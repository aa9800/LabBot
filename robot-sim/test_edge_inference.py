import sys
import time
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_inference import Detection, EdgeInferenceWorker


class FakeBackend:
    def __init__(self):
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return [Detection(10, "person", 0.9, [1, 2, 10, 20])]


class EdgeInferenceWorkerTests(unittest.TestCase):
    def test_worker_produces_latest_snapshot_without_queueing(self):
        backend = FakeBackend()
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        worker = EdgeInferenceWorker(lambda: frame, backend, target_fps=20)
        worker.start()
        time.sleep(0.18)
        worker.stop()

        latest = worker.latest()
        self.assertIsNotNone(latest)
        self.assertGreaterEqual(backend.calls, 2)
        self.assertEqual(latest.detections[0].class_name, "person")
        status = worker.status()
        self.assertFalse(status["running"])
        self.assertIsNone(status["error"])

    def test_worker_survives_missing_frames(self):
        backend = FakeBackend()
        worker = EdgeInferenceWorker(lambda: None, backend, target_fps=30)
        worker.start()
        time.sleep(0.08)
        worker.stop()
        self.assertEqual(backend.calls, 0)
        self.assertIsNone(worker.latest())


if __name__ == "__main__":
    unittest.main()
