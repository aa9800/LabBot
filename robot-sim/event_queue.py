"""로봇이 만든 이벤트를 로컬 메모리에 쌓아두는 큐 — 인터넷 없는 로봇용.

왜 필요한가
-----------
로봇은 자기 자신이 만든 핫스팟(`Raspbot`)에 붙어 있어서 상위 인터넷이 없다.
그래서 로봇에서 Supabase를 직접 부르면 전부 타임아웃으로 실패한다(실측 확인함).
반대로 PC는 랜선으로 인터넷이 항상 되고, 동시에 Wi-Fi로 로봇 핫스팟에 붙어 있다 —
즉 PC가 양쪽을 다 볼 수 있는 유일한 지점이다.

그래서 역할을 이렇게 나눈다:
  로봇  : 이벤트를 이 큐에 쌓기만 한다 (네트워크 시도 자체를 안 함)
  PC    : relay.py가 /events를 주기적으로 긁어가서 Supabase에 대신 쓴다

커서 방식(ack 없음)
-------------------
이벤트마다 1씩 증가하는 `seq`를 붙이고, 중계기는 `/events?after=<마지막seq>`로 가져간다.
중계기가 DB 쓰기 도중에 죽어도 커서를 안 올렸으면 다음 번에 같은 이벤트를 다시 받는다
(ack 왕복이 없어서 단순하고, 유실보다 중복이 낫다 — 중복은 relay.py 쪽에서 걸러낸다).

용량 제한
---------
메모리만 쓰므로 상한을 둔다. 중계기가 오래 꺼져 있으면 오래된 것부터 밀려나지만,
`run_logger.py`가 같은 내용을 JSONL로 디스크에 남기고 있어서 원본은 보존된다.
"""
import threading
import time
from collections import deque

MAX_EVENTS = 500        # 약 20초 쿨다운 기준이면 며칠치 안전 이벤트가 들어간다
MAX_SNAPSHOTS = 20      # 증거 사진은 용량이 커서 최근 것만 들고 있는다 (약 5~10MB)

_lock = threading.Lock()
_events = deque(maxlen=MAX_EVENTS)
_snapshots = {}                    # seq -> JPEG bytes
_snapshot_order = deque(maxlen=MAX_SNAPSHOTS)
_next_seq = 1


def push(kind, payload=None, snapshot_bytes=None):
    """이벤트를 큐에 넣고 부여된 seq를 돌려준다. 네트워크를 절대 건드리지 않는다.

    kind: "safety_event" | "audit_scan" | "camera_snapshot" | "local_ip"
    payload: JSON 직렬화 가능한 dict
    snapshot_bytes: 증거 사진(JPEG). 있으면 seq에 묶어서 따로 보관한다.
    """
    global _next_seq
    with _lock:
        seq = _next_seq
        _next_seq += 1
        _events.append({
            "seq": seq,
            "kind": kind,
            "ts": time.time(),
            "payload": payload or {},
            "has_snapshot": snapshot_bytes is not None,
        })
        if snapshot_bytes is not None:
            # maxlen에 걸려 밀려나는 seq의 사진은 같이 지워서 메모리 누수를 막는다
            if len(_snapshot_order) == _snapshot_order.maxlen:
                _snapshots.pop(_snapshot_order[0], None)
            _snapshot_order.append(seq)
            _snapshots[seq] = snapshot_bytes
        return seq


def drain_after(after_seq=0, limit=100):
    """`after_seq`보다 큰 이벤트를 오래된 순으로 돌려준다 (큐에서 지우지 않음)."""
    with _lock:
        out = [e for e in _events if e["seq"] > after_seq]
        return out[:limit]


def get_snapshot(seq):
    """해당 seq에 묶인 증거 사진(JPEG bytes). 없으면 None."""
    with _lock:
        return _snapshots.get(seq)


def stats():
    """중계기가 상태를 확인할 수 있게 하는 요약."""
    with _lock:
        return {
            "pending": len(_events),
            "oldest_seq": _events[0]["seq"] if _events else None,
            "latest_seq": _next_seq - 1,
            "snapshots_held": len(_snapshots),
        }
