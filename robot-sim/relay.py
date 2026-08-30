"""로봇 ↔ Supabase 중계기 — PC에서 상주 실행한다.

왜 PC에서 도는가
----------------
로봇은 자기 자신이 만든 핫스팟(`Raspbot`)의 AP라서 상위 인터넷이 없다. 로봇에서
Supabase를 직접 부르면 전부 타임아웃이다(실측). 그렇다고 로봇을 인터넷 되는 공유기
(`iptime`)에 붙이면, 이번엔 PC가 로봇 핫스팟을 떠나야 해서 카메라 스트림과 조종이 죽는다.

PC만 양쪽을 동시에 본다:
  - 랜선(이더넷)  -> 인터넷 -> Supabase
  - Wi-Fi        -> Raspbot 핫스팟 -> 로봇 10.42.0.1

그래서 이 스크립트가 로봇의 `/events`를 주기적으로 긁어서 Supabase에 대신 쓴다.
관리자 웹페이지를 열어두지 않아도 돌기 때문에 무인 순찰에도 알림이 쌓인다.

실행
----
    python relay.py                 # 기본 10.42.0.1
    python relay.py 192.168.0.22    # 로봇이 다른 망에 있을 때

중복 방지
--------
마지막으로 처리한 seq를 `relay_cursor.json`에 저장한다. 중계기가 죽었다 살아나도
이미 쓴 이벤트를 다시 쓰지 않는다. 반대로 DB 쓰기 도중에 죽으면 그 이벤트는 커서가
안 올라가서 다음 번에 다시 시도된다(유실보다 중복 재시도가 낫다).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Windows 콘솔 기본 코드페이지(cp949)는 이모지·일부 한글 기호를 못 찍는다.
# 로그 출력이 예외를 던지면 정상 동작이 실패로 뒤바뀔 수 있어서 UTF-8로 고정한다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from notify_supabase import (
    fetch_item_locations,
    fetch_items,
    record_audit_scan,
    report_local_ip,
    report_safety_event_sync,   # 비동기판은 성공 여부와 무관하게 True라 커서 판단에 쓸 수 없다
    upload_snapshot_sync,
)

# 2026-08-30 구조 변경: 로봇이 공유기(iptime)에 붙어 인터넷을 직접 쓰게 되면서
# 이 중계기는 더 이상 필수가 아니다. 로봇이 Supabase 에 직접 쓴다.
# 그래도 남겨두는 이유: 로봇이 공유기 범위를 벗어나거나 공유기가 죽으면 로봇은
# 이벤트를 디스크 큐에 쌓아둔다. 그때 PC 가 로봇에 닿을 수 있는 상황이라면
# 이 중계기로 밀린 것을 대신 올릴 수 있다.
ROBOT_HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.22"
ROBOT_PORT = 8080
BASE = f"http://{ROBOT_HOST}:{ROBOT_PORT}"

POLL_SECONDS = 2.0          # 이벤트 큐 확인 주기
SNAPSHOT_EVERY_SECONDS = 30.0  # 주기 카메라 스냅샷 업로드 주기
ITEMS_REFRESH_SECONDS = 300.0  # 물품 목록 갱신 주기(체크포인트 -> 물품 매칭용)
HTTP_TIMEOUT = 4.0
MAX_RETRIES = 3   # 이만큼 연속 실패하면 그 이벤트는 건너뛴다(큐 전체가 막히는 걸 방지)

_skipped_summary = []   # 종료 시 요약을 찍기 위한 모듈 레벨 참조

_DIR = os.path.dirname(os.path.abspath(__file__))
CURSOR_PATH = os.path.join(_DIR, "relay_cursor.json")


def _get(path, timeout=HTTP_TIMEOUT):
    """로봇에서 바이트를 가져온다. 못 붙으면 None (로봇이 꺼져 있을 수 있음)."""
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError):
        return None


def _post_json(path, payload, timeout=HTTP_TIMEOUT):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def load_cursor():
    try:
        with open(CURSOR_PATH, "r", encoding="utf-8") as f:
            return int(json.load(f).get("last_seq", 0))
    except (OSError, ValueError, KeyError):
        return 0


def save_cursor(seq):
    tmp = CURSOR_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"last_seq": seq, "updated_at": time.time()}, f)
    os.replace(tmp, CURSOR_PATH)  # 원자적 교체 — 쓰다가 죽어도 커서 파일이 깨지지 않는다


def handle_event(ev, items_by_location):
    """이벤트 하나를 Supabase에 기록한다. 성공하면 True.

    False를 돌려주면 커서를 안 올리므로 다음 폴링에서 다시 시도된다.
    """
    kind = ev.get("kind")
    p = ev.get("payload") or {}
    seq = ev.get("seq")

    if kind == "safety_event":
        snap = _get(f"/events/snapshot?seq={seq}") if ev.get("has_snapshot") else None
        ok = report_safety_event_sync(
            p.get("rule_id", "SR-00"),
            severity=p.get("severity", "MEDIUM"),
            note=p.get("note", ""),
            source=p.get("source", "real-raspbot"),
            snapshot_bytes=snap,
        )
        print(f"  [{seq}] 🚨 {p.get('rule_id')} {p.get('note','')[:40]} -> {'OK' if ok else '실패'}")
        return bool(ok)

    if kind == "audit_scan":
        # ⚠️ notify_supabase.record_audit_scan은 현재 print만 하는 껍데기다 — DB에
        # 아무것도 안 쓴다. audit_sessions 스키마상 "어느 실사 세션에 속하는 스캔인지"를
        # 정해야 하는데 그 설계가 아직 없어서, 여기서는 로그만 남기고 넘어간다.
        # (설계가 정해지면 이 분기만 채우면 된다 — 큐/커서 구조는 그대로 쓸 수 있다.)
        location = p.get("location")
        item_ids = [it["id"] for it in items_by_location.get(location, [])]
        record_audit_scan(location, item_ids)
        print(f"  [{seq}] 📸 체크포인트 {location} (물품 {len(item_ids)}개) — DB 미기록(실사 세션 설계 필요)")
        return True

    if kind == "local_ip":
        # 로봇이 스스로 보고한 IP는 못 믿는다 — get_my_local_ip()는 8.8.8.8로 라우팅을
        # 떠보는 방식인데, 인터넷 없는 로봇에서는 실패해서 127.0.0.1이 나온다.
        # 중계기는 실제로 접속에 성공한 주소(ROBOT_HOST)를 알고 있으니 그걸 쓴다.
        reported = p.get("local_ip")
        ip = ROBOT_HOST if (not reported or reported.startswith("127.")) else reported
        ok = report_local_ip(ip)
        suffix = f" (로봇 보고값 {reported}는 무시)" if ip != reported else ""
        print(f"  [{seq}] 🌐 로봇 IP {ip} -> {'OK' if ok else '실패'}{suffix}")
        return bool(ok)

    print(f"  [{seq}] ⚠️  모르는 이벤트 종류 '{kind}' — 건너뜀")
    return True  # 모르는 종류에 막혀서 큐 전체가 멈추면 안 되므로 넘긴다


def main():
    print(f"[relay] 로봇 {BASE} ↔ Supabase 중계 시작")
    cursor = load_cursor()
    print(f"[relay] 마지막 처리 seq = {cursor}")

    items_by_location = {}
    last_items_refresh = 0.0
    last_snapshot_at = 0.0
    robot_was_up = None
    failures = {}   # seq -> 연속 실패 횟수
    skipped = _skipped_summary   # 재시도 상한을 넘겨 건너뛴 이벤트(종료 시 요약 출력)

    while True:
        now = time.time()

        # 1) 물품 목록 주기 갱신 — 체크포인트를 물품에 매핑하는 데 쓴다
        if now - last_items_refresh > ITEMS_REFRESH_SECONDS:
            items = fetch_items()
            if items:
                items_by_location = {}
                for it in items:
                    items_by_location.setdefault(it.get("location"), []).append(it)
                print(f"[relay] 물품 {len(items)}개 갱신")
            item_locations = fetch_item_locations()
            if item_locations:
                cache_result = _post_json(
                    "/config/item-locations",
                    {
                        "revision": f"supabase-{int(now)}",
                        "items": item_locations,
                    },
                )
                if cache_result:
                    print(
                        f"[relay] 로봇 로컬 물품 위치 캐시 "
                        f"{cache_result.get('item_count', len(item_locations))}건 동기화"
                    )
                else:
                    print("[relay] ⚠️ 로봇 물품 위치 캐시 동기화 실패 — 다음 주기에 재시도")
            last_items_refresh = now

        # 2) 이벤트 큐 비우기
        raw = _get(f"/events?after={cursor}&limit=50")
        if raw is None:
            if robot_was_up is not False:
                print(f"[relay] ⚠️  로봇에 연결 안 됨 ({BASE}) — 계속 재시도합니다")
                robot_was_up = False
            time.sleep(POLL_SECONDS)
            continue
        if robot_was_up is False:
            print("[relay] ✅ 로봇 재연결됨")
        robot_was_up = True

        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            print("[relay] ⚠️  /events 응답을 해석 못했습니다")
            time.sleep(POLL_SECONDS)
            continue

        events = body.get("events", [])
        if events:
            print(f"[relay] 이벤트 {len(events)}건 수신 (대기 {body.get('pending')})")
        for ev in events:
            seq = ev["seq"]
            if handle_event(ev, items_by_location):
                cursor = seq
                save_cursor(cursor)
                failures.pop(seq, None)
            else:
                # 일시적 실패(네트워크 등)는 재시도한다. 하지만 컬럼 누락처럼 영구
                # 실패하는 이벤트가 있으면 큐 전체가 여기서 영원히 막히므로,
                # MAX_RETRIES를 넘으면 크게 로그를 남기고 건너뛴다.
                failures[seq] = failures.get(seq, 0) + 1
                if failures[seq] >= MAX_RETRIES:
                    print(f"  [{seq}] ⛔ {MAX_RETRIES}회 실패 — 건너뜁니다 "
                          f"(kind={ev.get('kind')}). 원인을 고친 뒤 재시도가 필요합니다.")
                    skipped.append({"seq": seq, "kind": ev.get("kind"), "payload": ev.get("payload")})
                    cursor = seq
                    save_cursor(cursor)
                    failures.pop(seq, None)
                    continue
                print(f"  [{seq}] ↩️  실패 {failures[seq]}/{MAX_RETRIES} — 다음 폴링에서 재시도")
                break

        # 3) 주기 카메라 스냅샷 (큐를 거치지 않고 항상 최신 한 장만)
        if now - last_snapshot_at > SNAPSHOT_EVERY_SECONDS:
            jpeg = _get("/snapshot")
            if jpeg:
                upload_snapshot_sync(jpeg)
            last_snapshot_at = now

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[relay] 종료합니다")
    finally:
        if _skipped_summary:
            print(f"[relay] ⚠️  DB에 못 쓰고 건너뛴 이벤트 {len(_skipped_summary)}건:")
            for s in _skipped_summary[-10:]:
                print(f"    seq={s['seq']} kind={s['kind']} payload={s['payload']}")
