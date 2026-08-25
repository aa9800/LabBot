"""Webots 3D 시뮬레이터용 HAL.

robot-sim/sim/hal_sim.py(pygame용)와 정확히 같은 5개 메서드를 구현한다:
    read_line_sensors() / read_ultrasonic() / try_read_qr() / set_motion() / stop()

controller.py의 PatrolController는 이 클래스가 Webots를 쓰는지조차 모른다 —
그냥 hal 인자로 이 객체를 건네받아 5개 메서드만 호출한다. 그래서 controller.py는
단 한 줄도 고칠 필요가 없다.

물리 센서(DistanceSensor, 지상 IR센서)는 전부 뺐다: 트랙 박스에 바퀴가 걸리는 문제,
장애물을 지워도 계속 같은 값이 나오는 문제(자기 몸통/바닥을 잘못 감지) 등 물리 엔진
쪽에서 예상 못한 문제가 반복돼서, pygame 버전과 똑같은 "좌표 계산" 방식으로 전부
바꿨다 — GPS 좌표 + Supervisor로 실제 위치를 직접 읽어서 판단하기 때문에 물리
엔진의 raycast/충돌 특성에 좌우되지 않는다.
"""
import math

# lab.wbt의 4m x 2.6m 순찰선과 반드시 같은 좌표를 유지할 것.
# Webots는 발표·통합 시연의 주 환경이고 pygame은 이 controller의 빠른 회귀 테스트에만 쓴다.
TRACK_POINTS_M = [(-2.0, -1.3), (2.0, -1.3), (2.0, 1.3), (-2.0, 1.3), (-2.0, -1.3)]

LINE_SENSOR_SPAN = 0.03      # 4채널 센서의 좌우 폭(m)
LINE_SENSOR_LOOKAHEAD = 0.05  # 로봇 앞쪽으로 얼마나 내다보는지(m)
LINE_TOLERANCE = 0.015        # 트랙 선으로 인정하는 거리(m)

# lab.wbt에 있는, 장애물로 취급할 노드의 DEF 이름들. 여기 없는 이름은 무시된다.
OBSTACLE_DEF_NAMES = ("OBSTACLE_1",)

WHEEL_RADIUS = 0.0205   # m, e-puck 실측 규격
AXLE_LENGTH = 0.052     # m, 두 바퀴 사이 거리
SPEED_SCALE = 0.001     # pygame의 speed=70 -> 0.07 m/s로 변환
MAX_WHEEL_VELOCITY = 6.28  # rad/s, 이 이상은 e-puck 모터가 못 낸다고 보고 자른다(clamp)

NO_OBSTACLE_CM = 999.0  # 감지되는 장애물이 하나도 없을 때 돌려주는 값 (OBSTACLE_STOP_DISTANCE보다 훨씬 큼)


def _dist_point_to_segment(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _distance_to_track(point):
    return min(
        _dist_point_to_segment(point, TRACK_POINTS_M[i], TRACK_POINTS_M[i + 1])
        for i in range(len(TRACK_POINTS_M) - 1)
    )


class WebotsHAL:
    def __init__(self, robot, timestep_ms, checkpoints):
        """
        robot: Webots Robot() 인스턴스 (labkeeper_controller.py에서 만들어서 넘겨준다).
               lab.wbt에서 이 로봇의 supervisor 필드를 TRUE로 켜둬야 장애물 좌표를
               직접 읽어올 수 있다.
        timestep_ms: 센서를 몇 ms마다 갱신할지 (world의 basicTimeStep과 맞춘다)
        checkpoints: [{"name": "선반A", "x":.., "y":.., "radius":..}, ...]
        """
        self.checkpoints = checkpoints
        self.last_speed = 0.0
        self.last_turn = 0.0

        self.left_motor = robot.getDevice("left wheel motor")
        self.right_motor = robot.getDevice("right wheel motor")
        self.left_motor.setPosition(float("inf"))  # 속도 제어 모드로 전환
        self.right_motor.setPosition(float("inf"))
        self.left_motor.setVelocity(0.0)
        self.right_motor.setVelocity(0.0)

        self.gps = robot.getDevice("gps")
        self.gps.enable(timestep_ms)
        self.gps_front = robot.getDevice("gps_front")
        self.gps_front.enable(timestep_ms)

        # Supervisor 권한으로 장애물 노드의 실제 위치를 읽어온다. robot 참조만 들고 있고,
        # 노드 자체는 매 틱 새로 찾는다(캐시하지 않음) — 실행 중에 사용자가 장애물을 직접
        # 지우거나 옮겨도(라이브 편집) 죽지 않고 "장애물 없음"으로 자연스럽게 처리된다.
        self._robot = robot

    def _position_and_heading(self):
        cx, cy, _ = self.gps.getValues()
        fx, fy, _ = self.gps_front.getValues()
        dx, dy = fx - cx, fy - cy
        norm = math.hypot(dx, dy)
        if norm < 1e-6:
            # 시작 순간처럼 두 GPS가 아직 같은 값을 줄 때의 기본값(정면 = world +x)
            dx, dy, norm = 1.0, 0.0, 1.0
        return cx, cy, dx / norm, dy / norm

    def read_line_sensors(self):
        """pygame 버전(sim/engine.py의 Robot.line_sensors)과 동일한 방식:
        로봇 앞쪽 지점을 중심으로 좌우 4곳을 검사해서 트랙 중심선과의 거리로 판정한다."""
        cx, cy, fwd_x, fwd_y = self._position_and_heading()
        perp_x, perp_y = -fwd_y, fwd_x  # 진행방향에 수직인 방향
        look_x = cx + fwd_x * LINE_SENSOR_LOOKAHEAD
        look_y = cy + fwd_y * LINE_SENSOR_LOOKAHEAD

        readings = []
        for k in (-1.5, -0.5, 0.5, 1.5):
            sx = look_x + perp_x * k * (LINE_SENSOR_SPAN / 3)
            sy = look_y + perp_y * k * (LINE_SENSOR_SPAN / 3)
            readings.append(_distance_to_track((sx, sy)) <= LINE_TOLERANCE)
        return tuple(readings)

    def read_ultrasonic(self):
        """실제 초음파 센서 대신, lab.wbt에 있는 장애물 노드들의 실시간 좌표
        (Supervisor로 직접 읽음)와 로봇 사이의 평면 거리를 cm로 돌려준다.
        가장 가까운 장애물까지의 거리를 쓴다. 장애물이 하나도 없으면(지워졌으면) NO_OBSTACLE_CM."""
        cx, cy, _, _ = self._position_and_heading()
        best = NO_OBSTACLE_CM
        for name in OBSTACLE_DEF_NAMES:
            node = self._robot.getFromDef(name)
            if node is None:
                continue  # 지워졌거나 아직 없음 — 장애물 없는 것으로 처리
            field = node.getField("translation")
            if field is None:
                continue
            ox, oy, _ = field.getSFVec3f()
            d_cm = math.hypot(cx - ox, cy - oy) * 100.0
            if d_cm < best:
                best = d_cm
        return best

    def try_read_qr(self):
        """실제 QR 이미지 인식 대신, 로봇의 GPS 좌표가 체크포인트 반경 안에 들어왔는지로
        판정한다 — pygame 버전의 nearby_marker()와 같은 역할이다."""
        x, y, _, _ = self._position_and_heading()
        for cp in self.checkpoints:
            if math.hypot(x - cp["x"], y - cp["y"]) <= cp["radius"]:
                return cp["name"]
        return None

    def set_motion(self, speed, turn):
        """pygame 버전과 같은 (speed, turn) 값을 받아 좌우 바퀴 각속도로 변환한다."""
        self.last_speed = float(speed)
        self.last_turn = float(turn)
        v = speed * SPEED_SCALE          # m/s
        w = math.radians(turn)           # rad/s
        left_v = (v - w * AXLE_LENGTH / 2) / WHEEL_RADIUS
        right_v = (v + w * AXLE_LENGTH / 2) / WHEEL_RADIUS
        left_v = max(-MAX_WHEEL_VELOCITY, min(MAX_WHEEL_VELOCITY, left_v))
        right_v = max(-MAX_WHEEL_VELOCITY, min(MAX_WHEEL_VELOCITY, right_v))
        self.left_motor.setVelocity(left_v)
        self.right_motor.setVelocity(right_v)

    def stop(self):
        self.last_speed = 0.0
        self.last_turn = 0.0
        self.left_motor.setVelocity(0.0)
        self.right_motor.setVelocity(0.0)

    def telemetry_snapshot(self):
        """공통 5메서드 인터페이스를 바꾸지 않는 Webots 전용 관측값.

        판단 로직은 이 메서드를 사용하지 않고, 실행 로그만 읽는다. 나중에 IsaacHAL/RealHAL도
        같은 이름을 선택적으로 구현하면 로그 형식을 그대로 재사용할 수 있다.
        """
        x, y, fwd_x, fwd_y = self._position_and_heading()
        return {
            "x": round(x, 4),
            "y": round(y, 4),
            "heading_deg": round(math.degrees(math.atan2(fwd_y, fwd_x)), 2),
            "obstacle_cm": round(self.read_ultrasonic(), 2),
            "command_speed": self.last_speed,
            "command_turn": self.last_turn,
        }
