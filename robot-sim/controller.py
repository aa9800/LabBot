"""실사 순찰 판단 로직 — 라인트래킹 + 정지스캔 + 장애물 회피.

HAL(hal 인자)에만 의존하고 pygame이나 GPIO를 직접 건드리지 않는다.
그래서 SimHAL로 연습한 이 파일을 나중에 RealHAL로 그대로 바꿔 끼울 수 있다.
"""
from obstacle_avoidance import ObstacleAvoider


SPEED = 100.0
TURN_GAIN = 100.0
# 40cm는 실내에서 너무 멀었다 — 책상·벽 옆을 지나기만 해도 멈춰서 순찰이 진행되지
# 않았다. 그래서 20cm로 낮췄는데, 이번에는 방 문턱을 16.4cm로 읽고 앞으로 가지
# 않았다. 초음파 하나로는 높이를 모르므로 "넘어가면 되는 낮은 턱"과 "멈춰야 하는
# 벽"을 구분하지 못한다.
#
# 그래서 10cm로 더 낮춘다. 라즈봇 차체가 작고 초음파 최소 측정이 2cm라 물리적으로는
# 가능하지만, 반응에 걸리는 시간을 감안하면 여유가 빠듯하다:
#     중앙값 필터 약 100ms + 제어 루프 50ms = 최소 150ms
# 실제 주행 속도를 재서 이 값이 충분한지 확인할 것. 부족하면 근본 해법은 초음파를
# 살짝 위로 기울여 바닥·문턱이 원뿔에서 빠지게 하는 것이다(코드 변경 불필요).
OBSTACLE_STOP_DISTANCE = 10
# 정지 기준과 해제 기준을 같게 두면 물리 엔진 관성이나 실제 초음파 노이즈 때문에
# 경계에서 감지와 해제가 반복된다. 히스테리시스로 이벤트 스팸과 모터 떨림을 막는다.
OBSTACLE_CLEAR_DISTANCE = 18
SCAN_HOLD_SECONDS = 1.0

# 거리에 따라 속도를 미리 줄인다.
#
# 임계값만 낮추는 것으로는 부족했다. PWM 60(실측 24.9cm/s)으로 벽에 다가가며 잰
# 기록이다:
#     1.8s  17.0cm  모터 60
#     2.0s   9.0cm  모터  0   <- 10cm 아래로 떨어져 정지 명령
#     2.1s   5.8cm  모터  0   <- 관성으로 3.5cm 더 감
# 임계를 넘어 4.5cm 를 더 간다. 전속(PWM 100, 약 41cm/s)이면 그 두 배라 박는다.
#
# 그렇다고 임계를 18cm 로 올리면 방 문턱(16.4cm)에 다시 걸린다. 그래서 속도를
# 거리에 따라 줄인다 — 가까워질수록 느려지므로 관성 여유가 저절로 확보되고,
# 문턱 근처에서는 이미 느려서 10cm 임계로도 충분하다.
CAUTION_DISTANCE = 40      # 이보다 멀면 전속
CAUTION_MIN_SPEED = 25     # 아무리 가까워도 이보다는 느려지지 않는다(못 움직이면 곤란)


def speed_cap_for_distance(distance_cm):
    """앞이 가까울수록 낮은 상한을 돌려준다. 0~100 스케일."""
    if distance_cm is None or distance_cm >= CAUTION_DISTANCE:
        return SPEED
    if distance_cm <= OBSTACLE_STOP_DISTANCE:
        return 0.0
    # 정지선~주의선 사이를 선형으로 잇는다.
    span = CAUTION_DISTANCE - OBSTACLE_STOP_DISTANCE
    ratio = (distance_cm - OBSTACLE_STOP_DISTANCE) / span
    return max(CAUTION_MIN_SPEED, SPEED * ratio)


class PatrolController:
    def __init__(self, hal, on_scan=None, on_obstacle=None, on_obstacle_cleared=None):
        self.hal = hal
        self.on_scan = on_scan
        self.on_obstacle = on_obstacle
        self.on_obstacle_cleared = on_obstacle_cleared
        self._scanned_marker = None
        self._scan_elapsed = 0.0
        self._obstacle_active = False
        self._avoider = ObstacleAvoider(
            hal,
            on_obstacle=on_obstacle,
            on_cleared=on_obstacle_cleared,
            stop_distance_cm=OBSTACLE_STOP_DISTANCE,
            clear_distance_cm=OBSTACLE_CLEAR_DISTANCE,
        )

    def avoidance_status(self):
        return self._avoider.status()

    def tick(self, dt, distance_cm=None):
        """dt: 이번 틱에 흐른 시뮬레이션 시간(초). 실제 시계가 아니라 이 값 기준으로만 판단한다."""
        distance = self.hal.read_ultrasonic() if distance_cm is None else distance_cm
        if self._avoider.tick(dt, distance):
            self._obstacle_active = self._avoider.active
            return
        self._obstacle_active = False

        qr = self.hal.try_read_qr()
        if qr:
            if self._scanned_marker != qr:
                self._scanned_marker = qr
                self._scan_elapsed = 0.0
                self.hal.stop()
                if self.on_scan:
                    self.on_scan(qr)
                return
            self._scan_elapsed += dt
            if self._scan_elapsed < SCAN_HOLD_SECONDS:
                self.hal.stop()
                return
        else:
            self._scanned_marker = None

        left, mid_l, mid_r, right = self.hal.read_line_sensors()
        if mid_l and mid_r:
            turn = 0.0
        elif mid_l:
            turn = -30.0
        elif mid_r:
            turn = 30.0
        elif left:
            turn = -TURN_GAIN
        elif right:
            turn = TURN_GAIN
        else:
            turn = 25.0  # 라인을 일시 이탈했을 때 완만한 선회로 부드럽게 재진입

        # 자동순찰도 수동 주행과 같은 감속 곡선을 쓴다. 예전에는 여기서 SPEED를
        # 그대로 써서, 회피가 발동하는 10cm 까지 전속으로 달리다 관성으로 박았다.
        self.hal.set_motion(speed_cap_for_distance(distance), turn)
