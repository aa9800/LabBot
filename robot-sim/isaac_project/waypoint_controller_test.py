"""Isaac 없이도 웨이포인트 제어기의 트랙 이탈을 빠르게 검증한다."""
import json
import math
import os

from waypoint_controller import WaypointPatrolController


DT = 1.0 / 60.0


def distance_to_segment(point, start, end):
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class MockHAL:
    def __init__(self, track):
        self.x, self.y = track[0]
        self.heading = math.atan2(track[1][1] - self.y, track[1][0] - self.x)

    def _position_and_heading(self):
        return self.x, self.y, math.cos(self.heading), math.sin(self.heading)

    def read_ultrasonic(self):
        return 999.0

    def try_read_qr(self):
        return None

    def stop(self):
        self.set_motion(0.0, 0.0)

    def set_motion(self, speed, turn):
        velocity = speed * 0.0035
        angular_velocity = turn * 0.012
        self.heading -= angular_velocity * DT
        self.x += velocity * math.cos(self.heading) * DT
        self.y += velocity * math.sin(self.heading) * DT


def main():
    path = os.path.join(os.path.dirname(__file__), "scene", "qr_anchors.json")
    with open(path, "r", encoding="utf-8") as stream:
        track = [tuple(point) for point in json.load(stream)["track_points"]]
    hal = MockHAL(track)
    controller = WaypointPatrolController(hal, track)
    max_error = 0.0
    for _ in range(60 * 180):
        controller.tick(DT)
        error = min(distance_to_segment((hal.x, hal.y), track[i], track[i + 1]) for i in range(len(track) - 1))
        max_error = max(max_error, error)
    if max_error > 0.35:
        raise AssertionError(f"웨이포인트 트랙 이탈: {max_error:.3f}m")

    guide_hal = MockHAL(track)
    arrived = []
    guide = WaypointPatrolController(guide_hal, track, on_guide_arrived=lambda task: arrived.append(task))
    guide.start_guide({
        "task_id": "test-guide",
        "item_name": "마이크로피펫 세트",
        "shelf_code": "A-01",
        "waypoints": [(0.0, -1.0), (0.0, -4.0), (-2.6, -5.2)],
    })
    for _ in range(60 * 60):
        guide.tick(DT)
        if guide.guide_status()["status"] == "arrived":
            break
    if not arrived:
        raise AssertionError(f"물품 안내 목적지 미도착: {guide.guide_status()}")
    if math.hypot(guide_hal.x + 2.6, guide_hal.y + 5.2) > 0.28:
        raise AssertionError("물품 안내 정차 좌표 오차 초과")
    guide.finish_guide()
    if guide.guide_status()["status"] != "idle":
        raise AssertionError("안내 완료 뒤 순찰 모드로 복귀하지 못함")

    print(f"WAYPOINT_CONTROLLER_TEST_OK max_error={max_error:.3f}m guide=A-01 position=({guide_hal.x:.2f},{guide_hal.y:.2f})")


if __name__ == "__main__":
    main()
