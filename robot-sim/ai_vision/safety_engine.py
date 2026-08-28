"""LabKeeper 연구실 안전관리 및 시설/자산 모니터링 종합 엔진."""
import time
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

class LabSafetyEngine:
    """연구실 안전 규정 및 시설 관리 실시간 판정 엔진."""

    def __init__(self, debounce_sec: float = 5.0):
        self.last_alerts: Dict[str, float] = {}
        self.debounce_sec = debounce_sec
        self.total_scans = 0
        self.violations_detected = 0

    def evaluate_frame_safety(
        self,
        current_zone: str,
        detections: List[Dict[str, Any]],
        obstacle_dist_cm: float = 999.0,
    ) -> List[Dict[str, Any]]:
        """현재 구역과 AI 비전 탐지 결과를 바탕으로 안전 규정 위반 및 상태를 평가."""
        self.total_scans += 1
        now = time.time()
        events = []

        detected_classes = [d["class_name"] for d in detections]

        # 1. 화재 안전: 소화기 비치 및 장애물 차단 검사
        if "안전" in current_zone or "복도" in current_zone:
            if "fire_extinguisher" in detected_classes:
                # 소화기 앞 1m 이내에 장애물이 가로막고 있는 경우
                if obstacle_dist_cm < 90.0:
                    ev_key = "FIRE_EXTINGUISHER_BLOCKED"
                    if now - self.last_alerts.get(ev_key, 0) > self.debounce_sec:
                        self.last_alerts[ev_key] = now
                        self.violations_detected += 1
                        ev = {
                            "rule_code": "FIRE_SAFETY_BLOCK",
                            "severity": "CRITICAL",
                            "title": "🚨 [화재안전] 소화기 전방 장애물 차단 감지",
                            "description": f"구역 [{current_zone}]의 소화기 전방 {obstacle_dist_cm:.1f}cm 거리에 무단 적치물이 감지되었습니다. 즉시 이동 조치가 필요합니다.",
                            "location": current_zone,
                        }
                        events.append(ev)

        # 2. 화학/시약 안전: 일반실험실 내 인화성/화학 시약병 방치 검사
        if current_zone in ("일반실험실", "기기실-1", "기기실-2"):
            if "reagent_bottle" in detected_classes or "flask" in detected_classes:
                ev_key = f"UNATTENDED_REAGENT_{current_zone}"
                if now - self.last_alerts.get(ev_key, 0) > self.debounce_sec:
                    self.last_alerts[ev_key] = now
                    self.violations_detected += 1
                    ev = {
                        "rule_code": "CHEMICAL_UNATTENDED",
                        "severity": "HIGH",
                        "title": "⚠️ [시약안전] 지정 보관함 외 화학 시약 방치",
                        "description": f"구역 [{current_zone}] 실험대 위에 화학 시약/플라스크가 보관함 외부에 방치되어 있습니다. 시약보관실 또는 안전 캐비닛으로 반납하세요.",
                        "location": current_zone,
                    }
                    events.append(ev)

        # 3. 비상 대피로 및 순찰 통로 차단 장애물 검사
        if obstacle_dist_cm < 45.0:
            ev_key = f"PATHWAY_OBSTRUCTION_{current_zone}"
            if now - self.last_alerts.get(ev_key, 0) > self.debounce_sec:
                self.last_alerts[ev_key] = now
                self.violations_detected += 1
                ev = {
                    "rule_code": "PATH_OBSTRUCTION",
                    "severity": "MEDIUM",
                    "title": "🚧 [통로안전] 순찰로 및 비상대피로 장애물 감지",
                    "description": f"구역 [{current_zone}] 자율주행 순찰 트랙에 장애물이 감지되어 로봇이 비상 정지했습니다. (거리: {obstacle_dist_cm:.1f}cm)",
                    "location": current_zone,
                }
                events.append(ev)

        # 4. 생물학적 유해 폐기물통 점검
        if "biohazard_bin" in detected_classes:
            ev_key = f"BIOHAZARD_VERIFIED_{current_zone}"
            if now - self.last_alerts.get(ev_key, 0) > self.debounce_sec * 2:
                self.last_alerts[ev_key] = now
                ev = {
                    "rule_code": "BIOHAZARD_CHECK",
                    "severity": "LOW",
                    "title": "✅ [시설점검] 생물학적 유해폐기물통 정상 비치 확인",
                    "description": f"구역 [{current_zone}]에서 생물 유해폐기물 수거함 위치를 정상 확인했습니다.",
                    "location": current_zone,
                }
                events.append(ev)

        return events
