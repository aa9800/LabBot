"""LabKeeper 웹의 /api/safety-events 로 이벤트를 보내는 아주 작은 헬퍼.

표준 라이브러리(urllib)만 쓴다 — robot-sim의 requirements.txt에 새 의존성을 추가하지 않기 위해서다.
웹 서버가 안 켜져 있어도 시뮬레이터가 죽지 않도록 예외를 삼킨다(연결 실패는 콘솔에만 출력).
"""
import json
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"
SAFETY_EVENTS_URL = f"{BASE_URL}/api/safety-events"
ITEMS_URL = f"{BASE_URL}/api/items"
AUDIT_SESSIONS_URL = f"{BASE_URL}/api/audit-sessions"


def _post_json(url: str, payload: dict, timeout: float = 3.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify] {url} 호출 실패 (웹 서버가 켜져 있나요?): {e}")
        return None


def report_safety_event(rule_id: str, severity: str = "MEDIUM", note: str = "", source: str = "robot-sim"):
    result = _post_json(SAFETY_EVENTS_URL, {"rule_id": rule_id, "severity": severity, "source": source, "note": note}, timeout=1.5)
    return result is not None


def fetch_items():
    """LabKeeper 웹에 실제로 등록된 물품 목록을 가져온다. 실패하면 빈 리스트를 돌려준다
    (그래도 시뮬레이터는 체크포인트 없이 계속 동작한다)."""
    try:
        with urllib.request.urlopen(ITEMS_URL, timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify] 물품 목록을 가져오지 못했습니다 (웹 서버가 켜져 있나요?): {e}")
        return []


def submit_audit_session(performed_by: str, checked_item_ids: list):
    """지금까지 순찰하며 스캔한 물품 id 목록을 실제 실사 세션으로 웹에 제출한다.
    반환값에 mismatch_count가 들어있어 몇 개가 안 보였는지 바로 알 수 있다."""
    return _post_json(AUDIT_SESSIONS_URL, {"performed_by": performed_by, "checked_item_ids": checked_item_ids})
