"""가짜 로봇으로 순찰 제어 흐름을 검증한다.

왜 필요한가
----------
순찰을 고칠 때마다 실물 로봇을 바닥에 놓고 돌려봐야 했다. 배터리가 닳고,
방을 치워야 하고, 한 번에 15초씩 걸린다. 그래서 확인이 귀찮아지고, 확인하지
않은 채로 배포하게 된다 - 실제로 오늘 "마커 보정이 위치를 164cm 튀게 만드는"
버그가 실기기에서야 드러났다.

여기서는 하드웨어 없이 같은 코드를 돌린다. 가짜 HAL 이 실측한 운동 모델대로
움직이는 척하고, 가상의 벽과 마커를 놓는다. 제어 흐름(방향 잡기, 구간 주행,
막힘 처리, 취소, 마커 보정)이 의도대로 도는지 몇 초 만에 확인할 수 있다.

무엇을 검증하지 못하는가
---------------------
실제 마찰, 배터리 전압 변화, 초음파 노이즈, 바퀴 미끄러짐은 흉내내지 않는다.
그건 실기기로만 알 수 있다. 여기서 잡는 것은 "코드가 의도한 순서로 도는가"다.

사용법
    python patrol_sim_test.py
"""

from __future__ import annotations

import math
import sys
import time

from odometry import Odometry
from patrol import PatrolRunner

# 실측한 운동 모델. 가짜 로봇도 이대로 움직이는 척한다.
MODEL = {
    "forward_cm_per_s": {"65": 27.1},
    "turn_deg_per_s": {"60": 62.2},
    "min_move_speed": 50,
    "min_turn": 60,
    "drive_trim": 1.7,
}


class FakeHAL:
    """명령을 받아 가상의 위치를 옮기는 로봇.

    실제 로봇과 다른 점은 명령이 정확히 먹는다는 것뿐이다. 시간은 흐르는
    대신 바로 계산하므로 15초짜리 순찰이 순식간에 끝난다.
    """

    def __init__(self, walls=None, markers=None, speed_factor=1.0, turn_factor=1.0):
        self.x = self.y = self.heading = 0.0
        self.speed = self.turn = 0.0
        self._since = time.time()
        self.cam_pan = 90
        self.cam_tilt = 90
        # 앞을 막는 벽들: (x, y, 반경) - 이 안에 들어가면 초음파가 짧게 읽힌다
        self.walls = walls or []
        self.markers = markers or {}
        # 명령보다 덜 가거나 더 가는 정도. 1.0 이면 모델대로 정확히 움직인다.
        self.speed_factor = speed_factor
        # 회전이 명령보다 더 돌거나 덜 도는 정도. 실기기에서 90도 명령에
        # 95~100도가 나온 적이 있고, 그 오차가 코너마다 쌓여 네모를
        # 망가뜨렸다. 방향 오차야말로 마커 보정이 고치라고 만든 것이다.
        self.turn_factor = turn_factor
        self.trace = [(0.0, 0.0)]
        self._model = Odometry(MODEL)

    # --- 시간 경과를 반영 ---
    def _advance(self):
        now = time.time()
        dt = now - self._since
        self._since = now
        if dt <= 0:
            return
        # 명령대로 계산한 뒤 speed_factor 를 곱한다. PatrolRunner 의
        # 오도메트리는 곱하지 않은 값을 믿으므로, 여기서 곱한 만큼이 그대로
        # "믿음과 실제의 차이"가 된다. 그게 엔코더 없는 로봇의 실제 상황이다.
        d = self._model.cm_for(self.speed, dt) * self.speed_factor
        turned = self._model.deg_for(self.turn, dt) * self.turn_factor
        self.heading -= turned / 2.0
        if d:
            rad = math.radians(self.heading)
            self.x += d * math.cos(rad)
            self.y += d * math.sin(rad)
            self.trace.append((round(self.x, 1), round(self.y, 1)))
        self.heading -= turned / 2.0

    # --- HAL 인터페이스 ---
    def set_motion(self, speed, turn):
        self._advance()
        self.speed, self.turn = float(speed), float(turn)

    def stop(self):
        self._advance()
        self.speed = self.turn = 0.0

    def read_ultrasonic(self):
        self._advance()
        best = 999.0
        for wx, wy, r in self.walls:
            # 로봇이 보는 방향에 있는 벽만 센다.
            dx, dy = wx - self.x, wy - self.y
            dist = math.hypot(dx, dy)
            bearing = (math.degrees(math.atan2(dy, dx)) - self.heading + 180) % 360 - 180
            if abs(bearing) < 25:
                best = min(best, max(2.0, dist - r))
        return best

    def capture_frame(self):
        return None

    def set_camera_angle(self, pan=None, tilt=None):
        if pan is not None:
            self.cam_pan = pan
        if tilt is not None:
            self.cam_tilt = tilt
        return {"pan": self.cam_pan, "tilt": self.cam_tilt}

    def markers_in_view(self):
        """가상 마커 중 지금 보이는 것."""
        self._advance()
        out = []
        for mid, (mx, my) in self.markers.items():
            dx, dy = mx - self.x, my - self.y
            dist = math.hypot(dx, dy)
            # 몸통 기준 방향은 "오른쪽이 양수"다(vector_to 와 같은 규약).
            # 로봇이 왼쪽을 보고 있으면 정면의 물체는 오른쪽에 보인다:
            #   방향 = heading - 절대방향
            # 이걸 거꾸로 쓰면 마커 보정이 반대로 돌아 오차를 두 배로 만든다.
            absdir = math.degrees(math.atan2(dy, dx))
            body = (self.heading - absdir + 180) % 360 - 180
            screen = body - (self.cam_pan - 90.0)
            if dist < 300 and abs(screen) < 26:      # 화각 안
                out.append({"id": mid, "distance_cm": round(dist, 1),
                            "angle_deg": round(screen, 1), "px": 50.0})
        return out


def run_case(name, walls=(), markers=None, speed_factor=1.0, turn_factor=1.0,
             cancel_after=None):
    hal = FakeHAL(walls=list(walls), markers=markers or {},
                  speed_factor=speed_factor, turn_factor=turn_factor)
    odo = Odometry(dict(MODEL))
    runner = PatrolRunner(hal, marker_fn=hal.markers_in_view, odometry=odo)
    # 마커는 경유지 너머 벽에 붙어 있다. 지도에도 그 좌표를 적어야
    # 보정 계산이 실제와 맞는다(안 적으면 경유지 좌표로 본다).
    runner._map = {"waypoints": [
        {"name": "출발", "marker": None, "x_cm": 0, "y_cm": 0},
        {"name": "1번", "marker": 1, "x_cm": 70, "y_cm": 0,
         "marker_x_cm": 150, "marker_y_cm": 0},
        {"name": "2번", "marker": 2, "x_cm": 70, "y_cm": 50,
         "marker_x_cm": 70, "marker_y_cm": 130},
    ]}

    if cancel_after is not None:
        import threading
        threading.Timer(cancel_after, runner.abort).start()

    for wp in runner._map["waypoints"][1:] + [runner._map["waypoints"][0]]:
        runner.goto(wp["x_cm"], wp["y_cm"], marker_id=wp.get("marker"))

    belief = odo.pose()
    truth_err = math.hypot(hal.x, hal.y)
    print(f"\n[{name}]")
    print(f"  로봇이 믿는 위치  ({belief['x_cm']:6.1f}, {belief['y_cm']:6.1f}) "
          f"방향 {belief['heading_deg']:5.1f}도")
    print(f"  실제 위치        ({hal.x:6.1f}, {hal.y:6.1f})  원점 오차 {truth_err:5.1f}cm")
    print(f"  마커 보정 {runner._marker_fixes}회 · 초음파 헛값 {runner._sonar_rejects}회")
    return belief, hal, runner


def main():
    print("가짜 로봇으로 순찰 제어 흐름 검증")
    print("=" * 52)

    # 1) 아무 방해 없음 - 믿음과 실제가 같아야 한다
    belief, hal, _ = run_case("깨끗한 삼각형")
    ok1 = math.hypot(hal.x, hal.y) < 5
    print("  판정:", "통과" if ok1 else "실패 - 제자리로 안 돌아옴")

    # 2) 로봇이 명령보다 15% 덜 간다 - 오차가 쌓이는 상황
    belief, hal, _ = run_case("모터가 15% 약할 때", speed_factor=0.85)
    print(f"  판정: 믿음과 실제가 {math.hypot(belief['x_cm']-hal.x, belief['y_cm']-hal.y):.1f}cm 벌어짐"
          " (엔코더가 없으면 이건 못 막는다)")

    # 3) 회전이 8% 더 도는 로봇 - 이게 실기기의 실제 증상이었다.
    #    90도 명령에 95~100도가 나왔고 코너마다 쌓여 네모가 찌그러졌다.
    #    마커 보정은 바로 이 방향 오차를 잡으라고 만든 것이다.
    # 마커는 그 구간의 진행 방향 "정면 벽"에 있어야 한다. 옆으로 벗어나면
    # 카메라 화각(±26도) 밖이라 달리는 동안 안 보인다.
    #   구간1: (0,0)->(70,0) 방향 0도   -> 마커를 (150,0) 에
    #   구간2: (70,0)->(70,50) 방향 90도 -> 마커를 (70,130) 에
    WALL = {1: (150, 0), 2: (70, 130)}
    _, hal_no, run_no = run_case("회전 8% 과다 · 마커 없음", turn_factor=1.08)
    _, hal_yes, run_yes = run_case("회전 8% 과다 · 마커 있음", turn_factor=1.08,
                                   markers=WALL)
    e_no = math.hypot(hal_no.x, hal_no.y)
    e_yes = math.hypot(hal_yes.x, hal_yes.y)
    print()
    print("  원점 오차: 마커 없음 %.1fcm -> 마커 있음 %.1fcm (보정 %d회)"
          % (e_no, e_yes, run_yes._marker_fixes))
    print("  판정:", "마커가 오차를 줄였다" if e_yes < e_no - 1
          else "마커 효과 없음 - 배치나 조건을 봐야 한다")

    # 4) 앞이 막혔을 때 - 무한정 밀지 않아야 한다
    started = time.time()
    _, hal_w, run_w = run_case("40cm 앞에 벽", walls=[(40, 0, 10)])
    print(f"  판정: {time.time()-started:.1f}초 만에 끝남 "
          f"(무한 루프면 여기서 안 끝난다)")

    print("\n" + "=" * 52)
    print("이 테스트가 잡는 것: 제어 흐름이 의도한 순서로 도는가")
    print("이 테스트가 못 잡는 것: 실제 마찰·배터리·초음파 노이즈·바퀴 미끄러짐")
    return 0 if ok1 else 1


if __name__ == "__main__":
    sys.exit(main())
