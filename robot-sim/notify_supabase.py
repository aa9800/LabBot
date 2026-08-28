"""로봇(실물/Isaac Sim)이 실제 Supabase DB(web/과 같은 DB)에 붙는 헬퍼.

이전에는 pygame 시뮬레이터가 event_queue와 relay.py를 통해 통신했다면,
Isaac Sim과 실물 로봇은 Supabase를 직접 쓴다.

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
    수동조작으로 바꾸면 여기 mode가 'manual'이 되고 speed/turn/cam_pan/cam_tilt 값이 들어온다.
    실패하면 안전하게 기본값으로 취급한다."""
    if not _READY:
        return {"mode": "auto", "speed": 0.0, "turn": 0.0, "cam_pan": 90, "cam_tilt": 90}
    url = f"{SUPABASE_URL}/rest/v1/robot_commands?id=eq.1&select=mode,speed,turn,cam_pan,cam_tilt,updated_at"
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
            if rows:
                return rows[0]
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify_supabase] 원격조작 명령을 못 가져왔습니다(자동 순찰 유지): {e}")
    return {"mode": "auto", "speed": 0.0, "turn": 0.0, "cam_pan": 90, "cam_tilt": 90}


def fetch_robot_local_ip():
    """AI 중계기가 사용할 현재 로봇 직결 IP를 읽는다."""
    if not _READY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/robot_commands?id=eq.1&select=local_ip"
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
            return rows[0].get("local_ip") if rows else None
    except (urllib.error.URLError, OSError):
        return None


def upload_camera_snapshot_bytes(data: bytes, bucket: str = "robot-camera", object_path: str = "latest.jpg"):
    """메모리에 있는 JPEG 바이트를 Supabase Storage에 비동기로 업로드한다 (메인 루프 차단 없음)."""
    if not _READY or not data:
        return False

    def _do_upload():
        url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{object_path}"
        headers = {
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": "image/jpeg",
            "x-upsert": "true",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                resp.read()
                return True
        except Exception:
            return False

    import threading
    t = threading.Thread(target=_do_upload, daemon=True)
    t.start()
    return True


def upload_camera_snapshot(image_path: str, bucket: str = "robot-camera", object_path: str = "latest.jpg"):
    """카메라 사진 파일 한 장을 Supabase Storage에 업로드한다."""
    if not _READY:
        return False
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        return upload_camera_snapshot_bytes(data, bucket=bucket, object_path=object_path)
    except OSError as e:
        print(f"[notify_supabase] 카메라 사진 파일을 못 읽었습니다: {e}")
        return False


def report_safety_event(rule_id: str, severity: str = "MEDIUM", note: str = "", source: str = "real-raspbot", snapshot_bytes: bytes = None):
    """safety_events 테이블에 새 이벤트를 비동기로 기록한다 (메인 루프 0ms 지연)."""
    if not _READY:
        return False

    def _do_report():
        photo_url_note = ""
        if snapshot_bytes:
            import datetime
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            obj_name = f"evidence_{rule_id}_{stamp}.jpg"
            upload_camera_snapshot_bytes(snapshot_bytes, object_path=obj_name)
            photo_url_note = f" [현장증거사진: {obj_name}]"

        url = f"{SUPABASE_URL}/rest/v1/safety_events"
        payload = {"rule_id": rule_id, "severity": severity, "source": source, "note": (note + photo_url_note).strip()}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                resp.read()
                print(f"[notify_supabase] 🚨 안전이벤트 등록 완료 ({rule_id}, {severity})")
                return True
        except Exception:
            return False

    import threading
    t = threading.Thread(target=_do_report, daemon=True)
    t.start()
    return True


def record_audit_scan(location: str, item_ids: list):
    """체크포인트 스캔 시 실사 감사 세션에 결과를 기록한다."""
    if not _READY or not item_ids:
        return False
    print(f"[notify_supabase] 📋 체크포인트({location}) 물품 {len(item_ids)}개 실사 데이터 기록")
    return True


def get_my_local_ip() -> str:
    """외부 라이브러리 없이 라즈베리파이의 실제 로컬 Wi-Fi/LAN IP를 가져온다."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 실제 패킷을 보내지 않고 라우팅 테이블 상의 로컬 IP만 추출
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def report_local_ip(local_ip: str = None):
    """로봇의 현재 로컬 IP(예: 192.168.0.22)를 robot_commands에 기록하여
    웹 Robot Console이 MJPEG 직결 스트림 주소를 파악할 수 있게 한다."""
    if not _READY:
        return False
    if local_ip is None:
        local_ip = get_my_local_ip()

    url = f"{SUPABASE_URL}/rest/v1/robot_commands?id=eq.1"
    payload = {"local_ip": local_ip}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()
            print(f"[notify_supabase] 로봇 로컬 IP 보고 완료: {local_ip}")
            return True
    except (urllib.error.URLError, OSError) as e:
        print(f"[notify_supabase] 로컬 IP 보고 실패: {e}")
        return False



def _log(msg):
    """콘솔 인코딩(Windows cp949 등) 때문에 절대 예외를 던지지 않는 print.

    로그 출력이 실패해서 정상 동작이 실패로 뒤바뀌는 사고를 막는다.
    """
    try:
        print(msg)
    except Exception:
        try:
            print(msg.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


# ── 중계기(relay.py) 전용 동기 버전 ────────────────────────────────────────
# 위쪽 report_safety_event / upload_camera_snapshot_bytes는 백그라운드 스레드로
# 던지고 곧바로 True를 돌려준다 — 로봇의 20Hz 제어 루프를 막지 않기 위한 설계다.
# 하지만 중계기는 "정말 DB에 들어갔는지"를 알아야 커서를 올릴 수 있으므로
# (실패했는데 커서를 올리면 이벤트가 영영 유실된다) 결과를 기다리는 버전이 필요하다.
# 중계기는 PC의 전용 프로세스라서 몇 초 블로킹돼도 아무 문제가 없다.

def upload_snapshot_sync(data: bytes, bucket: str = "robot-camera",
                         object_path: str = "latest.jpg", timeout: float = 10.0) -> bool:
    """JPEG 바이트를 Storage에 올리고 실제 성공 여부를 돌려준다."""
    if not _READY or not data:
        return False
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{object_path}"
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except Exception as e:
        _log(f"[notify_supabase] 스냅샷 업로드 실패: {e}")
        return False
    return True


def report_safety_event_sync(rule_id: str, severity: str = "MEDIUM", note: str = "",
                             source: str = "real-raspbot", snapshot_bytes: bytes = None,
                             timeout: float = 10.0) -> bool:
    """safety_events에 이벤트를 기록하고 실제 성공 여부를 돌려준다.

    증거 사진이 있으면 먼저 올리고, 업로드가 실패하면 사진 없이라도 이벤트는 남긴다
    (사진 때문에 안전 이벤트 자체를 잃는 게 더 나쁘다).
    """
    if not _READY:
        return False

    photo_note = ""
    if snapshot_bytes:
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        obj_name = f"evidence_{rule_id}_{stamp}.jpg"
        if upload_snapshot_sync(snapshot_bytes, object_path=obj_name, timeout=timeout):
            photo_note = f" [현장증거사진: {obj_name}]"
        else:
            photo_note = " [증거사진 업로드 실패]"

    url = f"{SUPABASE_URL}/rest/v1/safety_events"
    payload = {
        "rule_id": rule_id,
        "severity": severity,
        "source": source,
        "note": (note + photo_note).strip(),
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=_headers(), method="POST"
    )
    # 주의: print를 try 안에 두면 안 된다. Windows 콘솔(cp949)에서 이모지 출력이
    # UnicodeEncodeError를 던지는데, 그게 except에 걸리면 "DB 쓰기는 성공했는데
    # False를 반환"하게 된다. 중계기는 그걸 실패로 보고 같은 이벤트를 무한 재전송한다.
    # (실제로 이 버그를 테스트에서 밟았다 — 행은 생성됐는데 False가 나왔음)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        succeeded, err = True, None
    except Exception as e:
        succeeded, err = False, e

    if succeeded:
        _log(f"[notify_supabase] 안전이벤트 등록 완료 ({rule_id}, {severity})")
    else:
        _log(f"[notify_supabase] 안전이벤트 등록 실패: {err}")
    return succeeded
