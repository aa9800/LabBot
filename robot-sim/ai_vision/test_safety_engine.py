import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from safety_engine import LabSafetyEngine


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class LabSafetyEngineTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.engine = LabSafetyEngine(
            debounce_sec=5.0,
            rearm_sec=20.0,
            reagent_persistence_sec=20.0,
            clock=self.clock,
        )

    def evaluate(self, zone="일반실험실", classes=None, distance=999.0, obstacle_kind="unknown"):
        detections = [{"class_name": name} for name in (classes or [])]
        return self.engine.evaluate_frame_safety(zone, detections, distance, obstacle_kind)

    def test_persistent_path_obstruction_emits_only_once(self):
        first = self.evaluate(distance=30.0)
        self.clock.now = 5.0
        repeated = self.evaluate(distance=30.0)
        self.clock.now = 19.0
        still_present = self.evaluate(distance=30.0)

        self.assertEqual([event["rule_code"] for event in first], ["PATH_OBSTRUCTION"])
        self.assertEqual(repeated, [])
        self.assertEqual(still_present, [])

    def test_resolved_condition_rearms_after_clear_period(self):
        self.evaluate(distance=30.0)
        self.clock.now = 1.0
        self.evaluate(distance=999.0)
        self.clock.now = 22.0
        self.evaluate(distance=999.0)
        self.clock.now = 23.0
        recurring = self.evaluate(distance=30.0)

        self.assertEqual([event["rule_code"] for event in recurring], ["PATH_OBSTRUCTION"])

    def test_reagent_requires_persistent_detection(self):
        self.evaluate(classes=["reagent_bottle"])
        self.clock.now = 19.0
        self.assertEqual(self.evaluate(classes=["reagent_bottle"]), [])
        self.clock.now = 20.0
        events = self.evaluate(classes=["reagent_bottle"])
        self.clock.now = 25.0
        repeated = self.evaluate(classes=["reagent_bottle"])

        self.assertEqual([event["rule_code"] for event in events], ["CHEMICAL_UNATTENDED"])
        self.assertEqual(repeated, [])

    def test_normal_biohazard_bin_is_not_an_incident(self):
        events = self.evaluate(classes=["biohazard_bin"])
        self.assertEqual(events, [])
        self.assertEqual(self.engine.violations_detected, 0)

    def test_fire_event_is_a_review_request_not_a_confirmed_emergency(self):
        events = self.evaluate(zone="안전복도", classes=["fire_extinguisher"], distance=50.0)
        fire_event = next(event for event in events if event["rule_code"] == "FIRE_SAFETY_BLOCK")
        self.assertEqual(fire_event["severity"], "MEDIUM")

    def test_static_wall_is_not_reported_as_path_obstruction(self):
        events = self.evaluate(distance=20.0, obstacle_kind="static_wall")
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
