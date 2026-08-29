"""실물 Raspbot과 Isaac Sim이 함께 쓰는 저속 장애물 우회 상태기계.

전방 초음파 센서 하나만 있는 현재 하드웨어에서 가능한 가장 보수적인 방식이다.
로봇 몸체를 제자리 회전해 좌우 거리를 각각 재고, 더 넓은 쪽으로 S자 우회한 뒤
라인/원래 경로를 다시 찾는다. 사람으로 분류된 경우에는 가까이 지나가지 않고 기다린다.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Callable, Dict, List, Optional


STATE_LABELS = {
    "idle": "정상 주행",
    "pause": "장애물 확인",
    "wait_person": "사람 통과 대기",
    "scan_left_turn": "왼쪽 공간 확인",
    "scan_left_sample": "왼쪽 거리 측정",
    "scan_right_turn": "오른쪽 공간 확인",
    "scan_right_sample": "오른쪽 거리 측정",
    "choose_side": "우회 방향 결정",
    "orient_left": "왼쪽 우회 진입",
    "sidestep_out": "장애물 옆으로 이동",
    "align_forward": "진행 방향 정렬",
    "pass_forward": "장애물 통과",
    "turn_rejoin": "원래 경로 복귀",
    "seek_route": "라인 재탐색",
    "restore_heading": "주행 방향 복원",
    "blocked_center": "정면 복귀",
    "blocked_wait": "우회로 없음·대기",
}

# 약 65도 스캔. 현재 초음파의 시야각과 로봇 폭을 고려하면 45도만 돌았을 때는
# 30cm 앞 작은 물체도 좌우 양쪽에서 계속 잡혀 빈 공간을 구분하지 못한다.
SCAN_TURN_SECONDS = 0.80
SCAN_CROSS_SECONDS = SCAN_TURN_SECONDS * 2.0


class ObstacleAvoider:
    """고정 전방 초음파를 차체 회전 스캔처럼 사용하는 비차단 상태기계."""

    def __init__(
        self,
        hal: Any,
        on_obstacle: Optional[Callable[[float], None]] = None,
        on_cleared: Optional[Callable[[], None]] = None,
        stop_distance_cm: float = 40.0,
        clear_distance_cm: float = 55.0,
        max_scan_attempts: int = 3,
    ):
        self.hal = hal
        self.on_obstacle = on_obstacle
        self.on_cleared = on_cleared
        self.stop_distance_cm = stop_distance_cm
        self.clear_distance_cm = clear_distance_cm
        self.max_scan_attempts = max_scan_attempts

        self.state = "idle"
        self.state_elapsed = 0.0
        self.clear_elapsed = 0.0
        self.obstacle_kind = "unknown"
        self.chosen_side: Optional[str] = None
        self.left_distance_cm: Optional[float] = None
        self.right_distance_cm: Optional[float] = None
        self._samples: List[float] = []
        self._scan_attempt = 0
        self._last_tie_side = "right"
        self.last_result = "idle"

    @property
    def active(self) -> bool:
        return self.state != "idle"

    def status(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "state": self.state,
            "label": STATE_LABELS.get(self.state, self.state),
            "kind": self.obstacle_kind,
            "side": self.chosen_side,
            "left_cm": self.left_distance_cm,
            "right_cm": self.right_distance_cm,
            "attempt": self._scan_attempt,
            "last_result": self.last_result,
        }

    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_elapsed = 0.0
        self.clear_elapsed = 0.0
        self._samples = []

    def _classify_obstacle(self) -> str:
        classifier = getattr(self.hal, "classify_obstacle", None)
        if not callable(classifier):
            return "object"
        try:
            result = str(classifier() or "object").lower()
            if result in ("person", "static_wall", "static_fixture", "movable_object"):
                return result
            return "object"
        except Exception:
            return "object"

    def _begin(self, distance_cm: float) -> None:
        # 사람 분류는 카메라 연산이라 수십~수백 ms 걸릴 수 있다. 판별보다 모터 정지가
        # 반드시 먼저 실행되어야 그 시간 동안 장애물 쪽으로 계속 전진하지 않는다.
        self.hal.stop()
        self.obstacle_kind = self._classify_obstacle()
        self.chosen_side = None
        self.left_distance_cm = None
        self.right_distance_cm = None
        self._scan_attempt = 1
        self.last_result = "detected"
        self._set_state("wait_person" if self.obstacle_kind == "person" else "pause")
        if self.on_obstacle:
            self.on_obstacle(distance_cm)

    def _finish(self, result: str) -> None:
        self.hal.stop()
        self.last_result = result
        self.state = "idle"
        self.state_elapsed = 0.0
        self.clear_elapsed = 0.0
        if self.on_cleared:
            self.on_cleared()

    @staticmethod
    def _usable_distance(distance_cm: float) -> float:
        try:
            distance = float(distance_cm)
        except (TypeError, ValueError):
            return 999.0
        return distance if distance > 0.0 else 999.0

    def _sample(self, distance_cm: float) -> None:
        self._samples.append(self._usable_distance(distance_cm))

    def _sample_result(self) -> float:
        return float(median(self._samples)) if self._samples else 999.0

    def _turn(self, side: str, speed: float = 58.0) -> None:
        self.hal.set_motion(0.0, -speed if side == "left" else speed)

    def _forward_is_blocked(self, distance_cm: float) -> bool:
        return self._usable_distance(distance_cm) < 25.0

    def tick(self, dt: float, distance_cm: Optional[float] = None) -> bool:
        """한 제어 틱을 실행한다. True면 우회기가 그 틱의 모터 제어권을 사용했다."""
        distance = self._usable_distance(
            self.hal.read_ultrasonic() if distance_cm is None else distance_cm
        )

        if not self.active:
            if distance >= self.stop_distance_cm:
                return False
            self._begin(distance)
            return True

        self.state_elapsed += max(0.0, float(dt))

        if self.state == "wait_person":
            self.hal.stop()
            self.clear_elapsed = self.clear_elapsed + dt if distance >= self.clear_distance_cm else 0.0
            if self.clear_elapsed >= 2.0:
                self._finish("person_cleared")
            return True

        if self.state == "pause":
            self.hal.stop()
            if self.state_elapsed >= 0.30:
                self._set_state("scan_left_turn")
            return True

        if self.state == "scan_left_turn":
            self._turn("left")
            if self.state_elapsed >= SCAN_TURN_SECONDS:
                self._set_state("scan_left_sample")
            return True

        if self.state == "scan_left_sample":
            self.hal.stop()
            self._sample(distance)
            if self.state_elapsed >= 0.22:
                self.left_distance_cm = self._sample_result()
                self._set_state("scan_right_turn")
            return True

        if self.state == "scan_right_turn":
            self._turn("right")
            if self.state_elapsed >= SCAN_CROSS_SECONDS:
                self._set_state("scan_right_sample")
            return True

        if self.state == "scan_right_sample":
            self.hal.stop()
            self._sample(distance)
            if self.state_elapsed >= 0.22:
                self.right_distance_cm = self._sample_result()
                self._set_state("choose_side")
            return True

        if self.state == "choose_side":
            left = self.left_distance_cm or 0.0
            right = self.right_distance_cm or 0.0
            if max(left, right) < self.clear_distance_cm:
                self._set_state("blocked_center")
                return True

            if abs(left - right) < 8.0:
                self.chosen_side = "left" if self._last_tie_side == "right" else "right"
            else:
                self.chosen_side = "left" if left > right else "right"
            self._last_tie_side = self.chosen_side
            self._set_state("orient_left" if self.chosen_side == "left" else "sidestep_out")
            return True

        if self.state == "orient_left":
            # 현재 차체는 오른쪽 스캔 방향이므로 왼쪽 스캔 방향까지 되돌린다.
            self._turn("left")
            if self.state_elapsed >= SCAN_CROSS_SECONDS:
                self._set_state("sidestep_out")
            return True

        if self.state == "sidestep_out":
            if self._forward_is_blocked(distance):
                self._set_state("blocked_wait")
                self._scan_attempt = self.max_scan_attempts
                self.hal.stop()
                return True
            self.hal.set_motion(38.0, 0.0)
            # 로봇 반폭(약 8cm)과 실험실 카트/상자 반폭, 10cm 여유를 합쳐 약 38cm
            # 옆으로 벗어난다. 20cm만 이동하면 원래 방향으로 정렬했을 때 초음파 시야에
            # 장애물이 다시 들어와 우회를 중단하는 문제가 Isaac 실측에서 확인됐다.
            if self.state_elapsed >= 1.45:
                self._set_state("align_forward")
            return True

        if self.state == "align_forward":
            self._turn("right" if self.chosen_side == "left" else "left")
            if self.state_elapsed >= SCAN_TURN_SECONDS:
                self._set_state("pass_forward")
            return True

        if self.state == "pass_forward":
            if self._forward_is_blocked(distance):
                self._set_state("blocked_wait")
                self._scan_attempt = self.max_scan_attempts
                self.hal.stop()
                return True
            self.hal.set_motion(38.0, 0.0)
            if self.state_elapsed >= 1.05:
                self._set_state("turn_rejoin")
            return True

        if self.state == "turn_rejoin":
            self._turn("right" if self.chosen_side == "left" else "left")
            if self.state_elapsed >= SCAN_TURN_SECONDS:
                self._set_state("seek_route")
            return True

        if self.state == "seek_route":
            if self._forward_is_blocked(distance):
                self._set_state("blocked_wait")
                self._scan_attempt = self.max_scan_attempts
                self.hal.stop()
                return True
            self.hal.set_motion(30.0, 0.0)
            line_reader = getattr(self.hal, "read_line_sensors", None)
            line_found = callable(line_reader) and any(line_reader())
            if line_found or self.state_elapsed >= 1.10:
                self._set_state("restore_heading")
            return True

        if self.state == "restore_heading":
            self._turn("left" if self.chosen_side == "left" else "right")
            if self.state_elapsed >= SCAN_TURN_SECONDS:
                self._finish("avoided")
            return True

        if self.state == "blocked_center":
            # 좌우 스캔 뒤 오른쪽을 보고 있으므로 정면으로만 돌아온다.
            self._turn("left")
            if self.state_elapsed >= SCAN_TURN_SECONDS:
                self._set_state("blocked_wait")
            return True

        if self.state == "blocked_wait":
            self.hal.stop()
            self.clear_elapsed = self.clear_elapsed + dt if distance >= self.clear_distance_cm else 0.0
            if self.clear_elapsed >= 1.5:
                self._finish("obstacle_cleared")
                return True
            if self.state_elapsed >= 3.0 and self._scan_attempt < self.max_scan_attempts:
                self._scan_attempt += 1
                self._set_state("pause")
            return True

        self.hal.stop()
        return True
