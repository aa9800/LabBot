import tempfile
import unittest
from pathlib import Path

from mission_engine import ItemLocationCache, MissionEngine


class MissionEngineTests(unittest.TestCase):
    def make_engine(self):
        temp = tempfile.TemporaryDirectory()
        cache = ItemLocationCache(Path(temp.name) / "items.json")
        cache.replace([
            {"item_id": 1, "item_name": "피펫", "shelf_code": "LAB-A1", "location_detail": "1번째 줄"},
            {"item_id": 2, "item_name": "팁", "shelf_code": "LAB-A2", "location_detail": "2번째 줄"},
        ], revision="test")
        return temp, MissionEngine(cache)

    def test_only_item_id_is_resolved_locally(self):
        temp, engine = self.make_engine()
        self.addCleanup(temp.cleanup)
        result = engine.start(request_id="r1", item_id=1)
        self.assertEqual(result["item_name"], "피펫")
        self.assertEqual(result["status"], "awaiting_route_calibration")

    def test_next_item_starts_from_previous_shelf_without_home_trip(self):
        temp, engine = self.make_engine()
        self.addCleanup(temp.cleanup)
        engine.start(request_id="r1", item_id=1)
        engine.finish("completed")
        result = engine.start(request_id="r2", item_id=2)
        self.assertTrue(result["direct_from_previous"])
        self.assertEqual(result["departure_location"], "LAB-A1")

    def test_request_id_is_idempotent(self):
        temp, engine = self.make_engine()
        self.addCleanup(temp.cleanup)
        first = engine.start(request_id="same", item_id=1)
        second = engine.start(request_id="same", item_id=2)
        self.assertEqual(first["item_id"], second["item_id"])

    def test_verified_route_without_executor_fails_closed(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        cache = ItemLocationCache(Path(temp.name) / "items.json")
        cache.replace([{
            "item_id": 1,
            "item_name": "피펫",
            "physical_route": {
                "status": "verified",
                "controller": "line_checkpoint_v1",
                "segments": [{"checkpoint": "NAV-LAB-A1"}],
            },
        }])
        engine = MissionEngine(cache)
        result = engine.start(request_id="safe", item_id=1)
        self.assertEqual(result["status"], "awaiting_route_executor")
        self.assertFalse(result["route_executor_available"])
        self.assertFalse(engine.should_drive())

    def test_only_explicitly_supported_executor_can_navigate(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        cache = ItemLocationCache(Path(temp.name) / "items.json")
        cache.replace([{
            "item_id": 1,
            "item_name": "피펫",
            "physical_route": {
                "status": "verified",
                "controller": "line_checkpoint_v1",
                "segments": [{"checkpoint": "NAV-LAB-A1"}],
            },
        }])
        engine = MissionEngine(cache, supported_route_controllers={"line_checkpoint_v1"})
        result = engine.start(request_id="enabled", item_id=1)
        self.assertEqual(result["status"], "navigating")
        self.assertTrue(result["route_executor_available"])
        self.assertTrue(engine.should_drive())


if __name__ == "__main__":
    unittest.main()
