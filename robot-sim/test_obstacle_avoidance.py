import math
import unittest

from obstacle_avoidance import ObstacleAvoider


DT = 0.05


class FakeHAL:
    def __init__(self, kind="object", blocked=False):
        self.kind = kind
        self.blocked = blocked
        self.person_cleared = False
        self.heading = 0.0
        self.path_length = 0.0
        self.commands = []

    def classify_obstacle(self):
        return self.kind

    def read_ultrasonic(self):
        if self.kind == "person":
            return 999.0 if self.person_cleared else 25.0
        if self.blocked:
            return 25.0
        if self.path_length >= 0.10:
            return 999.0
        if self.heading > 0.25:
            return 140.0
        if self.heading < -0.25:
            return 70.0
        return 25.0

    def read_line_sensors(self):
        return False, False, False, False

    def set_motion(self, speed, turn):
        self.commands.append((float(speed), float(turn)))
        angular_velocity = float(turn) * 0.024
        self.heading -= angular_velocity * DT
        self.path_length += abs(float(speed) * 0.007 * DT)

    def stop(self):
        self.set_motion(0.0, 0.0)


class ObstacleAvoiderTest(unittest.TestCase):
    def test_scans_both_sides_and_uses_wider_side(self):
        hal = FakeHAL()
        detected = []
        cleared = []
        avoider = ObstacleAvoider(
            hal,
            on_obstacle=lambda distance: detected.append(distance),
            on_cleared=lambda: cleared.append(True),
        )

        for _ in range(500):
            avoider.tick(DT)
            if not avoider.active and avoider.last_result == "avoided":
                break

        self.assertEqual(len(detected), 1)
        self.assertEqual(len(cleared), 1)
        self.assertEqual(avoider.last_result, "avoided")
        self.assertEqual(avoider.chosen_side, "left")
        self.assertGreater(avoider.left_distance_cm, avoider.right_distance_cm)
        self.assertTrue(any(speed > 0 for speed, _turn in hal.commands))

    def test_person_is_not_bypassed(self):
        hal = FakeHAL(kind="person")
        avoider = ObstacleAvoider(hal)

        for _ in range(30):
            avoider.tick(DT)
        self.assertEqual(avoider.state, "wait_person")
        self.assertFalse(any(speed > 0 for speed, _turn in hal.commands))

        hal.person_cleared = True
        for _ in range(50):
            avoider.tick(DT)
        self.assertFalse(avoider.active)
        self.assertEqual(avoider.last_result, "person_cleared")

    def test_fully_blocked_path_stays_stopped(self):
        hal = FakeHAL(blocked=True)
        avoider = ObstacleAvoider(hal, max_scan_attempts=2)

        for _ in range(500):
            avoider.tick(DT)

        self.assertTrue(avoider.active)
        self.assertEqual(avoider.state, "blocked_wait")
        self.assertEqual(avoider.status()["attempt"], 2)
        self.assertFalse(any(speed > 0 for speed, _turn in hal.commands))


if __name__ == "__main__":
    unittest.main()
