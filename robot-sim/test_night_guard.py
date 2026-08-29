import datetime as dt
import unittest

from night_guard import NightGuardScheduler


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class NightGuardSchedulerTest(unittest.TestCase):
    def make_guard(self):
        clock = FakeClock()
        guard = NightGuardScheduler(
            enabled=True,
            start_hour=22,
            end_hour=8,
            patrol_interval_s=60,
            patrol_duration_s=10,
            investigation_duration_s=8,
            trigger_hold_s=0.8,
            sonar_delta_cm=30,
            sonar_near_cm=180,
            monotonic=clock,
        )
        return guard, clock

    def test_daytime_does_not_stop_existing_robot_work(self):
        guard, _ = self.make_guard()
        result = guard.update(now=dt.datetime(2026, 8, 28, 14, 0), sonar_cm=999)
        self.assertEqual(result["state"], "daytime")
        self.assertTrue(result["should_move"])
        self.assertFalse(result["active"])

    def test_night_starts_with_short_patrol_then_sensor_standby(self):
        guard, clock = self.make_guard()
        first = guard.update(now=dt.datetime(2026, 8, 28, 22, 0), sonar_cm=300)
        self.assertEqual(first["state"], "scheduled_patrol")
        self.assertTrue(first["should_move"])

        clock.advance(11)
        standby = guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 11), sonar_cm=300)
        self.assertEqual(standby["state"], "standby")
        self.assertFalse(standby["should_move"])

    def test_single_sonar_spike_is_rejected_but_persistent_change_dispatches(self):
        guard, clock = self.make_guard()
        guard.update(now=dt.datetime(2026, 8, 28, 22), sonar_cm=300)
        clock.advance(11)
        guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 11), sonar_cm=300)

        spike = guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 12), sonar_cm=120)
        self.assertEqual(spike["state"], "verifying")
        clock.advance(0.4)
        cleared = guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 12), sonar_cm=300)
        self.assertEqual(cleared["state"], "standby")

        clock.advance(0.1)
        guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 13), sonar_cm=120)
        clock.advance(0.9)
        dispatched = guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 14), sonar_cm=120)
        self.assertEqual(dispatched["state"], "investigating")
        self.assertTrue(dispatched["should_move"])

    def test_confirmed_person_or_external_camera_signal_dispatches_immediately(self):
        guard, clock = self.make_guard()
        guard.update(now=dt.datetime(2026, 8, 28, 22), sonar_cm=300)
        clock.advance(11)
        guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 11), sonar_cm=300)
        guard.trigger("ai-camera", person=True)
        result = guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 12), sonar_cm=300)
        self.assertEqual(result["state"], "investigating")
        self.assertIn("사람", result["reason"])

    def test_investigation_returns_to_standby_and_interval_restarts_patrol(self):
        guard, clock = self.make_guard()
        guard.update(now=dt.datetime(2026, 8, 28, 22), sonar_cm=300)
        clock.advance(11)
        guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 11), sonar_cm=300)
        guard.trigger("camera")
        guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 12), sonar_cm=300)
        clock.advance(9)
        standby = guard.update(now=dt.datetime(2026, 8, 28, 22, 0, 21), sonar_cm=300)
        self.assertEqual(standby["state"], "standby")

        clock.advance(40)
        patrol = guard.update(now=dt.datetime(2026, 8, 28, 22, 1, 1), sonar_cm=300)
        self.assertEqual(patrol["state"], "scheduled_patrol")


if __name__ == "__main__":
    unittest.main()
