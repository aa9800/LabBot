import math
import os
import numpy as np
import cv2
from pxr import Usd, UsdGeom, UsdPhysics
from lab_world import LAB_TRACK_POINTS_M, LAB_ZONES

LINE_SENSOR_SPAN = 0.08
LINE_SENSOR_LOOKAHEAD = 0.04
LINE_TOLERANCE = 0.08

# 실제 Raspbot 실측값(2026-08-26): 바퀴 지름 6.5cm, 트랙 폭 13.5cm
WHEEL_RADIUS = 0.0325
AXLE_LENGTH = 0.135
# 명령값(0~100)을 속도로 바꾸는 배율.
#
# 0.007 이면 speed=100 이 0.7m/s 다. 물리는 60Hz 고정이라 적분은 정확하지만,
# 렌더링이 무거우면 시뮬 시간이 실제 시간보다 느리게 흘러서 화면에서는 더
# 느려 보인다. 시연에서 "너무 느리다"는 지적이 있어 올렸다.
#
# 회전도 같은 비율로 올린다. 직진만 빠르게 하면 코너에서 목표를 지나친다.
#
# 환경변수로 조절할 수 있게 둔다 - 아이작을 띄운 채로 값을 바꿔가며 맞추는
# 편이 코드를 고치고 재시작하는 것보다 빠르다.
#   LABKEEPER_ISAAC_SPEED_SCALE=0.007  로 예전 속도로 되돌릴 수 있다.
SPEED_SCALE = float(os.environ.get("LABKEEPER_ISAAC_SPEED_SCALE", "0.012"))
ANGULAR_SPEED_SCALE = float(os.environ.get("LABKEEPER_ISAAC_TURN_SCALE", "0.041"))

NO_OBSTACLE_CM = 999.0
ULTRASONIC_MAX_M = 3.0
ROBOT_CLEARANCE_M = 0.11
FPV_WIDTH = int(os.environ.get("LABKEEPER_FPV_WIDTH", "960"))
FPV_HEIGHT = int(os.environ.get("LABKEEPER_FPV_HEIGHT", "540"))


def _dist_point_to_segment(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _distance_to_track(point):
    return min(
        _dist_point_to_segment(point, LAB_TRACK_POINTS_M[i], LAB_TRACK_POINTS_M[i + 1])
        for i in range(len(LAB_TRACK_POINTS_M) - 1)
    )


def _ray_aabb_distance(origin_x, origin_y, direction_x, direction_y, bounds, max_distance):
    """2D 전방 광선과 축 정렬 충돌 경계의 첫 교차 거리(m)를 반환한다."""
    min_x, min_y, max_x, max_y = bounds
    near, far = 0.0, float(max_distance)
    for origin, direction, lower, upper in (
        (origin_x, direction_x, min_x, max_x),
        (origin_y, direction_y, min_y, max_y),
    ):
        if abs(direction) < 1e-8:
            if origin < lower or origin > upper:
                return None
            continue
        first = (lower - origin) / direction
        second = (upper - origin) / direction
        if first > second:
            first, second = second, first
        near = max(near, first)
        far = min(far, second)
        if near > far:
            return None
    return near if 0.0 <= near <= max_distance else None


class IsaacHAL:
    def __init__(self, stage, jetbot_articulation, obstacle_prim_path, checkpoints=None, camera=None):
        """
        stage: omni.usd 스테이지 (장애물 prim 및 로봇 위치 조회)
        jetbot_articulation: isaacsim.core.prims.Articulation (Yahboom Raspbot 4WD 모델)
        obstacle_prim_path: 장애물 prim 경로 (예: "/World/Obstacle")
        checkpoints: [{"name": "기기실-1", "x":.., "y":.., "radius":..}, ...]
        camera: isaacsim.sensors.camera.Camera (실제 3D 렌더링 카메라)
        """
        self.stage = stage
        self.robot = jetbot_articulation
        self.camera = camera
        self.obstacle_prim_path = obstacle_prim_path
        self.checkpoints = checkpoints if checkpoints is not None else [z["checkpoint"] for z in LAB_ZONES]
        self.last_speed = 0.0
        self.last_turn = 0.0
        self.cam_pan = 90
        self.cam_tilt = 90
        # 방향키를 누르고 있는 동안 유지되는 이동 방향(-1/0/+1).
        self._servo_dir_pan = 0
        self._servo_dir_tilt = 0
        self._last_valid_frame = np.zeros((FPV_HEIGHT, FPV_WIDTH, 3), dtype=np.uint8)
        self._cached_dist = NO_OBSTACLE_CM
        self._cached_obstacle_kind = "none"

        dof_names = self.robot.dof_names
        self._left_indices = [
            dof_names.index(name)
            for name in ("left_front_wheel_joint", "left_rear_wheel_joint")
        ]
        self._right_indices = [
            dof_names.index(name)
            for name in ("right_front_wheel_joint", "right_rear_wheel_joint")
        ]
        self._n_dof = len(dof_names)
        self._static_colliders = self._build_static_collider_cache()
        print(f"[IsaacHAL] 고정 구조물 초음파 맵 {len(self._static_colliders)}개 로드")

    def _build_static_collider_cache(self):
        """USD CollisionAPI가 붙은 벽·파티션·가구를 2D 센서 경계로 캐시한다.

        바닥과 로봇보다 높은 상판은 전방 초음파/차체 충돌 대상에서 제외한다. 매 틱 USD를
        순회하지 않고 시작 시 한 번만 계산하므로 RTX 렌더링 반응성을 해치지 않는다.
        """
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
        colliders = []
        for prim in self.stage.Traverse():
            path = str(prim.GetPath())
            if path == self.obstacle_prim_path or path.startswith("/World/Raspbot"):
                continue
            try:
                if not prim.HasAPI(UsdPhysics.CollisionAPI):
                    continue
                aligned = cache.ComputeWorldBound(prim).ComputeAlignedBox()
                lower, upper = aligned.GetMin(), aligned.GetMax()
                min_z, max_z = float(lower[2]), float(upper[2])
                # Raspbot 본체/초음파가 차지하는 높이와 겹치는 구조물만 감지한다.
                if max_z < 0.025 or min_z > 0.36:
                    continue
                lower_path = path.casefold()
                kind = "static_wall" if any(
                    token in lower_path
                    for token in ("wall", "partition", "divider", "door", "glass", "jamb", "architecture")
                ) else "static_fixture"
                colliders.append({
                    "path": path,
                    "kind": kind,
                    "bounds": (
                        float(lower[0]) - ROBOT_CLEARANCE_M,
                        float(lower[1]) - ROBOT_CLEARANCE_M,
                        float(upper[0]) + ROBOT_CLEARANCE_M,
                        float(upper[1]) + ROBOT_CLEARANCE_M,
                    ),
                })
            except Exception:
                continue
        return colliders

    def _static_obstacle_ahead(self, rx, ry, fx, fy):
        nearest = None
        for collider in self._static_colliders:
            distance = _ray_aabb_distance(
                rx, ry, fx, fy, collider["bounds"], ULTRASONIC_MAX_M
            )
            if distance is None or (nearest and distance >= nearest[0]):
                continue
            nearest = (distance, collider["kind"], collider["path"])
        return nearest

    def update_tick_cache(self):
        """메인 시뮬레이션 스레드에서만 호출하여 PhysX 상태를 캐시한다 (스레드 충돌 방지)."""
        try:
            pos, quat = self.robot.get_world_poses()
            x, y = float(pos[0][0]), float(pos[0][1])
            self._cached_z = float(pos[0][2])
            qw, qx, qy, qz = (float(v) for v in quat[0])
            heading = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
            self._cached_pose = (x, y, math.cos(heading), math.sin(heading))
        except Exception:
            pass

        # 초음파 거리 캐시: 이동 상자뿐 아니라 USD 벽·파티션·고정 가구까지 같은 센서로 판정.
        try:
            rx, ry, fx, fy = self._position_and_heading()
            candidates = []
            obs_prim = self.stage.GetPrimAtPath(self.obstacle_prim_path)
            if obs_prim.IsValid():
                xformable = UsdGeom.Xformable(obs_prim)
                world_xf = xformable.ComputeLocalToWorldTransform(0)
                obs_pos = world_xf.ExtractTranslation()
                ox, oy = float(obs_pos[0]), float(obs_pos[1])
                dx, dy = ox - rx, oy - ry
                fwd_dist = dx * fx + dy * fy
                lat_dist = abs(-dx * fy + dy * fx)
                if 0.03 < fwd_dist < ULTRASONIC_MAX_M and lat_dist < 0.25:
                    candidates.append((fwd_dist, "movable_object", self.obstacle_prim_path))

            static_hit = self._static_obstacle_ahead(rx, ry, fx, fy)
            if static_hit:
                candidates.append(static_hit)

            if candidates:
                distance_m, kind, path = min(candidates, key=lambda hit: hit[0])
                self._cached_dist = distance_m * 100.0
                self._cached_obstacle_kind = kind
                self._cached_obstacle_path = path
            else:
                self._cached_dist = NO_OBSTACLE_CM
                self._cached_obstacle_kind = "none"
                self._cached_obstacle_path = ""
        except Exception:
            self._cached_dist = NO_OBSTACLE_CM
            self._cached_obstacle_kind = "none"

    def _position_and_heading(self):
        if hasattr(self, "_cached_pose") and self._cached_pose is not None:
            return self._cached_pose
        try:
            pos, quat = self.robot.get_world_poses()
            x, y = float(pos[0][0]), float(pos[0][1])
            qw, qx, qy, qz = (float(v) for v in quat[0])
            heading = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
            return x, y, math.cos(heading), math.sin(heading)
        except Exception:
            return 0.0, 0.0, 1.0, 0.0

    def read_line_sensors(self):
        """pygame/Webots/실물과 동일한 4채널 라인센서 판정."""
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
        """전방 장애물 초음파 센서 거리 (cm) - 스레드 세이프."""
        if hasattr(self, "_cached_dist") and self._cached_dist is not None:
            return self._cached_dist
        return NO_OBSTACLE_CM

    def classify_obstacle(self):
        """우회기와 안전 엔진이 벽을 이동 물체 사고로 오인하지 않도록 종류를 제공한다."""
        return self._cached_obstacle_kind

    def obstacle_context(self):
        return {
            "kind": self._cached_obstacle_kind,
            "path": getattr(self, "_cached_obstacle_path", ""),
            "distance_cm": self.read_ultrasonic(),
        }

    def try_read_qr(self):
        """로봇이 9개 보관 구역 체크포인트 반경 내에 진입했을 때 구역명 반환."""
        rx, ry, _, _ = self._position_and_heading()
        for cp in self.checkpoints:
            dist = math.hypot(rx - cp["x"], ry - cp["y"])
            if dist <= cp["radius"]:
                return cp["name"]
        return None

    def set_motion(self, speed, turn):
        """속도(-100 ~ 100)와 회전(-100 ~ 100)으로 좌우 바퀴 각속도를 구동한다."""
        self.last_speed = float(speed)
        self.last_turn = float(turn)

        v = speed * SPEED_SCALE
        w = turn * ANGULAR_SPEED_SCALE

        # 웹/컨트롤러 계약: turn < 0은 좌회전, turn > 0은 우회전.
        left_v = (v + w * AXLE_LENGTH / 2) / WHEEL_RADIUS
        right_v = (v - w * AXLE_LENGTH / 2) / WHEEL_RADIUS

        try:
            velocities = np.zeros((1, self._n_dof))
            for index in self._left_indices:
                velocities[0, index] = left_v
            for index in self._right_indices:
                velocities[0, index] = right_v
            self.robot.set_joint_velocities(velocities)
        except Exception:
            pass

        # 경량 Raspbot은 실측 차동운동학으로 포즈를 직접 적분한다. 4개 바퀴 회전은
        # 위 set_joint_velocities에서 별도로 동기화된다.
        try:
            x, y, forward_x, forward_y = self._position_and_heading()
            heading = math.atan2(forward_y, forward_x) - w / 60.0
            next_x = x + v * math.cos(heading) / 60.0
            next_y = y + v * math.sin(heading) / 60.0
            z = getattr(self, "_cached_z", 0.0)
            half = heading / 2.0
            self.robot.set_world_poses(
                positions=np.array([[next_x, next_y, z]]),
                orientations=np.array([[math.cos(half), 0.0, 0.0, math.sin(half)]]),
            )
            self._cached_pose = (next_x, next_y, math.cos(heading), math.sin(heading))
        except Exception:
            pass

    def stop(self):
        self.set_motion(0.0, 0.0)

    # 방향키를 누르고 있는 동안 초당 몇 도씩 움직일 것인가. 실물 서보가
    # 부드럽게 흐르는 느낌과 맞춘 값이다.
    SERVO_HOLD_DEG_PER_S = 45.0

    def set_servo_angle(self, pan=None, tilt=None):
        if pan is not None:
            self.cam_pan = max(0, min(180, int(pan)))
        if tilt is not None:
            self.cam_tilt = max(0, min(180, int(tilt)))
        return {"pan": self.cam_pan, "tilt": self.cam_tilt}

    def set_servo_direction(self, pan_dir=None, tilt_dir=None):
        """방향(-1/0/+1)을 받아 그 쪽으로 계속 움직이게 한다.

        웹의 카메라 화살표는 각도가 아니라 방향을 보낸다 - 누르고 있는 동안
        로봇이 매 틱 목표를 밀어줘야 끊기지 않는다(실물 쪽과 같은 계약).
        아이작에는 이 콜백이 등록돼 있지 않아서, 방향 명령이 각도 콜백으로
        떨어지고 pan=None, tilt=None 이 되어 아무 일도 일어나지 않았다.
        """
        if pan_dir is not None:
            self._servo_dir_pan = int(pan_dir)
        if tilt_dir is not None:
            self._servo_dir_tilt = int(tilt_dir)
        return {"pan": self.cam_pan, "tilt": self.cam_tilt}

    def step_servo(self, dt):
        """눌린 방향대로 카메라 각도를 조금씩 옮긴다. 메인 루프가 매 틱 부른다."""
        step = self.SERVO_HOLD_DEG_PER_S * max(0.0, min(0.2, dt))
        if self._servo_dir_pan:
            self.cam_pan = max(0, min(180, self.cam_pan + self._servo_dir_pan * step))
        if self._servo_dir_tilt:
            self.cam_tilt = max(0, min(180, self.cam_tilt + self._servo_dir_tilt * step))
        return {"pan": self.cam_pan, "tilt": self.cam_tilt}

    def capture_fpv_frame(self):
        """Isaac Sim 3D RTX/OpenGL 뷰포트의 실시간 카메라 렌더링 프레임을 반환한다.
        실제 3D 실험실/물류창고 씬을 RTX 고화질 설정으로 웹 스트리밍한다."""
        if self.camera is not None:
            try:
                rgb = self.camera.get_rgb()
                if rgb is not None and getattr(rgb, "size", 0) > 0:
                    if np.issubdtype(rgb.dtype, np.floating):
                        rgb = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
                    else:
                        rgb = np.ascontiguousarray(rgb, dtype=np.uint8)

                    if rgb.shape[:2] != (FPV_HEIGHT, FPV_WIDTH):
                        rgb = cv2.resize(rgb, (FPV_WIDTH, FPV_HEIGHT), interpolation=cv2.INTER_AREA)
                    if rgb.ndim == 3 and rgb.shape[2] == 4:
                        self._last_valid_frame = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
                    elif rgb.ndim == 3 and rgb.shape[2] == 3:
                        self._last_valid_frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                    else:
                        self._last_valid_frame = cv2.cvtColor(rgb, cv2.COLOR_GRAY2BGR)
            except Exception as e:
                print(f"[IsaacHAL capture_fpv_frame error]: {e}")

        bgr = self._last_valid_frame.copy()

        # 텔레메트리 OSD 오버레이
        x, y, _, _ = self._position_and_heading()
        nearest_zone = self.try_read_qr()
        zone_map = {
            "일반실험실": "General Lab",
            "기기실-1": "Instrument-1",
            "기기실-2": "Instrument-2",
            "세포배양실": "Cell Culture",
            "시약보관실": "Reagent Storage",
            "냉동보관실": "Deep Freezer (-80C)",
            "냉장보관실": "Cold Storage (4C)",
            "소모품보관실": "Consumables",
            "안전장비함": "Safety Station",
        }
        zone_label = zone_map.get(nearest_zone, "Patrolling...") if nearest_zone else "Patrolling..."
        dist = self.read_ultrasonic()

        font_scale = max(0.42, min(0.62, FPV_WIDTH / 1800.0))
        cv2.putText(bgr, f"ISAAC BIOTECH TWIN (X:{x:.2f}, Y:{y:.2f})", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 120), 1, cv2.LINE_AA)
        cv2.putText(bgr, f"ZONE: {zone_label}", (12, FPV_HEIGHT - 18), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 220, 255), 1, cv2.LINE_AA)

        if dist < 50.0:
            kind = self._cached_obstacle_kind.replace("static_", "").upper()
            cv2.putText(bgr, f"{kind} {dist:.0f}cm", (FPV_WIDTH - 230, 24), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 255), 1, cv2.LINE_AA)
        return bgr
