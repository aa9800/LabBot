import math
import numpy as np
import cv2
from pxr import UsdGeom
from lab_world import LAB_TRACK_POINTS_M, LAB_ZONES

LINE_SENSOR_SPAN = 0.03
LINE_SENSOR_LOOKAHEAD = 0.05
LINE_TOLERANCE = 0.04

# 실제 Raspbot 실측값(2026-08-26): 바퀴 지름 6.5cm, 트랙 폭 13.5cm
WHEEL_RADIUS = 0.0325
AXLE_LENGTH = 0.135
SPEED_SCALE = 0.001

NO_OBSTACLE_CM = 999.0


def _dist_point_to_segment(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0, min(1, ((px - ax) * dx + (py - dy) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _distance_to_track(point):
    return min(
        _dist_point_to_segment(point, LAB_TRACK_POINTS_M[i], LAB_TRACK_POINTS_M[i + 1])
        for i in range(len(LAB_TRACK_POINTS_M) - 1)
    )


class IsaacHAL:
    def __init__(self, stage, jetbot_articulation, obstacle_prim_path, checkpoints=None):
        """
        stage: omni.usd 스테이지 (장애물 prim 및 로봇 위치 조회)
        jetbot_articulation: isaacsim.core.prims.Articulation (Jetbot)
        obstacle_prim_path: 장애물 prim 경로 (예: "/World/Obstacle")
        checkpoints: [{"name": "기기실-1", "x":.., "y":.., "radius":..}, ...]
        """
        self.stage = stage
        self.robot = jetbot_articulation
        self.obstacle_prim_path = obstacle_prim_path
        self.checkpoints = checkpoints if checkpoints is not None else [z["checkpoint"] for z in LAB_ZONES]
        self.last_speed = 0.0
        self.last_turn = 0.0
        self.cam_pan = 90
        self.cam_tilt = 90

        dof_names = self.robot.dof_names
        self._left_idx = dof_names.index("left_wheel_joint")
        self._right_idx = dof_names.index("right_wheel_joint")
        self._n_dof = len(dof_names)

    def _position_and_heading(self):
        pos, quat = self.robot.get_world_poses()
        x, y = float(pos[0][0]), float(pos[0][1])
        qw, qx, qy, qz = (float(v) for v in quat[0])
        heading = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
        return x, y, math.cos(heading), math.sin(heading)

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
        """장애물 prim과의 실제 거리를 cm 단위로 반환."""
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
        """로봇 위치가 체크포인트 반경 안인지 판정."""
        x, y, _, _ = self._position_and_heading()
        for cp in self.checkpoints:
            if math.hypot(x - cp["x"], y - cp["y"]) <= cp.get("radius", 0.35):
                return cp["name"]
        return None

    def scan_qr_now(self):
        """웹에서 [물품 QR 인식하기] 버튼을 눌렀을 때 실행되는 온디맨드 스캔 메서드.
        현재 로봇 위치가 9개 구역 중 어디인지 감지하고 해당 구역의 물품 QR 데이터를 반환한다."""
        detected_zone = self.try_read_qr()
        if not detected_zone:
            return None

        for z in LAB_ZONES:
            if z["name"] == detected_zone:
                # 해당 구역의 대표 물품 반환
                sample_item = z["sample_items"][0] if z["sample_items"] else "표준 시약"
                return f"ITEM:{detected_zone}:{sample_item}"
        return f"LOC:{detected_zone}"

    def set_motion(self, speed, turn):
        """속도(speed) 및 회전(turn) 명령을 Jetbot 차동구동 휠 속도로 변환."""
        self.last_speed = float(speed)
        self.last_turn = float(turn)
        v = speed * SPEED_SCALE
        w = math.radians(turn)
        left_v = (v - w * AXLE_LENGTH / 2) / WHEEL_RADIUS
        right_v = (v + w * AXLE_LENGTH / 2) / WHEEL_RADIUS

        velocities = np.zeros((1, self._n_dof))
        velocities[0, self._left_idx] = left_v
        velocities[0, self._right_idx] = right_v
        self.robot.set_joint_velocities(velocities)

    def stop(self):
        self.set_motion(0.0, 0.0)

    def set_servo_angle(self, pan=None, tilt=None):
        if pan is not None:
            self.cam_pan = int(pan)
        if tilt is not None:
            self.cam_tilt = int(tilt)

    def capture_fpv_frame(self):
        """가상 FPV 카메라 프레임을 생성한다 (웹 30 FPS 실시간 스트리밍용).
        로봇의 현재 좌표, 시야각, 전방 구역명, 초음파 거리를 렌더링하여 현실감 있는 FPV 시야를 제공한다."""
        x, y, fx, fy = self._position_and_heading()
        dist = self.read_ultrasonic()
        nearest_zone = self.try_read_qr() or "순찰 주행 중"

        # 320x240 캔버스 (실제 Raspbot과 동일 해상도)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        # 1. 배경: 위는 실험실 벽(밝은 회색), 아래는 바닥(진한 회색)
        horizon = 110 + int((self.cam_tilt - 90) * 0.8)
        frame[:horizon, :] = [45, 45, 52]   # 벽/천장
        frame[horizon:, :] = [25, 28, 30]   # 바닥

        # 2. 바닥 순찰 라인 (원근감 표시)
        line_offset = int((self.cam_pan - 90) * 1.2)
        cv2.line(frame, (160 - line_offset, horizon), (160 - line_offset * 2, 240), (220, 220, 220), 4)

        # 3. 전방 구역 선반 표시 (구역에 접근했을 때 시각적 선반 렌더링)
        if nearest_zone != "순찰 주행 중":
            cv2.rectangle(frame, (100, horizon - 50), (220, horizon + 20), (70, 110, 180), -1)
            cv2.rectangle(frame, (100, horizon - 50), (220, horizon + 20), (255, 255, 255), 2)
            cv2.putText(frame, nearest_zone, (110, horizon - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, "[QR TAG]", (125, horizon + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

        # 4. 전방 장애물 표시 (40cm 이내 접근 시 빨간 경고 박스)
        if dist < 45.0:
            cv2.rectangle(frame, (130, horizon - 30), (190, horizon + 30), (0, 0, 220), -1)
            cv2.putText(frame, f"OBSTACLE {dist:.0f}cm", (100, horizon - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 2)

        # 5. FPV 타임스탬프 및 위치 텍스트
        cv2.putText(frame, f"ISAAC DIGITAL TWIN (X:{x:.2f}, Y:{y:.2f})", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 120), 1)
        cv2.putText(frame, f"ZONE: {nearest_zone}", (10, 225), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

        return frame
