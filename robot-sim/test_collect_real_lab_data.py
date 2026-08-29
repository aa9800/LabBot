import unittest

from collect_real_lab_data import is_robot_stationary, validate_request


class CollectRealLabDataTests(unittest.TestCase):
    def test_person_collection_requires_consent(self):
        with self.assertRaisesRegex(ValueError, "명시적 동의"):
            validate_request("person-validation", 10, 1.0, True, False)

    def test_collection_rate_is_limited(self):
        with self.assertRaisesRegex(ValueError, "0.5초 이상"):
            validate_request("background-negative", 10, 0.1, True, False)

    def test_stationary_requires_manual_zero_command(self):
        self.assertTrue(is_robot_stationary({"mode": "manual", "speed": 0, "turn": 0}))
        self.assertFalse(is_robot_stationary({"mode": "auto", "speed": 0, "turn": 0}))
        self.assertFalse(is_robot_stationary({"mode": "manual", "speed": 0.2, "turn": 0}))


if __name__ == "__main__":
    unittest.main()
