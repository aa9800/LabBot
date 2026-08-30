"""Isaac 대형 랩 맵용 경량 웨이포인트 순찰 제어기."""
import math
import os
import sys

_ROBOT_SIM_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROBOT_SIM_ROOT not in sys.path:
    sys.path.insert(0, _ROBOT_SIM_ROOT)

from obstacle_avoidance import ObstacleAvoider


def _wrap_angle(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


class WaypointPatrolController:
    def __init__(self, hal, track_points, on_scan=None, on_obstacle=None, on_obstacle_cleared=None,
                 on_guide_arrived=None):
        self.hal = hal
        self.track_points = track_points
        self.on_scan = on_scan
        self.on_obstacle = on_obstacle
        self.on_obstacle_cleared = on_obstacle_cleared
        self.on_guide_arrived = on_guide_arrived
        self.target_index = 1
        self.completed_laps = 0
        self._scanned_marker = None
        self._scan_elapsed = 0.0
        self._obstacle_active = False
        self._avoider = ObstacleAvoider(
            hal,
            on_obstacle=on_obstacle,
            on_cleared=on_obstacle_cleared,
        )
        self.guide_task = None
        self.guide_waypoint_index = 0

    def avoidance_status(self):
        return self._avoider.status()

    def patrol_status(self):
        """웹과 테스트가 현재 순찰 진행 상황을 동일하게 읽는다."""
        target = self.track_points[self.target_index]
        return {
            "status": "paused_for_guide" if self.guide_task else "patrolling",
            "waypoint_index": self.target_index,
            "waypoint_count": len(self.track_points),
            "completed_laps": self.completed_laps,
            "target_x": target[0],
            "target_y": target[1],
        }

    def start_guide(self, task):
        """순찰을 잠시 멈추고 물품/반납대 안내 경로를 시작한다."""
        waypoints = [tuple(point) for point in task.get("waypoints", [])]
        if not waypoints:
            raise ValueError("안내 경로 좌표가 없습니다.")
        self.guide_task = {**task, "waypoints": waypoints, "status": "navigating"}
        self.guide_waypoint_index = 0
        self._scanned_marker = None
        return self.guide_status()

    def finish_guide(self, status="completed"):
        previous = self.guide_status()
        self.guide_task = None
        self.guide_waypoint_index = 0
        self.hal.stop()
        # 현재 위치에서 가장 가까운 순찰 지점부터 자연스럽게 복귀한다.
        x, y, _, _ = self.hal._position_and_heading()
        self.target_index = min(
            range(len(self.track_points)),
            key=lambda idx: math.hypot(self.track_points[idx][0] - x, self.track_points[idx][1] - y),
        )
        previous["status"] = status
        return previous

    def guide_status(self):
        if not self.guide_task:
            return {"status": "idle"}
        return {
            key: value for key, value in self.guide_task.items() if key != "waypoints"
        } | {
            "waypoint_index": self.guide_waypoint_index,
            "waypoint_count": len(self.guide_task["waypoints"]),
        }

    def _drive_toward(self, target_x, target_y, speed_fast=62.0):
        x, y, forward_x, forward_y = self.hal._position_and_heading()
        dx, dy = target_x - x, target_y - y
        distance = math.hypot(dx, dy)
        current_heading = math.atan2(forward_y, forward_x)
        desired_heading = math.atan2(dy, dx)
        heading_error = _wrap_angle(desired_heading - current_heading)
        turn = max(-85.0, min(85.0, -math.degrees(heading_error) * 1.15))
        speed = speed_fast if abs(heading_error) < 0.35 else 24.0
        self.hal.set_motion(speed, turn)
        return distance

    def tick(self, dt):
        distance_cm = self.hal.read_ultrasonic()
        if self._avoider.tick(dt, distance_cm):
            self._obstacle_active = self._avoider.active
            return
        self._obstacle_active = False

        if self.guide_task:
            if self.guide_task["status"] == "arrived":
                self.hal.stop()
                return
            target_x, target_y = self.guide_task["waypoints"][self.guide_waypoint_index]
            distance = self._drive_toward(target_x, target_y, speed_fast=78.0)
            arrival_tolerance = max(0.05, float(self.guide_task.get("arrival_tolerance", 0.22)))
            if distance < arrival_tolerance:
                self.guide_waypoint_index += 1
                if self.guide_waypoint_index >= len(self.guide_task["waypoints"]):
                    self.guide_waypoint_index = len(self.guide_task["waypoints"]) - 1
                    self.guide_task["status"] = "arrived"
                    self.hal.stop()
                    if self.on_guide_arrived:
                        self.on_guide_arrived(dict(self.guide_task))
            return

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
            if self._scan_elapsed < 1.0:
                self.hal.stop()
                return
        else:
            self._scanned_marker = None

        x, y, forward_x, forward_y = self.hal._position_and_heading()
        target_x, target_y = self.track_points[self.target_index]
        dx, dy = target_x - x, target_y - y
        distance = math.hypot(dx, dy)
        if distance < 0.18:
            reached_index = self.target_index
            if reached_index == len(self.track_points) - 1:
                self.completed_laps += 1
            self.target_index = (self.target_index + 1) % len(self.track_points)
            target_x, target_y = self.track_points[self.target_index]
            dx, dy = target_x - x, target_y - y

        self._drive_toward(target_x, target_y)
