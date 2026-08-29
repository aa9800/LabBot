"""카메라 캡처를 스트리밍·QR·AI가 안전하게 공유하는 최신 프레임 브로커."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class FrameSnapshot:
    sequence: int
    timestamp: float
    frame: np.ndarray


class FrameBroker:
    """대기열을 쌓지 않고 가장 최근 BGR 프레임 하나만 보관한다."""

    def __init__(self):
        self._condition = threading.Condition()
        self._sequence = 0
        self._timestamp = 0.0
        self._frame: Optional[np.ndarray] = None

    def publish(self, frame: np.ndarray):
        if frame is None or frame.size == 0:
            return
        with self._condition:
            self._frame = frame
            self._sequence += 1
            self._timestamp = time.time()
            self._condition.notify_all()

    def latest(self, *, copy=True) -> Optional[FrameSnapshot]:
        with self._condition:
            if self._frame is None:
                return None
            frame = self._frame.copy() if copy else self._frame
            return FrameSnapshot(self._sequence, self._timestamp, frame)

    def wait_for_new(self, after_sequence: int, timeout=0.5, *, copy=True):
        with self._condition:
            if self._sequence <= after_sequence:
                self._condition.wait(timeout)
            if self._frame is None or self._sequence <= after_sequence:
                return None
            frame = self._frame.copy() if copy else self._frame
            return FrameSnapshot(self._sequence, self._timestamp, frame)
