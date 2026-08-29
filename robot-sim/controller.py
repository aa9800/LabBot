"""실사 순찰 판단 로직 — 라인트래킹 + 정지스캔 + 장애물 회피.

HAL(hal 인자)에만 의존하고 pygame이나 GPIO를 직접 건드리지 않는다.
그래서 SimHAL로 연습한 이 파일을 나중에 RealHAL로 그대로 바꿔 끼울 수 있다.
"""
from obstacle_avoidance import ObstacleAvoider


SPEED = 100.0
TURN_GAIN = 100.0
OBSTACLE_STOP_DISTANCE = 40
# 정지 기준과 해제 기준을 같게 두면 물리 엔진 관성이나 실제 초음파 노이즈 때문에
# 39.9cm/40.1cm 경계에서 감지와 해제가 반복된다. 10cm 히스테리시스로 이벤트 스팸과
# 모터의 떨림을 막는다.
OBSTACLE_CLEAR_DISTANCE = 50
SCAN_HOLD_SECONDS = 1.0


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

        self.hal.set_motion(SPEED, turn)
