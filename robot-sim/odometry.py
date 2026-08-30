"""바퀴 명령을 좌표 변화로 바꾼다.

왜 필요한가
----------
이 로봇에는 엔코더가 없다. "앞으로 가"라고만 할 수 있고 "몇 cm 갔는지"는 알려주지
않는다. 그래서 좌표로 이동하려면 사람이 대신 재줘야 한다 - 속도 60으로 1초 가면
몇 cm 인가, 회전 60으로 1초 돌면 몇 도인가. 그 표가 여기 들어간다.

측정은 calibrate_motion.py 가 하고 결과를 state/motion_model.json 에 남긴다.
여기서는 그걸 읽어 적분만 한다.

    x     += 이동거리 x cos(heading)
    y     += 이동거리 x sin(heading)
    heading += 회전각

이 방식의 한계
------------
적분이므로 오차가 쌓인다. 바닥이 미끄러우면 바퀴가 헛돌고, 배터리가 닳으면 같은
명령이 덜 간다. 10m 를 돌면 수십 cm 는 틀어진다고 봐야 한다.

그래서 마커가 보이면 그때마다 위치를 덮어쓴다(reset_from_marker). 마커는 필수가
아니라 보정 수단이다 - 없으면 없는 대로 돌고, 보이면 그때 오차가 0 이 된다.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / "state"

# 실물 라즈봇과 아이작 심의 가상 로봇은 물리가 다르다. 실물은 정지마찰과 배터리
# 전압에 좌우되고 심은 그렇지 않다. 같은 표를 쓰면 둘 다 틀린다.
DEFAULT_ENV = os.environ.get("LABKEEPER_ENV", "real")


def model_path(env=None):
    env = (env or DEFAULT_ENV or "real").strip().lower()
    return STATE_DIR / f"motion_model_{env}.json"

# 실측 전까지 쓰는 기본값. 이전에 손으로 재둔 값에서 왔다.
#   속도 45 / 0.12초 -> 1.4cm,  속도 60 / 0.20초 -> 4.4cm,  회전 60 / 0.10초 -> 2.7도
# 정지마찰 때문에 아주 짧은 펄스는 이 표보다 덜 간다. 그건 min_pulse 로 다룬다.
DEFAULT_MODEL = {
    "forward_cm_per_s": {"45": 11.7, "60": 22.0, "75": 30.0, "85": 36.0},
    "turn_deg_per_s": {"60": 27.0, "75": 40.0, "90": 55.0},
    "min_move_speed": 40,     # 이보다 약하면 정지마찰을 못 이긴다
    "min_turn": 55,
    "note": "실측 전 기본값",
}


def load_model(env=None):
    try:
        data = json.loads(model_path(env).read_text(encoding="utf-8"))
        if data.get("forward_cm_per_s") and data.get("turn_deg_per_s"):
            return data
    except Exception:
        pass
    return dict(DEFAULT_MODEL)


def save_model(data, env=None):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = dict(data, env=(env or DEFAULT_ENV))
    model_path(env).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    return data


def _interp(table, key):
    """표에 없는 값은 양옆을 잇는 직선으로 채운다.

    속도-거리 관계는 완전한 직선은 아니지만(정지마찰 때문에 낮은 쪽이 더 손해),
    측정한 점 사이에서는 직선으로 봐도 몇 % 안에 들어온다.
    """
    pts = sorted((float(k), float(v)) for k, v in table.items())
    if not pts:
        return 0.0
    key = float(key)
    if key <= pts[0][0]:
        return pts[0][1] * key / pts[0][0] if pts[0][0] else 0.0
    if key >= pts[-1][0]:
        return pts[-1][1] * key / pts[-1][0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= key <= x1:
            t = (key - x0) / (x1 - x0) if x1 != x0 else 0.0
            return y0 + (y1 - y0) * t
    return pts[-1][1]


class Odometry:
    """명령을 적분해 (x, y, heading) 을 유지한다.

    heading 은 도 단위, 0 = +x 방향, 반시계가 양수(수학 관례). 로봇의 turn 은
    오른쪽이 양수이므로 부호를 뒤집어 더한다.
    """

    def __init__(self, model=None):
        self.model = model or load_model()
        self._lock = threading.Lock()
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0
        self.path = [(0.0, 0.0)]      # 지나온 자취. 웹에 그려주려고 남긴다.
        self._last_fix = None

    # ---------- 조회 ----------

    def pose(self):
        with self._lock:
            return {"x_cm": round(self.x, 1), "y_cm": round(self.y, 1),
                    "heading_deg": round(self.heading % 360.0, 1),
                    "last_fix": self._last_fix}

    def reset(self, x=0.0, y=0.0, heading=0.0, note="reset"):
        with self._lock:
            self.x, self.y, self.heading = float(x), float(y), float(heading)
            self.path = [(self.x, self.y)]
            self._last_fix = {"at": time.strftime("%H:%M:%S"), "how": note}

    # ---------- 예측 ----------

    # 명령을 줘도 바로 안 움직인다. 정지마찰을 이기고 모터가 붙을 때까지 걸리는
    # 시간이 있다. 이걸 빼먹으면 짧은 명령은 아무 것도 안 하는데 모델은 움직였다고
    # 믿고, 긴 명령은 실제보다 훨씬 더 간다. 실측:
    #     회전 1.82초 -> 약 100도,  2.34초 -> 약 180도
    #     0.52초 늘었는데 80도가 늘었다 -> 초당 154도이고, 앞의 1.17초는 버려진다
    # 단순 비례로 계산하면 짧은 회전은 과대평가, 긴 회전은 과소평가된다.

    def _deadtime(self, kind):
        return float(self.model.get(f"{kind}_deadtime_s", 0.0))

    def cm_for(self, speed, seconds):
        """속도 speed 로 seconds 초 가면 몇 cm 인가."""
        if abs(speed) < self.model.get("min_move_speed", 40):
            return 0.0
        effective = max(0.0, seconds - self._deadtime("forward"))
        sign = 1.0 if speed > 0 else -1.0
        return sign * _interp(self.model["forward_cm_per_s"], abs(speed)) * effective

    def deg_for(self, turn, seconds):
        """회전 turn 으로 seconds 초 돌면 몇 도인가. 오른쪽이 양수."""
        if abs(turn) < self.model.get("min_turn", 55):
            return 0.0
        effective = max(0.0, seconds - self._deadtime("turn"))
        sign = 1.0 if turn > 0 else -1.0
        return sign * _interp(self.model["turn_deg_per_s"], abs(turn)) * effective

    def seconds_for_cm(self, cm, speed):
        """cm 만큼 가려면 몇 초를 줘야 하나. 출발 지연을 얹어준다."""
        rate = _interp(self.model["forward_cm_per_s"], abs(speed))
        if rate <= 0.1:
            return 0.0
        return self._deadtime("forward") + abs(cm) / rate

    def seconds_for_deg(self, deg, turn):
        rate = _interp(self.model["turn_deg_per_s"], abs(turn))
        if rate <= 0.1:
            return 0.0
        return self._deadtime("turn") + abs(deg) / rate

    # ---------- 적분 ----------

    def apply(self, speed, turn, seconds):
        """이 명령을 이만큼 줬다고 치고 좌표를 옮긴다.

        회전과 직진이 섞이면 원호를 그리지만, 여기서는 구간을 짧게 끊어 부르므로
        '먼저 반만 돌고, 직진하고, 나머지 반을 돈다'로 근사한다. 0.2초짜리 구간에서
        이 근사의 오차는 무시할 수준이다.
        """
        d = self.cm_for(speed, seconds)
        turned = self.deg_for(turn, seconds)
        with self._lock:
            # turn 오른쪽(양수) = 수학 좌표계에서 시계방향 = heading 감소
            self.heading -= turned / 2.0
            if d:
                rad = math.radians(self.heading)
                self.x += d * math.cos(rad)
                self.y += d * math.sin(rad)
                self.path.append((round(self.x, 1), round(self.y, 1)))
                if len(self.path) > 2000:
                    del self.path[:1000]
            self.heading -= turned / 2.0
        return d, turned

    # ---------- 마커로 보정 ----------

    def reset_from_marker(self, marker_xy, distance_cm, bearing_deg):
        """마커 관측으로 위치를 덮어쓴다. 쓰지 말 것 — 아래 경고 참고.

        !! 2026-08-31 실측에서 순찰을 망가뜨렸다. 로봇 위치가 164cm 튀었고
        그 뒤로 엉뚱한 방향으로 달렸다. 아래 계산이 heading 에 의존하는데,
        heading 이 틀어져 있으면 그 오차가 거리에 비례해 위치 오차로 바뀌기
        때문이다. 마커가 멀수록 더 크게 튄다.

        대신 patrol._fix_heading_from_markers 를 쓴다. 그쪽은 heading 만
        고치고 위치는 건드리지 않아서, 위치 오차에 둔감하다.


        마커가 (mx, my) 에 있고 지금 그게 거리 d, 몸통기준 방향 b 로 보인다면
        로봇은 마커에서 정반대 방향으로 d 만큼 떨어진 곳에 있다.

            마커를 보는 절대 방향 = heading - b        (b 는 오른쪽이 양수)
            로봇 위치 = 마커 위치 - d x (그 방향 단위벡터)

        heading 자체는 못 고친다(마커 하나로는 방향을 확정할 수 없다). 위치만
        고쳐도 적분 오차의 대부분이 사라진다.
        """
        with self._lock:
            look = math.radians(self.heading - float(bearing_deg))
            self.x = float(marker_xy[0]) - float(distance_cm) * math.cos(look)
            self.y = float(marker_xy[1]) - float(distance_cm) * math.sin(look)
            self.path.append((round(self.x, 1), round(self.y, 1)))
            self._last_fix = {"at": time.strftime("%H:%M:%S"), "how": "marker",
                              "distance_cm": round(float(distance_cm), 1)}
        return self.pose()

    # ---------- 목표까지 ----------

    def vector_to(self, x, y):
        """목표까지 (거리cm, 돌아야 할 각도). 각도는 오른쪽이 양수."""
        with self._lock:
            dx, dy = float(x) - self.x, float(y) - self.y
            want = math.degrees(math.atan2(dy, dx))
            # -180~180 으로 접는다. 350도 돌지 말고 -10도 돌게.
            delta = (self.heading - want + 180.0) % 360.0 - 180.0
        return math.hypot(dx, dy), delta
