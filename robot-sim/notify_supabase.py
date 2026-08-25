"""Webots(labkeeper_controller)가 실제 Supabase DB(web/과 같은 DB)에 붙는 헬퍼.

notify.py(기존, pygame용 — LabKeeper 로컬 FastAPI 서버를 본다)는 그대로 두고,
이 파일을 새로 만들었다. 이유: 지훈님이 만든 실제 웹은 이제 그 FastAPI가 아니라
Supabase를 직접 쓰기 때문에, Webots 쪽만 이 새 모듈로 갈아 끼운다.

표준 라이브러리(urllib)만 쓴다 — notify.py와 같은 이유(새 의존성 추가 안 함).

secret key를 쓰는 이유: 로그인 세션이 없는 이 스크립트는 RLS(Row Level Security)를
통과할 수 없다. secret key는 RLS를 우회하는 "서버 전용" 키다 — 그래서 robot-sim/.env
(git에 안 올라감)에만 두고, 이 파일도 절대 web/(브라우저 코드)에 두면 안 된다.
"""
import json
import os
import urllib.error
import urllib.request


def _load_env(path):
    """python-dotenv 없이 KEY=VALUE 줄만 읽는 아주 작은 파서."""
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
_env = _load_env(_ENV_PATH)

SUPABASE_URL = _env.get("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = _env.get("SUPABASE_SECRET_KEY", "")

_READY = bool(SUPABASE_URL and SUPABASE_SECRET_KEY)
if not _READY:
    print(
        "[notify_supabase] robot-sim/.env가 없거나 값이 비어 있습니다. "
        "robot-sim/.env.example을 복사해서 .env로 만들고 값을 채워주세요. "
        "(그전까지는 물품 위치를 못 읽어와서 체크포인트가 빈 목록으로 시작합니다)"
    )


def is_configured():
    """robot-sim/.env에 SUPABASE_URL/SUPABASE_SECRET_KEY가 채워져 있는지.
    호출하는 쪽(main.py 등)이 "체크포인트 0개"의 원인이 .env 미설정인지, 아니면
    서버는 설정됐는데 네트워크/DB 문제로 실패한 것인지 구분해서 안내할 때 쓴다."""
    return _READY


def _headers():
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def fetch_items():
    """items 테이블 전체를 가져온다. 실패하면 빈 리스트(체크포인트 없이도 계속 동작)."""
    if not _READY:
        return []
    url = f"{SUPABASE_URL}/rest/v1/items?select=*"
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify_supabase] 물품 목록을 가져오지 못했습니다: {e}")
        return []


def fetch_robot_command():
    """robot_commands(단일 행, id=1)을 읽어온다. 웹의 관리자가 'Robot Console'에서
    수동조작으로 바꾸면 여기 mode가 'manual'이 되고 speed/turn 값이 들어온다.
    실패하면 안전하게 '자동 순찰'로 취급한다."""
    if not _READY:
        return {"mode": "auto", "speed": 0.0, "turn": 0.0}
    url = f"{SUPABASE_URL}/rest/v1/robot_commands?id=eq.1&select=mode,speed,turn,updated_at"
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
            if rows:
                return rows[0]
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify_supabase] 원격조작 명령을 못 가져왔습니다(자동 순찰 유지): {e}")
    return {"mode": "auto", "speed": 0.0, "turn": 0.0}


def upload_camera_snapshot(image_path: str, bucket: str = "robot-camera", object_path: str = "latest.jpg"):
    """카메라 사진 한 장을 Supabase Storage에 업로드해서, 웹 Robot Console이
    그 URL을 계속 새로 불러와 '거의 실시간'처럼 보여줄 수 있게 한다.
    (실시간 영상 스트리밍이 아니라 주기적 스냅샷 — 발표 범위에서는 이 정도로 충분하다)"""
    if not _READY:
        return False
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{object_path}"
    try:
        with open(image_path, "rb") as f:
            data = f.read()
    except OSError as e:
        print(f"[notify_supabase] 카메라 사진 파일을 못 읽었습니다: {e}")
        return False

    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true",  # 같은 파일 이름에 매번 덮어쓰기
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()
            return True
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify_supabase] 카메라 사진 업로드 실패: {e}")
        return False


def report_safety_event(rule_id: str, severity: str = "MEDIUM", note: str = "", source: str = "webots-sim"):
    """safety_events 테이블에 새 이벤트를 하나 넣는다. 항상 NEEDS_REVIEW로 시작한다
    (DB 기본값) — 로봇이 자동으로 확정하지 않는다."""
    if not _READY:
        return False
    url = f"{SUPABASE_URL}/rest/v1/safety_events"
    payload = {"rule_id": rule_id, "severity": severity, "source": source, "note": note}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()
            return True
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify_supabase] 안전이벤트 전송 실패: {e}")
        return False
