"""실사 순찰 판단 로직 — 라인트래킹 + 정지스캔 + 장애물 회피.

HAL(hal 인자)에만 의존하고 pygame이나 GPIO를 직접 건드리지 않는다.
그래서 SimHAL로 연습한 이 파일을 나중에 RealHAL로 그대로 바꿔 끼울 수 있다.
"""
SPEED = 70.0
TURN_GAIN = 90.0
OBSTACLE_STOP_DISTANCE = 40
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

    def tick(self, dt):
        """dt: 이번 틱에 흐른 시뮬레이션 시간(초). 실제 시계가 아니라 이 값 기준으로만 판단한다."""
        distance = self.hal.read_ultrasonic()
        if distance < OBSTACLE_STOP_DISTANCE:
            self.hal.stop()
            if not self._obstacle_active:
                # 새로 감지된 순간에만 콜백 — 정지해 있는 동안 매 틱마다 이벤트를 보내지 않는다.
                self._obstacle_active = True
                if self.on_obstacle:
                    self.on_obstacle(distance)
            return
        if self._obstacle_active:
            self._obstacle_active = False
            if self.on_obstacle_cleared:
                self.on_obstacle_cleared()

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
        if mid_l or mid_r:
            turn = 0.0
        elif left:
            turn = -TURN_GAIN
        elif right:
            turn = TURN_GAIN
        else:
            turn = TURN_GAIN  # 라인을 완전히 잃으면(대개 코너) 한쪽으로 돌며 재탐색

        self.hal.set_motion(SPEED, turn)
