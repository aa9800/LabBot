import unittest

from health_monitor import parse_temperature, summarize


class HealthMonitorTests(unittest.TestCase):
    def test_temperature_parser(self):
        self.assertEqual(parse_temperature("temp=72.4'C"), 72.4)
        self.assertIsNone(parse_temperature(None))

    def test_summary_detects_restart(self):
        base = {
            "camera": {"fps": 30},
            "ai": {"actual_fps": 10},
            "temperature_c": 70,
            "rss_kib": 100,
            "service_active": "active",
            "throttled": "throttled=0x0",
            "errors": [],
        }
        records = [
            {**base, "monotonic": 0, "service_restarts": 0},
            {**base, "monotonic": 30, "service_restarts": 1},
        ]
        result = summarize(records, min_ai_fps=9)
        self.assertEqual(result["service_restart_delta"], 1)
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
