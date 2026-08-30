"""수동 주행을 녹화하고 그대로 재생한다 (티치 앤 리피트).

왜 이 방식인가
-------------
라즈봇에는 바퀴 엔코더도 IMU 도 없어서 "1m 앞으로" 같은 명령을 정확히 수행할
방법이 없다. 대신 사람이 한 번 몰아서 보여준 것을 그대로 따라 하게 한다.
같은 명령을 같은 시간만큼 주면 대체로 같은 경로를 간다.

대체로일 뿐이라는 게 이 방식의 한계다. 배터리가 닳으면 같은 PWM 이라도 느려지고,
바닥이 미끄러우면 회전각이 달라진다. 그래서 경유점마다 ArUco 마커로 위치를 다시
잡아 오차가 누적되지 않게 한다(marker_locator.py). 구간 이동은 재생으로, 위치
확정은 마커로 — 이 조합이 추가 하드웨어 없이 좌표 순찰을 가능하게 한다.

세그먼트 형식
------------
    {"speed": 60, "turn": 0, "duration_s": 1.24}

같은 명령이 이어지면 한 세그먼트로 합친다. 웹 조이스틱은 초당 수십 번 명령을
보내므로, 합치지 않으면 세그먼트가 수백 개가 되어 재생 오차만 커진다.

경로 전체는 MissionEngine 이 기대하는 physical_route 형식으로 저장한다.

    {"status": "verified", "controller": "teach_replay_v1", "segments": [...]}
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

CONTROLLER_NAME = "teach_replay_v1"

# 이 값보다 작은 차이는 같은 명령으로 본다. 조이스틱은 미세하게 흔들리므로
# 그대로 두면 세그먼트가 잘게 쪼개진다.
SPEED_EPS = 8.0
TURN_EPS = 8.0

# 이보다 짧은 구간은 버린다. 손이 스친 정도의 입력까지 재생하면 로봇이 떤다.
MIN_SEGMENT_S = 0.12

ROUTES_DIR = Path(__file__).resolve().parent / "state" / "routes"


class RouteRecorder:
    """수동 주행 명령을 받아 세그먼트로 합쳐 쌓는다.

    on_drive 는 웹에서 명령이 올 때마다 불린다. 정지(속도·회전 0)도 하나의
    구간으로 기록한다 — 순찰 중 잠시 멈추는 동작도 경로의 일부다.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._segments = []
        self._cur = None          # {"speed", "turn", "start"}
        self._recording = False
        self._started_at = None
        self._name = None

    def start(self, name="route"):
        with self._lock:
            self._segments = []
            self._cur = None
            self._recording = True
            self._started_at = time.time()
            self._name = str(name or "route")
        return self.status()

    def on_drive(self, speed, turn):
        """웹이 주행 명령을 보낼 때마다 호출한다. 녹화 중이 아니면 아무 일도 안 한다."""
        if not self._recording:
            return
        now = time.time()
        with self._lock:
            if self._cur is None:
                self._cur = {"speed": float(speed), "turn": float(turn), "start": now}
                return
            same = (abs(self._cur["speed"] - speed) <= SPEED_EPS
                    and abs(self._cur["turn"] - turn) <= TURN_EPS)
            if same:
                return
            self._close_segment(now)
            self._cur = {"speed": float(speed), "turn": float(turn), "start": now}

    def _close_segment(self, now):
        """호출자가 _lock 을 잡고 있어야 한다."""
        if self._cur is None:
            return
        dur = now - self._cur["start"]
        if dur >= MIN_SEGMENT_S:
            self._segments.append({
                "speed": round(self._cur["speed"], 1),
                "turn": round(self._cur["turn"], 1),
                "duration_s": round(dur, 3),
            })
        self._cur = None

    def mark(self, marker_id, distance_cm, angle_deg):
        """지금 지점에서 본 마커를 경로에 새겨둔다. 재생 때 여기서 위치를 다시 잡는다."""
        if not self._recording:
            return
        with self._lock:
            self._segments.append({
                "marker": int(marker_id),
                "distance_cm": round(float(distance_cm), 1),
                "angle_deg": round(float(angle_deg), 1),
            })

    def stop(self):
        with self._lock:
            self._close_segment(time.time())
            self._recording = False
            route = {
                "status": "verified" if self._segments else "calibration_required",
                "controller": CONTROLLER_NAME,
                "name": self._name,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "duration_s": round(sum(s.get("duration_s", 0) for s in self._segments), 2),
                "segments": list(self._segments),
            }
        return route

    def save(self, route):
        ROUTES_DIR.mkdir(parents=True, exist_ok=True)
        path = ROUTES_DIR / f"{route.get('name') or 'route'}.json"
        path.write_text(json.dumps(route, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def status(self):
        with self._lock:
            drive_segments = [s for s in self._segments if "duration_s" in s]
            return {
                "recording": self._recording,
                "name": self._name,
                "segments": len(self._segments),
                "drive_segments": len(drive_segments),
                "markers": len(self._segments) - len(drive_segments),
                "elapsed_s": round(time.time() - self._started_at, 1) if self._started_at else 0,
            }


def load_route(name):
    path = ROUTES_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_routes():
    if not ROUTES_DIR.is_dir():
        return []
    out = []
    for p in sorted(ROUTES_DIR.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "name": r.get("name") or p.stem,
                "segments": len(r.get("segments") or []),
                "duration_s": r.get("duration_s"),
                "recorded_at": r.get("recorded_at"),
            })
        except Exception:
            continue
    return out


class RoutePlayer:
    """녹화한 세그먼트를 순서대로 실행한다.

    장애물을 만나면 그 자리에서 멈추고 기다린다. 여기서 회피까지 하면 경로가
    어긋나므로, 회피는 상위(PatrolController)에 맡기고 여기서는 대기만 한다.
    """

    def __init__(self, hal, distance_fn=None, stop_distance=10.0, on_marker=None):
        self.hal = hal
        self.distance_fn = distance_fn
        self.stop_distance = float(stop_distance)
        self.on_marker = on_marker
        self._abort = threading.Event()
        self._lock = threading.Lock()
        self._state = {"playing": False, "index": 0, "total": 0, "name": None}

    def abort(self):
        self._abort.set()

    def status(self):
        with self._lock:
            return dict(self._state)

    def play(self, route, tick_s=0.05):
        segments = (route or {}).get("segments") or []
        self._abort.clear()
        with self._lock:
            self._state = {"playing": True, "index": 0, "total": len(segments),
                           "name": route.get("name")}
        try:
            for i, seg in enumerate(segments):
                if self._abort.is_set():
                    break
                with self._lock:
                    self._state["index"] = i

                if "marker" in seg:
                    # 위치 확인 지점. 실제 보정은 상위에서 처리한다.
                    if self.on_marker:
                        try:
                            self.on_marker(seg)
                        except Exception as e:
                            print(f"[route] 마커 콜백 실패(무시): {e}")
                    continue

                self._run_segment(seg, tick_s)
        finally:
            self.hal.stop()
            with self._lock:
                self._state["playing"] = False
        return self.status()

    def _run_segment(self, seg, tick_s):
        speed = float(seg.get("speed", 0))
        turn = float(seg.get("turn", 0))
        remaining = float(seg.get("duration_s", 0))

        while remaining > 0 and not self._abort.is_set():
            # 앞이 막혔으면 시간을 세지 않고 기다린다. 그래야 장애물이 치워졌을 때
            # 남은 거리를 그대로 이어갈 수 있다.
            if speed > 0 and self.distance_fn is not None:
                d = self.distance_fn()
                if d is not None and d < self.stop_distance:
                    self.hal.stop()
                    time.sleep(tick_s)
                    continue

            self.hal.set_motion(speed, turn)
            step = min(tick_s, remaining)
            time.sleep(step)
            remaining -= step

        self.hal.stop()
