"""마커를 좌표로 삼아 순찰한다.

왜 티치 앤 리피트를 버렸는가
--------------------------
녹화한 (속도, 회전, 시간) 을 그대로 되감는 방식은 이 로봇에서 안 된다. 엔코더가
없어서 "얼마나 갔는지"를 알 수 없고, 바닥 마찰과 배터리 전압에 따라 같은 명령이
매번 다른 거리를 만든다. 구간이 60개면 오차가 60번 쌓인다. 실제로 1m 넘게 떨어진
마커 사이를 재생시켰더니 로봇은 거의 제자리에 있었다.

여기서는 반대로 간다. 목표 마커를 카메라로 계속 보면서 그쪽으로 달린다. 매
0.2초마다 마커까지의 거리와 방향을 다시 재서 조향을 고친다. 폐루프이므로
오차가 쌓일 수가 없다 - 틀어지면 다음 관측에서 바로 잡힌다. 도착 판정도 시간이
아니라 "마커까지 70cm 안" 이라는 실제 거리로 한다.

좌표는 어디서 나오는가
--------------------
마커마다 실제 좌표를 사람이 재서 적어준다(patrol_map.json). 로봇은 다음 마커까지
남은 거리를 알고 있으므로, 직전 마커에서 다음 마커로 가는 선 위 어디쯤인지
역산할 수 있다.

    진행률 = (구간 길이 - 남은 거리) / 구간 길이
    현재 좌표 = 직전 마커 + (다음 마커 - 직전 마커) x 진행률

로봇이 그 선에서 크게 벗어나면 이 추정은 틀린다. 그래도 순찰에서는 로봇이 늘
다음 마커를 향해 달리므로 선에서 멀리 못 벗어난다. 라이다 없이 얻을 수 있는
정확도로는 이게 상한이다.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / "state"
MAP_DIR = STATE_DIR / "patrol_maps"

# 실물 라즈봇과 아이작 심 가상 실험실은 완전히 다른 공간이다. 방 크기도, 좌표계도,
# 로봇이 얼마나 가는지도 다르다. 같은 파일을 쓰면 한쪽 순찰이 다른 쪽을 덮어쓴다.
# 웹에서 "자동 순찰 복귀"를 눌렀을 때 어느 쪽 로봇인지에 따라 다른 지도를 써야 한다.
ENVIRONMENTS = ("real", "isaac")
DEFAULT_ENV = os.environ.get("LABKEEPER_ENV", "real")


def _env(name=None):
    name = (name or DEFAULT_ENV or "real").strip().lower()
    return name if name in ENVIRONMENTS else "real"


def map_path(env=None):
    return MAP_DIR / f"{_env(env)}.json"

# --- 회전 ---
# 정지마찰 때문에 이보다 약하게 주면 소리만 나고 안 돈다. 실측으로 찾은 값이다.
TURN_SPEED = 60.0
TURN_PULSE_S = 0.10        # 한 펄스 약 2.7도
DEG_PER_PULSE = 2.7
FACE_TOL_DEG = 6.0         # 이 안에 들어오면 정면으로 본다
FACE_MAX_PULSES = 40

STEER_GAIN = 1.6           # 방향 오차 1도당 turn 값. 크면 좌우로 흔들린다.
STEER_MAX = 45.0
CONTROL_HZ = 5.0           # 초당 몇 번 다시 보고 고칠 것인가

# --- 마커를 놓쳤을 때 ---
LOST_GRACE = 6             # 이만큼 연속으로 못 보면 멈추고 카메라로 찾는다
PAN_SWEEP = (90, 65, 115, 45, 135)   # 훑어볼 카메라 각도
PAN_SETTLE_BASE_S = 0.30             # 화면이 안정될 때까지
PAN_DEG_PER_S = 150.0                # 서보가 실제로 도는 속도(real_hal 과 같은 값)

# --- 안전 ---
# 자유주행에서 검증된 곡선을 그대로 쓴다: 40cm 부터 서서히 줄이고 10cm 에서 선다.
# 문턱도 넘고 벽 앞에서도 자연스럽게 멎는 게 실제 주행으로 확인됐다.
#
# 한동안 25cm 정지·60cm 감속으로 더 보수적으로 잡았는데 오히려 나빴다. 감속한
# 속도가 최소 구동속도(50) 밑으로 떨어지면 "막혔다"로 판정해서, 벽이 45cm 나
# 남았는데도 순찰이 멈춰 섰다. 바닥 속도를 지켜주면 그런 일이 없다.
PATROL_STOP_CM = 10.0      # 이보다 가까우면 무조건 정지
PATROL_SLOW_CM = 40.0      # 이 안쪽부터 감속을 시작한다

# 이보다 짧게 읽히면 측정 실패로 본다.
#
# 로봇은 10cm 에서 서므로 주행 중에 3cm 가 나올 수가 없다. 그런데 실제로
# 2.3 / 2.9 / 3.9cm 가 연달아 나왔고(2026-08-31 순찰), 그걸 장애물로 믿고
# 50도씩 비켜서다가 네모가 통째로 틀어졌다. CPU 가 바쁠 때 에코 측정이 밀려
# 펄스가 짧게 잡히는 것으로 보인다 - 예전에 sleep(0) 하나가 같은 증상을 만든
# 적이 있다.
#
# 짧은 쪽으로만 틀리는 고장이라, 하한을 두고 버리는 게 안전하다. 진짜로
# 8cm 앞에 벽이 있다면 그건 이미 10cm 정지선을 지난 것이라 다른 문제다.
SONAR_MIN_TRUST_CM = 8.0
BLOCKED_LIMIT = 8          # 막힌 상태가 이만큼 이어지면 회피를 시도한다
LEG_TIMEOUT_S = 90.0       # 한 구간에 이 이상 걸리면 뭔가 잘못된 것이다

# --- 회피 ---
# 초음파는 앞쪽 좁은 원뿔 하나뿐이라 "왼쪽이 비었는지"를 알 수 없다. 그래서 어디로
# 피할지 계산할 수가 없다. 대신 좌표 주행이라는 성질을 이용한다: 옆으로 조금
# 비켜서고 나면 목표는 여전히 좌표로 남아 있으므로 거기로 다시 방향을 잡으면 된다.
# 비켜선 만큼 각도가 달라져서 아까 막힌 것을 비껴간다. 경로를 되감는 방식이었다면
# 한 번 비켜선 순간 나머지 경로가 통째로 어긋나서 이게 불가능하다.
#
# 사람은 다르게 다룬다. 사람 옆으로 파고드는 건 위험하고, 사람은 어차피 알아서
# 비킨다. 그래서 멈춰 서서 기다린다.
DETOUR_TURN_DEG = 50.0     # 옆으로 틀 각도
DETOUR_CM = 40.0           # 틀고 나서 옆으로 갈 거리
MAX_DETOURS = 2            # 이 횟수를 넘으면 그 지점을 포기한다
PERSON_WAIT_S = 20.0       # 사람이 비킬 때까지 기다리는 최대 시간

# 비켜서기를 기본으로 끈다.
#
# 실측(2026-08-31)에서 이게 순찰 모양을 망가뜨렸다. 초음파 헛값을 장애물로 믿고
# 50도씩 틀었고, 그 회전이 그대로 누적돼 네모가 찌그러졌다. 헛값 자체는 8cm
# 하한으로 걸렀지만, 비켜서기는 성공해도 문제가 남는다 - 옆에 뭐가 있는지 모른
# 채 트는 것이라 반쯤은 도박이고, 실패하면 각도만 버린다.
#
# 좁은 방에서는 비켜설 자리 자체가 없어서 득보다 실이 크다. 막히면 그냥 그
# 지점을 포기하고 다음으로 넘어간다 - 그러면 회전이 90도씩만 일어나 모양이
# 유지된다. 넓은 공간에서 쓰고 싶으면 /patrol/avoid?on=1 로 켠다.
#
# 사람 기다리기는 끄지 않는다. 제자리에 서 있는 것이라 각도를 건드리지 않고,
# 안전에 직접 걸린 동작이다.
AVOID_DEFAULT = os.environ.get("LABKEEPER_PATROL_AVOID", "0") == "1"

# --- 알림음 ---
# 순찰 중 앞이 막히면 소리로 알린다. 사람과 물체를 다른 소리로 내는 이유는,
# 사람에게는 "비켜주세요"라는 신호이고 물체는 "여기 뭔가 있다"는 기록이기
# 때문이다. 같은 소리를 내면 사람이 자기한테 하는 말인지 알 수가 없다.
#
#   사람  : 짧게 두 번 (buzz_warning). 재촉하지 않는 정도의 알림.
#   물체  : 길게 한 번. 사람이 반응할 필요가 없는 소리.
#
# 쿨다운을 두는 이유는 벽 앞에서 계속 울리면 소음이 되기 때문이다. 실제로
# 장애물 알림에서 같은 문제가 있었다(벽 앞 15초마다 194건 신고).
BEEP_COOLDOWN_S = 8.0


def cruise_speed(distance_cm):
    """멀면 빠르게, 가까우면 천천히. 목표 앞에서 관성으로 지나치는 걸 막는다."""
    if distance_cm > 200:
        return 85.0
    if distance_cm > 120:
        return 75.0
    if distance_cm > 80:
        return 65.0
    return 55.0


def default_map(env=None):
    """로봇이 선 자리를 (0,0) 으로 삼고 도는 네모. 마커는 없어도 된다."""
    side = 80 if _env(env) == "real" else 200
    return {
        "name": "square",
        "env": _env(env),
        "note": "로봇의 처음 자리가 (0,0). 오른쪽 -> 위 -> 왼쪽 -> 제자리 순으로 돈다.",
        "waypoints": [
            {"name": "출발", "marker": None, "x_cm": 0, "y_cm": 0},
            {"name": "1", "marker": None, "x_cm": side, "y_cm": 0},
            {"name": "2", "marker": None, "x_cm": side, "y_cm": side},
            {"name": "3", "marker": None, "x_cm": 0, "y_cm": side},
        ],
    }


def load_map(env=None):
    try:
        data = json.loads(map_path(env).read_text(encoding="utf-8"))
        data.setdefault("env", _env(env))
        return data
    except Exception:
        return default_map(env)


def save_map(data, env=None):
    env = _env(data.get("env") if isinstance(data, dict) else None or env)
    data = dict(data, env=env)
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    map_path(env).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return data


def list_maps():
    """환경별로 어떤 지도가 있는지. 웹에서 고를 수 있게 한다."""
    out = {}
    for env in ENVIRONMENTS:
        data = load_map(env)
        out[env] = {"name": data.get("name"),
                    "waypoints": len(data.get("waypoints") or []),
                    "saved": map_path(env).exists()}
    return out


def bearing_of(marker, cam_pan):
    """로봇 몸통 기준 마커 방향(도). 오른쪽이 양수.

    카메라각 90 이 정면이다. 카메라가 115도(오른쪽 25도)를 보는데 마커가 화면에서
    +5도에 있으면 몸통 기준으로는 +30도다. 이걸 빼먹으면 카메라를 돌려놓은 채로
    몸통이 엉뚱한 방향으로 돈다.
    """
    return (float(cam_pan) - 90.0) + float(marker["angle_deg"])


class PatrolRunner:
    """마커를 순서대로 찾아가며 한 바퀴 돌고 제자리로 돌아온다."""

    def __init__(self, hal, marker_fn=None, speed_cap_fn=None, on_event=None,
                 odometry=None, on_finish=None, person_fn=None):
        self.hal = hal
        self.marker_fn = marker_fn            # () -> [{id, distance_cm, angle_deg}]
        self.speed_cap_fn = speed_cap_fn      # (거리cm) -> 허용 속도
        self.on_event = on_event
        # 순찰이 끝나면(정상 종료든 중단이든) 알려준다. 바퀴 소유권을 놓는 데 쓴다.
        self.on_finish = on_finish
        self._last_blocked = False
        self._front_cm = None
        self._sonar_rejects = 0     # 못 믿어서 버린 초음파 측정 횟수
        self._marker_fixes = 0      # 마커로 방향을 고친 횟수
        self._fix_tick = 0
        self._map = None            # 지금 도는 지도(마커 좌표를 여기서 읽는다)
        self._all_short = 0         # 셋 다 못 믿을 값이었던 연속 횟수
        self.avoid_enabled = AVOID_DEFAULT
        self._detour_side = 1
        self._last_beep = {"person": 0.0, "object": 0.0}
        # 앞을 막은 게 사람인지 묻는 함수. AI 비전이 알려준다.
        self.person_fn = person_fn
        # 좌표 추적. 명령을 적분해 지금 위치를 안다. 마커는 보이면 보정에 쓰고
        # 안 보이면 그냥 적분만으로 간다.
        from odometry import Odometry
        self.odometry = odometry or Odometry()
        self._thread = None
        self._abort = threading.Event()
        self._lock = threading.Lock()
        self._state = {
            "running": False, "map": None, "env": DEFAULT_ENV, "lap": 0, "laps": 1,
            "leg": 0, "legs": 0, "target": None, "phase": "idle",
            "distance_cm": None, "bearing_deg": None,
            "x_cm": None, "y_cm": None, "started_at": None, "message": "",
        }

    # ---------- 상태 ----------

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    def status(self):
        with self._lock:
            st = dict(self._state)
        st["sonar_rejects"] = self._sonar_rejects
        st["front_cm"] = self._front_cm
        st["avoid_enabled"] = self.avoid_enabled
        st["marker_fixes"] = self._marker_fixes
        return st

    def _log(self, msg):
        print(f"[patrol] {msg}")
        self._set(message=msg)
        if self.on_event:
            try:
                self.on_event(msg, self.status())
            except Exception as e:
                print(f"[patrol] 이벤트 콜백 실패(무시): {e}")

    # ---------- 카메라 ----------

    def _pan(self, angle):
        """카메라를 그 각도로 돌리고 도착할 때까지 기다린다.

        set_camera_angle 은 목표만 정하고 즉시 돌아온다. 실제 이동은 서보
        스레드가 초당 150도로 한다. 기다리지 않고 바로 촬영하면 아직 가는 중인
        화면을 보게 되어 마커를 놓친다.
        """
        before = self._cam_pan()
        try:
            self.hal.set_camera_angle(pan=angle)
        except Exception as e:
            print(f"[patrol] 카메라 이동 실패(무시): {e}")
        travel = abs(float(angle) - before) / PAN_DEG_PER_S
        time.sleep(PAN_SETTLE_BASE_S + travel)

    def _cam_pan(self):
        return float(getattr(self.hal, "cam_pan", 90.0))

    def _see(self, marker_id):
        """지금 화면에 그 마커가 있으면 돌려준다."""
        try:
            for m in self.marker_fn() or []:
                if int(m.get("id", -1)) == int(marker_id):
                    return m
        except Exception as e:
            print(f"[patrol] 마커 조회 실패: {e}")
        return None

    def _acquire(self, marker_id):
        """카메라를 훑어 마커를 찾는다. (마커, 카메라각) 또는 (None, 90).

        몸통을 돌려 찾지 않는 게 중요하다. 카메라는 즉시 정확히 움직이지만 몸통은
        정지마찰 때문에 뭉텅이로 움직이고, 찾는 동안 위치까지 틀어져 버린다.
        """
        for pan in PAN_SWEEP:
            if self._abort.is_set():
                break
            self._pan(pan)
            m = self._see(marker_id)
            if m is not None:
                return m, float(pan)
        self._pan(90)
        return None, 90.0

    # ---------- 몸통 회전 ----------

    def turn_in_place(self, degrees):
        """제자리 회전. 배달 복귀 뒤 방향을 되돌릴 때 밖에서도 쓴다."""
        return self._turn_pulse(degrees)

    def _turn_pulse(self, degrees):
        """제자리에서 지정한 각도만큼 돈다. 오른쪽이 양수.

        실측한 회전 속도로 필요한 시간을 계산한다. 예전처럼 '한 펄스 2.7도'로
        고정하지 않는다 - 90도를 돌아야 하면 33번 끊어 도는 게 아니라 한 번에
        도는 게 훨씬 정확하고 빠르다.
        """
        if abs(degrees) < 1.0:
            return
        turn = TURN_SPEED if degrees > 0 else -TURN_SPEED
        seconds = self.odometry.seconds_for_deg(abs(degrees), TURN_SPEED)
        # 정지마찰 때문에 아주 짧은 명령은 아예 안 움직인다. 하한을 둔다.
        seconds = max(TURN_PULSE_S, min(3.0, seconds))
        # 실제로 보낸 명령을 남긴다. "1·2번 코너가 더 도는 것 같다"는 관찰이
        # 나왔을 때, 명령이 달랐는지 아니면 같은 명령인데 결과가 달랐는지를
        # 갈라야 한다. 전자면 계산 문제고 후자면 배터리·바닥 문제다.
        before = self.odometry.pose()["heading_deg"]
        self.hal.set_motion(0, turn)
        time.sleep(seconds)
        self.hal.stop()
        self.odometry.apply(0, turn, seconds)
        after = self.odometry.pose()["heading_deg"]
        self._log(f"회전 명령: 목표 {degrees:+.1f}도 · turn {turn:+.0f} · "
                  f"{seconds:.3f}초 · 방향 {before:.1f}→{after:.1f}")
        time.sleep(0.25)          # 관성이 멎고 화면이 안정될 때까지

    def _face(self, marker_id):
        """마커를 정면으로 볼 때까지 몸통을 돌린다. 카메라는 정면에 고정한다.

        카메라로 찾고 몸통으로 맞춘다. 찾은 뒤에는 카메라를 90도로 되돌려야
        다음 직진에서 조향 계산이 맞는다.
        """
        m, pan = self._acquire(marker_id)
        if m is None:
            return False
        # 카메라가 옆을 보고 있으면 그만큼 몸통을 먼저 돌려 정면으로 가져온다.
        if abs(pan - 90.0) > 1.0:
            self._turn_pulse(bearing_of(m, pan))
            self._pan(90)

        for _ in range(FACE_MAX_PULSES):
            if self._abort.is_set():
                return False
            m = self._see(marker_id)
            if m is None:
                m, pan = self._acquire(marker_id)
                if m is None:
                    return False
                self._pan(90)
                continue
            b = bearing_of(m, self._cam_pan())
            self._set(distance_cm=m["distance_cm"], bearing_deg=round(b, 1))
            if abs(b) <= FACE_TOL_DEG:
                return True
            self._turn_pulse(b)
        return True   # 못 맞춰도 대충 향했으니 출발한다. 달리면서 계속 고친다.

    # ---------- 직진 ----------

    def _approach(self, waypoint, prev_wp):
        """마커가 목표 거리 안에 들어올 때까지 달린다.

        멈춰서 재는 게 아니라 달리면서 계속 본다. 초당 5번 거리와 방향을 다시
        재고 조향을 고친다. 이래야 오차가 쌓이지 않는다.
        """
        marker_id = waypoint["marker"]
        stop_cm = float(waypoint.get("stop_cm", 70))
        leg_len = self._leg_length(prev_wp, waypoint)
        started = time.time()
        lost = 0
        blocked = 0
        tick = 1.0 / CONTROL_HZ

        while not self._abort.is_set():
            if time.time() - started > LEG_TIMEOUT_S:
                self.hal.stop()
                self._log(f"마커 {marker_id} 구간 시간 초과 — 다음으로 넘어간다")
                return False

            m = self._see(marker_id)
            if m is None:
                lost += 1
                if lost >= LOST_GRACE:
                    self.hal.stop()
                    m, _pan = self._acquire(marker_id)
                    self._pan(90)
                    if m is None:
                        self._log(f"마커 {marker_id} 을(를) 놓쳤다 — 구간 중단")
                        return False
                    lost = 0
                else:
                    time.sleep(tick)
                    continue
            else:
                lost = 0

            dist = float(m["distance_cm"])
            b = bearing_of(m, self._cam_pan())
            self._set(distance_cm=dist, bearing_deg=round(b, 1),
                      **self._estimate_xy(prev_wp, waypoint, dist, leg_len))

            if dist <= stop_cm:
                self.hal.stop()
                # 마커에 도착했으면 그 좌표를 안다. 여기서 적분 오차를 0 으로
                # 되돌린다. 이게 마커를 쓰는 진짜 이유다.
                self._log(f"마커 {marker_id} 도착 · {dist:.0f}cm")
                return True

            # 초음파가 앞을 막으면 속도를 줄이거나 멈춘다. 순찰이 벽을 들이받는
            # 일은 없어야 한다.
            speed = self._allowed_speed(cruise_speed(dist))
            if speed <= 1.0:
                blocked += 1
                self.hal.stop()
                if blocked >= BLOCKED_LIMIT:
                    self._log(f"마커 {marker_id} 앞이 막혔다 — 구간 포기")
                    return False
                self._set(phase="blocked")
                time.sleep(tick)
                continue
            blocked = 0
            self._set(phase="driving")

            # 방향이 크게 틀어졌으면 달리지 말고 제자리에서 잡는다. 달리면서
            # 크게 꺾으면 그만큼 옆으로 밀려난다.
            if abs(b) > 25:
                self.hal.stop()
                self._turn_pulse(b)
                continue

            turn = max(-STEER_MAX, min(STEER_MAX, b * STEER_GAIN)) + self._trim(speed)
            self.hal.set_motion(speed, turn)
            time.sleep(tick)
            self.odometry.apply(speed, turn, tick)

        self.hal.stop()
        return False

    # ---------- 좌표로 이동 ----------

    ARRIVE_TOL_CM = 20.0     # 이 안에 들어오면 도착으로 본다
    GOTO_MAX_TRIES = 4       # 목표를 지나쳤을 때 다시 잡을 기회
    DRIVE_CHUNK_S = 0.3      # 이만큼씩 끊어 가며 장애물을 확인한다

    def _drive_cm(self, cm, cap_speed=None):
        """앞으로 cm 만큼 간다. 실제로 간 거리를 돌려준다.

        한 번에 쭉 가지 않고 0.3초씩 끊는다. 그래야 중간에 장애물이 나타나도
        멈출 수 있고, 오도메트리도 그 단위로 갱신된다.
        """
        if cm <= 1.0:
            return 0.0
        speed = cruise_speed(cm)
        if cap_speed is not None:
            speed = min(speed, cap_speed)
        gone = 0.0
        blocked = 0
        self._last_blocked = False
        while gone < cm and not self._abort.is_set():
            allowed = self._allowed_speed(speed)
            if allowed <= 1.0:
                self.hal.stop()
                blocked += 1
                self._set(phase="blocked")
                if blocked >= BLOCKED_LIMIT:
                    self._last_blocked = True
                    self._beep("person" if self._person_ahead() else "object")
                    self._log(f"앞이 막혔다 — 초음파 {self._front_cm}cm · "
                              f"{cm - gone:.0f}cm 남기고 이 구간 포기")
                    break
                time.sleep(0.25)
                continue
            blocked = 0
            self._set(phase="driving")

            remaining = cm - gone
            chunk = min(self.DRIVE_CHUNK_S,
                        max(0.12, self.odometry.seconds_for_cm(remaining, allowed)))
            self.hal.set_motion(allowed, self._trim(allowed))
            time.sleep(chunk)
            # 달리는 도중에 마커가 보이면 그때 방향을 고친다. 멈춰 서서 찾지
            # 않는 이유는, 순찰이 매번 서면 느려지고 정지·재출발 자체가 또
            # 오차를 만들기 때문이다.
            self._fix_tick += 1
            if self._fix_tick % self.MARKER_FIX_EVERY == 0:
                self._fix_heading_from_markers()
            # 오도메트리에는 회전 0 으로 넣는다. trim 은 방향을 바꾸려는 게 아니라
            # 휘는 걸 상쇄해 똑바로 가게 하는 값이므로, 결과는 직진이다.
            moved, _ = self.odometry.apply(allowed, 0, chunk)
            gone += abs(moved)
            self._set(**self._pose_fields())
        self.hal.stop()
        time.sleep(0.3)
        return gone

    # 주행 중 마커 보정
    #
    # 왜 방향만 고치는가
    # -----------------
    # 이 로봇에서 오차가 쌓이는 주범은 방향이다. 2도만 틀어져도 190cm 가는 동안
    # 6.6cm 벌어지고, 그게 다음 변으로 그대로 넘어간다. 거리는 줄자로 맞춰서
    # 이미 잘 맞는다.
    #
    # 마커가 (mx,my) 에 있다는 걸 알고, 지금 내 위치를 (대충) 안다면, 마커가
    # 있어야 할 절대 방향 φ 를 계산할 수 있다. 그런데 실제로는 마커가 몸통 기준
    # b 방향에 보인다. 그러면 내 진짜 방향은
    #
    #     heading = φ + b
    #
    # 이다. 위치가 조금 틀려도 φ 는 거의 안 변한다 - 2.5m 떨어진 마커라면
    # 위치가 10cm 틀려도 φ 는 2.3도밖에 안 움직인다. 그래서 위치 오차에 둔감하고
    # 방향만 깨끗하게 뽑힌다.
    #
    # 마커의 기울기(solvePnP yaw)를 쓰면 위치까지 고칠 수 있지만 부호를 잘못
    # 잡으면 오차를 키운다. 방향(bearing)의 부호는 오늘 주행으로 검증됐으므로
    # 확실한 쪽만 쓴다.
    MARKER_FIX_EVERY = 5        # 몇 틱마다 마커를 찾아볼 것인가
    MARKER_FIX_MIN_CM = 60.0    # 너무 가까우면 각도가 예민해져 안 쓴다
    MARKER_FIX_MAX_DEG = 25.0   # 이보다 큰 보정은 잘못 본 것으로 보고 버린다

    def _marker_positions(self):
        """지도에 적힌 마커 번호 -> 좌표."""
        out = {}
        for wp in (self._map or {}).get("waypoints") or []:
            mid = wp.get("marker")
            if mid is not None:
                out[int(mid)] = (float(wp.get("x_cm", 0)), float(wp.get("y_cm", 0)))
        return out

    def _fix_heading_from_markers(self):
        """지금 보이는 마커로 방향을 고친다. 못 보면 조용히 넘어간다."""
        if self.marker_fn is None:
            return False
        markers = self._marker_positions()
        if not markers:
            return False
        try:
            seen = self.marker_fn() or []
        except Exception:
            return False

        # 여러 개가 보이면 먼 것을 쓴다. 멀수록 위치 오차에 둔감하다.
        best = None
        for m in seen:
            mid = int(m.get("id", -1))
            if mid not in markers or m["distance_cm"] < self.MARKER_FIX_MIN_CM:
                continue
            if best is None or m["distance_cm"] > best["distance_cm"]:
                best = m
        if best is None:
            return False

        mx, my = markers[int(best["id"])]
        pose = self.odometry.pose()
        phi = math.degrees(math.atan2(my - pose["y_cm"], mx - pose["x_cm"]))
        bearing = bearing_of(best, self._cam_pan())
        want = phi + bearing
        # -180~180 으로 접는다.
        delta = (want - pose["heading_deg"] + 180.0) % 360.0 - 180.0
        if abs(delta) < 0.5:
            return False
        if abs(delta) > self.MARKER_FIX_MAX_DEG:
            self._log(f"마커 {best['id']} 보정 {delta:+.1f}도는 너무 커서 무시한다")
            return False

        self.odometry.heading += delta
        self._marker_fixes += 1
        self._log(f"마커 {best['id']}({best['distance_cm']:.0f}cm)로 방향 보정 "
                  f"{delta:+.1f}도 -> {self.odometry.pose()['heading_deg']:.1f}도")
        return True

    # trim 을 잰 기준 속도. 이 속도에서 측정한 값을 다른 속도로 환산한다.
    TRIM_REF_SPEED = 65.0

    def _trim(self, speed=None):
        """직진할 때 섞어줄 미세 조향값. 오른쪽이 양수.

        모터 두 개가 완전히 같을 수 없다. 왼쪽이 조금 약하면 직진 명령에도 계속
        왼쪽으로 휜다. set_motion 이 left=speed+trim, right=speed-trim 으로
        섞으므로, 양수를 주면 왼쪽을 올리고 오른쪽을 동시에 낮춘다.

        속도에 비례시키는 이유
        --------------------
        불균형은 "왼쪽이 몇 % 약하다"는 비율이지 고정된 차이가 아니다. 그런데
        순찰 한 구간 안에서도 속도가 85 -> 55 로 변한다(목표에 가까워지면
        감속). 고정값을 쓰면 빠를 때 모자라고 느릴 때 과해서, 같은 구간
        앞뒤로 다르게 휜다. 잰 속도(65) 기준으로 비례시켜야 일정해진다.
        """
        base = float(self.odometry.model.get("drive_trim", 0.0))
        if not base or speed is None:
            return base
        return base * abs(float(speed)) / self.TRIM_REF_SPEED

    def _read_front(self):
        """앞 거리. 세 번 읽어 중앙값을 쓴다. 못 믿을 값이면 None.

        초음파는 바닥이나 옆 물체에서 튄 메아리로 가끔 엉뚱한 값을 낸다. 세 번
        중 가운데를 쓰면 한 번짜리 헛값은 걸러진다.

        그것과 별개로 8cm 미만은 아예 버린다. 주행 중에 그 거리가 나올 수 없기
        때문이다(10cm 에서 서니까). 이 하한이 없을 때 헛값을 벽으로 믿고 회피를
        돌려서 순찰 경로가 망가졌다.
        """
        vals = []
        rejected = 0
        for _ in range(3):
            try:
                d = self.hal.read_ultrasonic()
            except Exception:
                continue
            if not d or d <= 0 or d >= 400:
                continue
            if d < SONAR_MIN_TRUST_CM:
                rejected += 1
                continue
            vals.append(d)
        if rejected:
            self._sonar_rejects += rejected
        if vals:
            self._all_short = 0
            vals.sort()
            return vals[len(vals) // 2]

        # 셋 다 못 믿을 값이었다. 한두 번이면 노이즈로 보고 넘어간다 - 여기서
        # 막혔다고 판단하면 멀쩡한 데서 순찰이 선다.
        #
        # 하지만 계속 그러면 얘기가 다르다. 정말로 코앞에 뭐가 있어서 짧게
        # 읽히는 것일 수 있고, 그때 "모른다"며 계속 가면 그대로 박는다.
        # 모를 때 미는 것보다 서는 쪽이 안전하다.
        self._all_short += 1
        if self._all_short >= 5:
            return 0.0
        return None
        vals.sort()
        return vals[len(vals) // 2]

    def _allowed_speed(self, want):
        """지금 앞 상황에서 낼 수 있는 속도. 벽 앞에서는 0 이 나온다.

        controller.speed_cap_for_distance 만 믿으면 안 된다 - 거기엔 최소 속도
        바닥이 있어서 10cm 까지 계속 밀고 들어간다. 순찰은 25cm 에서 확실히 선다.
        """
        d = self._read_front()
        self._front_cm = d
        if d == 0.0:
            self._log("초음파가 계속 8cm 미만만 읽는다 — 코앞에 뭔가 있다고 보고 선다")
        if d is None:
            return want                      # 못 읽으면(허공) 그냥 간다
        if d <= PATROL_STOP_CM:
            return 0.0
        floor = float(self.odometry.model.get("min_move_speed", 50))
        if d < PATROL_SLOW_CM:
            ratio = (d - PATROL_STOP_CM) / (PATROL_SLOW_CM - PATROL_STOP_CM)
            # 줄이되 바닥 아래로는 안 내린다. 정지마찰 때문에 그 아래는 소리만
            # 나고 안 가는데, 그걸 "막혔다"로 읽으면 멀쩡한 데서 순찰이 선다.
            want = max(floor, want * ratio)
        return want

    def _pose_fields(self):
        p = self.odometry.pose()
        return {"x_cm": p["x_cm"], "y_cm": p["y_cm"], "heading_deg": p["heading_deg"]}

    def _beep(self, kind):
        """막힌 이유를 소리로 알린다. 사람과 물체를 다르게 낸다."""
        now = time.time()
        if now - self._last_beep.get(kind, 0.0) < BEEP_COOLDOWN_S:
            return
        self._last_beep[kind] = now
        try:
            if kind == "person":
                self.hal.buzz_warning()       # 짧게 두 번 — "지나갈게요"
            else:
                self.hal.trigger_buzzer(0.6)  # 길게 한 번 — "여기 뭔가 있다"
        except Exception as e:
            print(f"[patrol] 부저 실패(무시): {e}")

    def _person_ahead(self):
        if self.person_fn is None:
            return False
        try:
            return bool(self.person_fn())
        except Exception:
            return False

    def _wait_for_person(self):
        """사람이 비킬 때까지 멈춰 선다. 돌아가지 않는다.

        사람 옆으로 파고드는 건 위험하고, 사람은 어차피 알아서 비킨다. 기다리는
        쪽이 안전하고 결과도 낫다.
        """
        self.hal.stop()
        self._set(phase="waiting_person")
        self._beep("person")
        self._log("사람이 앞에 있다 — 비킬 때까지 기다린다")
        waited = 0.0
        while waited < PERSON_WAIT_S and not self._abort.is_set():
            time.sleep(0.5)
            waited += 0.5
            if waited % BEEP_COOLDOWN_S < 0.5:
                self._beep("person")   # 계속 서 있으면 한 번 더 알린다
            if not self._person_ahead() and (self._read_front() or 999) > PATROL_SLOW_CM:
                self._log(f"길이 열렸다 ({waited:.0f}초 기다림) — 계속 간다")
                return True
        self._log(f"{PERSON_WAIT_S:.0f}초 기다려도 안 비킨다 — 돌아서 간다")
        return False

    def _detour(self):
        """옆으로 비켜선다. 목표 방향은 goto 가 다시 잡아준다.

        어느 쪽이 비었는지 모르므로 왼쪽·오른쪽을 번갈아 시도한다.
        """
        self._detour_side = -self._detour_side
        side = "왼쪽" if self._detour_side < 0 else "오른쪽"
        self._set(phase="detour")
        self._log(f"{side}으로 비켜선다 ({DETOUR_TURN_DEG:.0f}도 · {DETOUR_CM:.0f}cm)")
        self._turn_pulse(DETOUR_TURN_DEG * self._detour_side)
        if self._drive_cm(DETOUR_CM) < 5:
            self._log("비켜설 공간도 없다")
            return False
        return True

    def goto(self, x, y, marker_id=None):
        """좌표 (x, y) 로 간다. 마커 번호를 주면 도착 후 그걸로 위치를 보정한다.

        방향을 맞추고 -> 거리만큼 달리고 -> 남은 오차를 다시 잡는다. 오도메트리가
        완벽하지 않으므로 한 번에 못 맞춘다. 도착 판정은 20cm 안이다.
        """
        blocked_out = False
        detours = 0
        for attempt in range(self.GOTO_MAX_TRIES + MAX_DETOURS):
            if self._abort.is_set():
                break
            dist, delta = self.odometry.vector_to(x, y)
            if dist <= self.ARRIVE_TOL_CM:
                break
            self._set(phase="turning", **self._pose_fields())
            self._turn_pulse(delta)
            self._set(phase="driving")
            gone = self._drive_cm(dist)
            self._log(f"({x:.0f},{y:.0f}) 로 {attempt + 1}차 이동 · "
                      f"지금 {self._pose_fields()}")
            if self._last_blocked and gone < dist - self.ARRIVE_TOL_CM:
                # 사람이면 기다린다. 비키면 그대로 이어서 간다.
                if self._person_ahead() and self._wait_for_person():
                    continue
                # 물건이면 옆으로 비켜설 수도 있지만 기본은 끄여 있다. 비켜서기가
                # 순찰 모양을 망가뜨리기 때문이다(위 AVOID_DEFAULT 설명).
                if self.avoid_enabled and detours < MAX_DETOURS and self._detour():
                    detours += 1
                    continue
                blocked_out = True
                break

        if marker_id is not None:
            # 도착했으니 마커로 방향을 한 번 더 잡아둔다. 위치는 건드리지
            # 않는다 - 위치를 덮어쓰면 heading 오차가 거리에 비례해 증폭돼
            # 로봇이 엉뚱한 곳으로 간다(실측으로 164cm 튀었다).
            self._fix_heading_from_markers()
        dist, _ = self.odometry.vector_to(x, y)
        self._set(phase="arrived", **self._pose_fields())
        return {"target": [x, y], "pose": self.odometry.pose(),
                "error_cm": round(dist, 1), "blocked": blocked_out}

    # ---------- 좌표 추정 ----------

    @staticmethod
    def _leg_length(prev_wp, wp):
        if not prev_wp:
            return 0.0
        return math.hypot(wp.get("x_cm", 0) - prev_wp.get("x_cm", 0),
                          wp.get("y_cm", 0) - prev_wp.get("y_cm", 0))

    @staticmethod
    def _estimate_xy(prev_wp, wp, dist_cm, leg_len):
        """직전 마커와 다음 마커를 잇는 선 위에서 지금 어디쯤인지."""
        if not prev_wp or leg_len <= 1:
            return {"x_cm": wp.get("x_cm"), "y_cm": wp.get("y_cm")}
        progress = max(0.0, min(1.0, (leg_len - dist_cm) / leg_len))
        return {
            "x_cm": round(prev_wp["x_cm"] + (wp["x_cm"] - prev_wp["x_cm"]) * progress, 1),
            "y_cm": round(prev_wp["y_cm"] + (wp["y_cm"] - prev_wp["y_cm"]) * progress, 1),
        }

    # ---------- 실행 ----------

    def start(self, laps=1, env=None, keep_origin=False):
        """순찰 시작. 기본적으로 지금 서 있는 자리가 원점 (0,0) 이 된다.

        순찰 경로는 '방 안의 절대 좌표'가 아니라 '출발점에서 본 상대 좌표'다.
        그래야 로봇을 어디에 놓든 같은 모양을 그린다 - 방 구석에 두면 구석에서,
        가운데 두면 가운데에서 같은 네모를 돈다. 이어서 돌 때만 keep_origin 을
        준다(그때는 직전 바퀴가 끝난 위치를 그대로 이어받는다).
        """
        if self._thread and self._thread.is_alive():
            return {"error": "이미 순찰 중"}
        data = load_map(env)
        wps = data.get("waypoints") or []
        if len(wps) < 2:
            return {"error": "순찰 경로에 지점이 2개 이상 있어야 한다"}
        # 출발 전에 앞이 트였는지 본다. 시작 방향이 곧 +x 축이므로, 벽을 보고
        # 시작하면 첫 구간부터 막힌다. 돌려서 시작하게 만들지는 않는다 - 회전
        # 오차가 네모 전체를 기울이기 때문이다. 사람에게 알리고 판단을 맡긴다.
        first_leg = self._leg_length(wps[0], wps[1]) if len(wps) > 1 else 0
        clearance = None
        try:
            clearance = self.hal.read_ultrasonic()
        except Exception:
            pass
        warning = None
        if clearance and 2 < clearance < 400 and first_leg > clearance + 20:
            warning = (f"앞이 {clearance:.0f}cm 인데 첫 구간이 {first_leg:.0f}cm 다. "
                       f"진행 방향으로 놓고 시작하는 게 좋다")
            self._log(warning)

        self._map = data
        self._marker_fixes = 0
        if not keep_origin:
            self.odometry.reset(0, 0, 0, note="순찰 시작 지점")
        self._abort.clear()
        self._set(running=True, map=data.get("name"), env=data.get("env"),
                  lap=0, laps=int(laps),
                  leg=0, legs=len(wps), phase="starting", message="",
                  started_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._thread = threading.Thread(target=self._run, args=(data, int(laps)), daemon=True)
        self._thread.start()
        return {"status": "started", "map": data.get("name"), "env": data.get("env"),
                "waypoints": [w.get("name") or w.get("marker") for w in wps],
                "laps": int(laps), "clearance_cm": clearance, "warning": warning}

    def stop(self):
        self._abort.set()
        self.hal.stop()
        return {"status": "stopping"}

    def abort(self):
        """지금 진행 중인 주행만 멈춘다. 배달 취소에서 쓴다."""
        self._abort.set()
        self.hal.stop()

    def clear_abort(self):
        """중단 신호를 푼다. 취소 뒤 복귀 주행을 돌리려면 반드시 필요하다 -
        안 풀면 복귀 goto 도 즉시 중단돼 로봇이 그 자리에 남는다."""
        self._abort.clear()

    def _run(self, data, laps):
        wps = data["waypoints"]
        try:
            for lap in range(laps):
                if self._abort.is_set():
                    break
                self._set(lap=lap + 1)
                self._log(f"{lap + 1}바퀴 시작 · 마커 {[w['marker'] for w in wps]}")

                # 출발점에서 한 바퀴 돌아 다시 출발점으로. 마지막에 첫 마커를
                # 한 번 더 방문해야 "제자리로 돌아왔다"가 된다.
                order = list(range(1, len(wps))) + [0]
                # 방이 경로보다 좁으면 어느 변에선가 벽에 막힌다. 그때 목표를
                # 그대로 두고 다음 지점으로 가면 대각선이 그려져 네모가 깨진다.
                # 대신 "막힌 그 자리"를 이번 코너로 인정하고, 남은 지점들을 같은
                # 만큼 당긴다. 그러면 방에 맞는 더 작은 네모가 그려진다.
                shift = [0.0, 0.0]
                for step, idx in enumerate(order):
                    if self._abort.is_set():
                        break
                    wp = wps[idx]
                    # 마지막 복귀는 출발점 그대로다. 집은 당기지 않는다.
                    home = idx == 0 and step == len(order) - 1
                    tx = wp.get("x_cm", 0) + (0.0 if home else shift[0])
                    ty = wp.get("y_cm", 0) + (0.0 if home else shift[1])
                    self._set(leg=step + 1, legs=len(order),
                              target=wp.get("marker"), phase="turning")
                    self._log(f"{step + 1}/{len(order)} {wp.get('name') or ''} "
                              f"({tx:.0f},{ty:.0f})cm 로 간다")
                    r = self.goto(tx, ty, marker_id=wp.get("marker"))

                    if r.get("blocked"):
                        pose = self.odometry.pose()
                        shift[0] += pose["x_cm"] - tx
                        shift[1] += pose["y_cm"] - ty
                        self._log(f"벽에 막혀 여기를 코너로 삼는다 "
                                  f"({pose['x_cm']:.0f},{pose['y_cm']:.0f})cm · "
                                  f"남은 지점을 {shift[0]:+.0f},{shift[1]:+.0f} 당김")
                    else:
                        self._log(f"도착 · 오차 {r['error_cm']}cm")

                # 제자리로 돌아왔으면 방향도 처음처럼 되돌린다. 네 번 90도를
                # 돌았으니 위치는 맞아도 몸은 뒤를 보고 있다. 다음 바퀴가
                # 같은 조건에서 시작해야 오차가 반복되지 않는다.
                if not self._abort.is_set():
                    self._set(phase="turning")
                    _d, delta = self.odometry.vector_to(
                        wps[0].get("x_cm", 0) + 100.0, wps[0].get("y_cm", 0))
                    self._turn_pulse(delta)
                    self._log(f"처음 방향으로 복귀 · {self.odometry.pose()['heading_deg']:.0f}도")

            self._set(phase="done" if not self._abort.is_set() else "aborted")
            self._log("순찰 종료" if not self._abort.is_set() else "순찰 중단됨")
        except Exception as e:
            self._log(f"순찰 오류: {e}")
            self._set(phase="error")
        finally:
            self.hal.stop()
            self._pan(90)
            self._set(running=False, target=None)
            if self.on_finish:
                try:
                    self.on_finish()
                except Exception as e:
                    print(f"[patrol] 종료 콜백 실패(무시): {e}")
