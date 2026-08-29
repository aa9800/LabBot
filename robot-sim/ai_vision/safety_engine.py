"""LabBot 연구실 안전관리 및 시설/자산 모니터링 종합 엔진."""
import time
import sys
from pathlib import Path
from typing import List, Dict, Any, Callable, Set

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

class LabSafetyEngine:
    """연구실 안전 규정 및 시설 관리 실시간 판정 엔진."""

    def __init__(
        self,
        debounce_sec: float = 5.0,
        rearm_sec: float = 20.0,
        reagent_persistence_sec: float = 20.0,
        clock: Callable[[], float] = time.time,
    ):
        # last_alerts/debounce_sec는 기존 호출부와의 호환을 위해 유지한다. 실제 재알림은
        # 고정 주기 반복이 아니라, 위험이 사라졌다가 rearm_sec 뒤 다시 나타날 때만 발생한다.
        self.last_alerts: Dict[str, float] = {}
        self.debounce_sec = debounce_sec
        self.rearm_sec = max(rearm_sec, debounce_sec)
        self.reagent_persistence_sec = reagent_persistence_sec
        self._clock = clock
        self._first_seen: Dict[str, float] = {}
        self._last_seen: Dict[str, float] = {}
        self._active_conditions: Set[str] = set()
        self.total_scans = 0
        self.violations_detected = 0

    def _observe_condition(
        self,
        key: str,
        event: Dict[str, Any],
        now: float,
        observed: Set[str],
        events: List[Dict[str, Any]],
        persistence_sec: float = 0.0,
    ) -> None:
        """지속되는 동일 위험은 한 번만 알리고, 해소 후 재발할 때만 다시 알린다."""
        observed.add(key)
        last_seen = self._last_seen.get(key)

        # 마지막 관측 이후 충분히 오래 비어 있었다면 새로운 위험 발생으로 본다.
        if last_seen is None or now - last_seen >= self.rearm_sec:
            self._first_seen[key] = now
            self._active_conditions.discard(key)

        self._last_seen[key] = now
        self._first_seen.setdefault(key, now)

        if key in self._active_conditions:
            return
        if now - self._first_seen[key] < persistence_sec:
            return

        self._active_conditions.add(key)
        self.last_alerts[key] = now
        self.violations_detected += 1
        events.append(event)

    def _clear_resolved_conditions(self, observed: Set[str], now: float) -> None:
        """일정 시간 다시 보이지 않은 조건을 해제해 실제 재발만 새 이벤트로 만든다."""
        for key, last_seen in list(self._last_seen.items()):
            if key in observed or now - last_seen < self.rearm_sec:
                continue
            self._last_seen.pop(key, None)
            self._first_seen.pop(key, None)
            self._active_conditions.discard(key)

    def evaluate_frame_safety(
        self,
        current_zone: str,
        detections: List[Dict[str, Any]],
        obstacle_dist_cm: float = 999.0,
        obstacle_kind: str = "unknown",
    ) -> List[Dict[str, Any]]:
        """현재 구역과 AI 비전 탐지 결과를 바탕으로 안전 규정 위반 및 상태를 평가."""
        self.total_scans += 1
        now = self._clock()
        events: List[Dict[str, Any]] = []
        observed: Set[str] = set()

        detected_classes = {d["class_name"] for d in detections}
        fire_access_candidate = False

        # 1. 화재 안전: 소화기와 근거리 장애물이 같은 시점에 보인 경우의 검토 요청.
        # 단일 카메라+전방 초음파만으로 '소화기 바로 앞을 막았다'고 단정할 수는 없다.
        if "안전" in current_zone or "복도" in current_zone:
            if "fire_extinguisher" in detected_classes:
                # 소화기 앞 1m 이내에 장애물이 가로막고 있는 경우
                if obstacle_dist_cm < 90.0:
                    fire_access_candidate = True
                    ev_key = "FIRE_EXTINGUISHER_BLOCKED"
                    self._observe_condition(
                        ev_key,
                        {
                            "rule_code": "FIRE_SAFETY_BLOCK",
                            "severity": "MEDIUM",
                            "title": "🧯 [확인 필요] 소화기 접근구역 장애물 가능성",
                            "description": f"구역 [{current_zone}]에서 소화기와 {obstacle_dist_cm:.1f}cm 전방 장애물이 함께 감지되었습니다. 카메라 사진으로 실제 접근 방해 여부를 확인하세요.",
                            "location": current_zone,
                        },
                        now,
                        observed,
                        events,
                    )

        # 2. 화학/시약 안전: 용기 반복 관측. 현재 모델은 내용물·사용자·뚜껑 상태를
        # 식별하지 못하므로 '방치 확정'이 아니라 관리자 확인 대상으로만 기록한다.
        if current_zone in ("일반실험실", "기기실-1", "기기실-2"):
            if "reagent_bottle" in detected_classes or "flask" in detected_classes:
                ev_key = f"UNATTENDED_REAGENT_{current_zone}"
                self._observe_condition(
                    ev_key,
                    {
                        "rule_code": "CHEMICAL_UNATTENDED",
                        "severity": "MEDIUM",
                        "title": "🧪 [확인 필요] 시약 용기 반복 감지",
                        "description": f"구역 [{current_zone}]에서 시약병/플라스크가 {self.reagent_persistence_sec:.0f}초 이상 반복 감지되었습니다. 사용 중인지 사진으로 확인하고, 미사용 시 지정 보관 위치로 옮기세요.",
                        "location": current_zone,
                    },
                    now,
                    observed,
                    events,
                    persistence_sec=self.reagent_persistence_sec,
                )

        # 3. 비상 대피로 및 순찰 통로 차단 장애물 검사
        # 벽·유리 파티션·고정 가구는 경로 보정 대상이지 안전사고가 아니다. 이동 가능한
        # 물체나 종류를 확정하지 못한 장애물만 관리자 검토 이벤트로 남긴다.
        is_fixed_structure = str(obstacle_kind).startswith("static_")
        if obstacle_dist_cm < 45.0 and not is_fixed_structure and not fire_access_candidate:
            ev_key = f"PATHWAY_OBSTRUCTION_{current_zone}"
            self._observe_condition(
                ev_key,
                {
                    "rule_code": "PATH_OBSTRUCTION",
                    "severity": "MEDIUM",
                    "title": "🚧 [주행 주의] 이동 장애물 감지",
                    "description": f"구역 [{current_zone}] 로봇 진행 방향 {obstacle_dist_cm:.1f}cm에서 이동 가능 물체가 감지되어 정지·우회를 시작했습니다. 사진으로 통로 정리 필요 여부를 확인하세요.",
                    "location": current_zone,
                },
                now,
                observed,
                events,
            )

        # 생물학적 폐기물통이 제자리에 있는 것은 정상 상태다. 정상 확인을 안전사고
        # 목록에 넣으면 실제 위험이 묻히므로 이벤트를 만들지 않는다.
        self._clear_resolved_conditions(observed, now)

        return events
