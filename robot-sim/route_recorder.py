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

    # 마커 보정 파라미터. 녹화 때와 지금 보이는 값의 차이를 이 안에서 줄인다.
    ALIGN_ANGLE_TOL = 3.0      # 이 각도 안이면 방향은 맞은 것으로 본다
    ALIGN_DIST_TOL = 6.0       # 이 거리 안이면 위치도 맞은 것으로 본다(cm)
    ALIGN_TURN_SPEED = 30.0    # 보정 회전 속도 — 느려야 넘어가지 않는다
    ALIGN_MOVE_SPEED = 35.0
    ALIGN_MAX_TRIES = 12       # 무한히 흔들리지 않도록 상한을 둔다

    def __init__(self, hal, distance_fn=None, stop_distance=10.0, on_marker=None,
                 speed_cap_fn=None, marker_fn=None):
        self.hal = hal
        self.distance_fn = distance_fn
        self.stop_distance = float(stop_distance)
        self.on_marker = on_marker
        # 거리에 따라 속도를 줄이는 함수. 수동 주행·자동순찰과 같은 것을 쓴다.
        # 없으면 녹화된 속도를 그대로 내보내는데, 그러면 벽까지 전속으로 달리다
        # 임계값에서 급정거해 관성으로 밀고 들어간다(실측: 4.6cm 까지 박았다).
        self.speed_cap_fn = speed_cap_fn
        # 지금 보이는 마커 목록을 돌려주는 함수. 없으면 보정 없이 재생만 한다.
        self.marker_fn = marker_fn
        self.align_log = []
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
                    self._align_to_marker(seg, tick_s)
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

    def _see(self, marker_id):
        """지금 보이는 마커 중 해당 ID 를 찾는다. 없으면 None."""
        if self.marker_fn is None:
            return None
        try:
            for m in self.marker_fn() or []:
                if int(m.get("id", -1)) == int(marker_id):
                    return m
        except Exception as e:
            print(f"[route] 마커 조회 실패: {e}")
        return None

    def _nudge(self, speed, turn, seconds):
        """짧게 움직이고 멈춘다. 보정은 조금씩 여러 번이 안전하다."""
        self.hal.set_motion(speed, turn)
        time.sleep(seconds)
        self.hal.stop()
        time.sleep(0.25)   # 관성이 멎고 카메라가 안정될 때까지 기다린다

    def _align_to_marker(self, seg, tick_s):
        """녹화 때 이 지점에서 봤던 마커 값으로 지금 위치를 되돌린다.

        녹화 때  마커 1번 · 60cm · +3도
        지금     마커 1번 · 75cm · -8도
          -> 11도 오른쪽으로 돌고 15cm 앞으로 가면 그때 자리에 선다.

        이것이 티치 앤 리피트의 오차를 끊어주는 지점이다. 여기서 맞춰두면
        다음 구간은 다시 깨끗한 상태에서 시작한다.
        """
        want_id = seg.get("marker")
        want_dist = float(seg.get("distance_cm", 0))
        want_angle = float(seg.get("angle_deg", 0))
        entry = {"marker": want_id, "want": [want_dist, want_angle], "tries": 0}

        seen = self._see(want_id)
        if seen is None:
            # 안 보이면 좌우로 조금씩 돌며 찾는다. 재생 중 틀어졌을 때를 대비한다.
            for i in range(6):
                if self._abort.is_set():
                    break
                self._nudge(0, self.ALIGN_TURN_SPEED * (1 if i % 2 == 0 else -1), 0.18 * (i + 1))
                seen = self._see(want_id)
                if seen is not None:
                    break
        if seen is None:
            entry["result"] = "not_found"
            self.align_log.append(entry)
            print(f"[route] 마커 {want_id} 을(를) 못 찾음 — 보정 없이 진행")
            return

        entry["found"] = [seen["distance_cm"], seen["angle_deg"]]
        for _ in range(self.ALIGN_MAX_TRIES):
            if self._abort.is_set():
                break
            seen = self._see(want_id)
            if seen is None:
                break
            d_angle = seen["angle_deg"] - want_angle
            d_dist = seen["distance_cm"] - want_dist
            entry["tries"] += 1

            if abs(d_angle) > self.ALIGN_ANGLE_TOL:
                # 마커가 오른쪽에 더 치우쳐 보이면 오른쪽으로 돌아야 가운데로 온다.
                turn = self.ALIGN_TURN_SPEED if d_angle > 0 else -self.ALIGN_TURN_SPEED
                self._nudge(0, turn, min(0.30, 0.012 * abs(d_angle) + 0.06))
                continue

            if abs(d_dist) > self.ALIGN_DIST_TOL:
                # 지금이 더 멀면 앞으로, 더 가까우면 뒤로.
                speed = self.ALIGN_MOVE_SPEED if d_dist > 0 else -self.ALIGN_MOVE_SPEED
                if speed > 0 and self.distance_fn is not None:
                    d = self.distance_fn()
                    if d is not None and d < self.stop_distance:
                        break   # 앞이 막혔으면 더 못 간다
                self._nudge(speed, 0, min(0.35, 0.006 * abs(d_dist) + 0.08))
                continue

            entry["result"] = "aligned"
            entry["final"] = [seen["distance_cm"], seen["angle_deg"]]
            self.align_log.append(entry)
            print(f"[route] 마커 {want_id} 정렬 완료 · "
                  f"{seen['distance_cm']:.1f}cm {seen['angle_deg']:+.1f}도 "
                  f"(목표 {want_dist:.1f}cm {want_angle:+.1f}도, {entry['tries']}회)")
            return

        entry["result"] = "gave_up"
        if seen:
            entry["final"] = [seen["distance_cm"], seen["angle_deg"]]
        self.align_log.append(entry)
        print(f"[route] 마커 {want_id} 정렬 미완 — {entry['tries']}회 시도 후 진행")

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

            drive_speed = speed
            if speed > 0 and self.speed_cap_fn is not None and self.distance_fn is not None:
                cap = self.speed_cap_fn(self.distance_fn())
                drive_speed = min(speed, cap)
                if drive_speed <= 0:
                    # 감속 곡선이 0 을 주면 정지선 안이다. 시간을 세지 않고 기다린다.
                    self.hal.stop()
                    time.sleep(tick_s)
                    continue
            self.hal.set_motion(drive_speed, turn)
            step = min(tick_s, remaining)
            time.sleep(step)
            remaining -= step

        self.hal.stop()
