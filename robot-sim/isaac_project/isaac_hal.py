"""Isaac Sim용 HAL.

robot-sim/sim/hal_sim.py(pygame), robot-sim/webots_project/.../webots_hal.py(Webots)와
정확히 같은 5개 메서드를 구현한다: read_line_sensors() / read_ultrasonic() / try_read_qr() /
set_motion() / stop().

controller.py의 PatrolController는 이 클래스가 Isaac Sim을 쓰는지조차 모른다 — 그냥 hal
인자로 이 객체를 건네받아 5개 메서드만 호출한다. 그래서 controller.py는 단 한 줄도 고칠
필요가 없다(Webots와 동일한 원칙).

⚠️ 지금은 실제 Raspbot이 아니라 Isaac Sim 기본 제공 Jetbot을 물리 섀시로 쓴다(2단계
실측+URDF 전까지의 임시 조치) — Webots가 처음에 E-puck을 임시로 썼던 것과 같은 이유다.
Jetbot은 좌/우 바퀴 2개짜리 차동구동이고, 실제 Raspbot은 바퀴 4개(TT모터 4개) 스키드
스티어라서 나중에 진짜 URDF로 바꾸면 set_motion()의 바퀴 매핑 부분만 수정하면 된다
(좌표 계산 방식의 read_* 메서드들은 그대로 재사용 가능).

Webots 버전과 똑같이 "좌표 계산" 방식을 쓴다 — 실제 라인센서/초음파 물리 시뮬레이션이
아니라, 로봇의 실제 pose와 트랙/장애물의 실제 위치를 직접 읽어서 판정한다. 이유도 같다:
물리 센서 시뮬레이션은 노이즈·충돌 문제가 반복돼서 판단 로직 검증 단계에서는 좌표 계산이
훨씬 안정적이다(webots_hal.py의 "deterministic demo mode" 설명과 동일한 논리).
"""
import math

from pxr import UsdGeom

# 테스트용 작은 사각 순찰로(m 단위) — pygame/Webots와 같은 방식으로 4개 꼭짓점을 잇는 루프.
# 실제 연구실 배치가 아니라 controller.py 판단 로직(라인트래킹/장애물정지/QR정지)이
# Isaac Sim 위에서도 똑같이 동작하는지만 확인하는 최소 트랙이다.
TRACK_POINTS_M = [(-1.0, -0.6), (1.0, -0.6), (1.0, 0.6), (-1.0, 0.6), (-1.0, -0.6)]

LINE_SENSOR_SPAN = 0.03
LINE_SENSOR_LOOKAHEAD = 0.05
LINE_TOLERANCE = 0.02

# 실제 Raspbot 실측값(2026-08-26, 사용자 직접 측정): 바퀴 지름 6.5cm -> 반지름 0.0325m.
# (참고: Jetbot 공식 예제 값과 우연히 같은 숫자라 지금 Jetbot 임시 섀시로도 그대로 맞는다.)
WHEEL_RADIUS = 0.0325
# 실제 Raspbot 실측값(2026-08-26): 바퀴 바깥쪽 면 기준 16cm - 바퀴 두께 2.5cm = 13.5cm
# = 0.135m (중심축 사이 거리). Jetbot 기본값(0.1125m)보다 넓어서 회전 반경 계산에 실제로
# 반영됨 — 이제 turn 동작이 Jetbot 임시 섀시에서도 실제 Raspbot 트랙 폭 기준으로 계산된다.
AXLE_LENGTH = 0.135
SPEED_SCALE = 0.001  # pygame/Webots와 동일 스케일 — speed=70 -> 0.07 m/s

NO_OBSTACLE_CM = 999.0


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


class IsaacHAL:
    def __init__(self, stage, jetbot_articulation, obstacle_prim_path, checkpoints):
        """
        stage: omni.usd 스테이지 (장애물 prim의 실시간 위치를 직접 읽을 때 씀 —
               Webots의 Supervisor.getFromDef()와 같은 역할)
        jetbot_articulation: isaacsim.core.prims.Articulation (Jetbot)
        obstacle_prim_path: 장애물로 취급할 prim 경로(예: "/World/Obstacle") — 없으면 None
        checkpoints: [{"name": "A", "x":.., "y":.., "radius":..}, ...]
        """
        self.stage = stage
        self.robot = jetbot_articulation
        self.obstacle_prim_path = obstacle_prim_path
        self.checkpoints = checkpoints
        self.last_speed = 0.0
        self.last_turn = 0.0

        dof_names = self.robot.dof_names
        self._left_idx = dof_names.index("left_wheel_joint")
        self._right_idx = dof_names.index("right_wheel_joint")
        self._n_dof = len(dof_names)

    def _position_and_heading(self):
        pos, quat = self.robot.get_world_poses()
        x, y = float(pos[0][0]), float(pos[0][1])
        # quat: (w, x, y, z) — z축 회전만 있다고 가정(평면 위 로봇)하고 heading 추출
        qw, qx, qy, qz = (float(v) for v in quat[0])
        heading = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
        return x, y, math.cos(heading), math.sin(heading)

    def read_line_sensors(self):
        """pygame/Webots와 동일한 방식: 로봇 앞쪽 4개 지점이 트랙 중심선과 얼마나
        가까운지로 판정한다."""
        cx, cy, fwd_x, fwd_y = self._position_and_heading()
        perp_x, perp_y = -fwd_y, fwd_x
        look_x = cx + fwd_x * LINE_SENSOR_LOOKAHEAD
        look_y = cy + fwd_y * LINE_SENSOR_LOOKAHEAD
        readings = []
        for k in (-1.5, -0.5, 0.5, 1.5):
            sx = look_x + perp_x * k * (LINE_SENSOR_SPAN / 3)
            sy = look_y + perp_y * k * (LINE_SENSOR_SPAN / 3)
            readings.append(_distance_to_track((sx, sy)) <= LINE_TOLERANCE)
        return tuple(readings)

    def read_ultrasonic(self):
        """장애물 prim의 실제 좌표를 USD 스테이지에서 직접 읽어(Webots의 getFromDef와
        같은 역할) 로봇과의 평면 거리를 cm로 돌려준다. 장애물이 없으면 NO_OBSTACLE_CM."""
        if not self.obstacle_prim_path:
            return NO_OBSTACLE_CM
        prim = self.stage.GetPrimAtPath(self.obstacle_prim_path)
        if not prim or not prim.IsValid():
            return NO_OBSTACLE_CM
        xform = UsdGeom.Xformable(prim)
        translation = xform.ComputeLocalToWorldTransform(0).ExtractTranslation()
        cx, cy, _, _ = self._position_and_heading()
        return math.hypot(cx - translation[0], cy - translation[1]) * 100.0

    def try_read_qr(self):
        """GPS 좌표 대신 로봇 pose가 체크포인트 반경 안인지로 판정 — Webots와 동일."""
        x, y, _, _ = self._position_and_heading()
        for cp in self.checkpoints:
            if math.hypot(x - cp["x"], y - cp["y"]) <= cp["radius"]:
                return cp["name"]
        return None

    def set_motion(self, speed, turn):
        """pygame/Webots와 같은 (speed, turn) 컨벤션 -> Jetbot 좌/우 바퀴 각속도.

        ⚠️ Jetbot은 바퀴 2개(차동구동)라 이 변환식이 그대로 맞지만, 실제 Raspbot(바퀴
        4개, 스키드 스티어)로 바꿀 때는 좌측 2개/우측 2개에 같은 값을 넣는 방식으로
        바뀌어야 한다 — 그때 이 메서드만 고치면 되고 controller.py는 무관하다."""
        self.last_speed = float(speed)
        self.last_turn = float(turn)
        v = speed * SPEED_SCALE
        w = math.radians(turn)
        left_v = (v - w * AXLE_LENGTH / 2) / WHEEL_RADIUS
        right_v = (v + w * AXLE_LENGTH / 2) / WHEEL_RADIUS

        import numpy as np

        velocities = np.zeros((1, self._n_dof))
        velocities[0, self._left_idx] = left_v
        velocities[0, self._right_idx] = right_v
        self.robot.set_joint_velocities(velocities)

    def stop(self):
        self.set_motion(0.0, 0.0)
