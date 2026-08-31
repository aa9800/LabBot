"""로봇이 스스로 "이 명령이 얼마나 움직이는지"를 잰다.

왜 로봇이 직접 재는가
-------------------
사람이 줄자로 재면 정확하지만 속도마다·회전값마다 다 재야 해서 수십 번을 반복해야
한다. 로봇에는 이미 두 개의 자가 달려 있다.

  직진 : 초음파. 앞의 벽까지 거리가 줄어든 만큼이 간 거리다.
  회전 : 카메라. 돌면 화면이 옆으로 흐르고, 흐른 픽셀을 각도로 바꾸면 돈 각도다.

        각도 = atan(흐른 픽셀 / 초점거리)

화면 흐름은 cv2.phaseCorrelate 로 잰다. 두 이미지를 주파수 영역에서 비교해 몇
픽셀 어긋났는지를 한 번에 내놓는다. 특징점을 찾을 필요가 없어서 벽지처럼 밋밋한
장면에서도 동작한다.

주의
----
- 앞에 벽이 있어야 한다(60~200cm). 없으면 직진 측정이 안 된다.
- 측정 중 로봇 앞을 지나가면 안 된다. 초음파와 화면이 둘 다 오염된다.
- 잰 뒤에는 왔던 만큼 되돌아가므로 제자리 근처에서 끝난다.
"""

from __future__ import annotations

import math
import statistics
import time

import cv2
import numpy as np

FOCAL_PX = 634.9      # ov5647 640px 폭 기준. marker_locator 와 같은 값.

FORWARD_SPEEDS = (50, 65, 85)
FORWARD_PULSE_S = 0.8
TURN_VALUES = (60, 75, 90)
TURN_TRACK_S = 1.2    # 이만큼 계속 돌면서 프레임마다 누적한다

SAFE_MIN_CM = 30.0    # 이보다 가까우면 직진 측정을 멈춘다


def _distance(hal, n=5):
    """초음파를 여러 번 읽어 중앙값. 한 번 읽으면 튀는 값이 섞인다."""
    vals = []
    for _ in range(n):
        d = hal.read_ultrasonic()
        if d and 2 < d < 400:
            vals.append(d)
        time.sleep(0.05)
    return statistics.median(vals) if vals else None


def _gray(hal):
    frame = hal.capture_frame()
    if frame is None:
        return None
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return g.astype(np.float32)


def _shift_px(before, after):
    """두 화면이 가로로 몇 픽셀 어긋났나. 신뢰도가 낮으면 None."""
    if before is None or after is None or before.shape != after.shape:
        return None
    (dx, _dy), response = cv2.phaseCorrelate(before, after)
    if response < 0.05:
        return None
    return dx


def _marker_distance(marker_fn, marker_id, n=5):
    """마커까지 거리를 여러 번 재서 중앙값. 초음파보다 정확하다(1m 에서 ±0.5cm)."""
    vals = []
    for _ in range(n):
        for m in marker_fn() or []:
            if m["id"] == marker_id:
                vals.append(m["distance_cm"])
                break
        time.sleep(0.05)
    return statistics.median(vals) if len(vals) >= 3 else None


def measure_forward_by_marker(hal, marker_fn, log=print):
    """마커를 자로 삼아 속도별 cm/s 를 잰다.

    앞에 벽이 없어도 되고, 마커 거리는 초음파보다 정확하다. 뒤로 물러나며 재는
    이유는 마커가 코앞에 있을 때도 쓸 수 있어야 하기 때문이다 - 앞으로 가면
    마커에 부딪히거나 화면 밖으로 나간다.
    """
    seen = marker_fn() or []
    if not seen and hasattr(hal, "set_camera_angle"):
        # 카메라가 바닥을 보고 있으면 코앞의 마커도 못 본다. 훑어서 찾는다.
        for tilt in (85, 75, 95, 65):
            hal.set_camera_angle(pan=90, tilt=tilt)
            time.sleep(0.8)
            seen = marker_fn() or []
            if seen:
                log(f"  카메라 tilt {tilt} 에서 마커를 찾았다")
                break
    if not seen:
        return {}
    marker_id = seen[0]["id"]
    log(f"  마커 {marker_id} 을(를) 자로 쓴다")

    table = {}
    for speed in FORWARD_SPEEDS:
        before = _marker_distance(marker_fn, marker_id)
        if before is None:
            log(f"  속도 {speed}: 마커를 놓쳤다 — 건너뜀")
            continue

        hal.set_motion(-speed, 0)            # 뒤로 물러난다
        time.sleep(FORWARD_PULSE_S)
        hal.stop()
        time.sleep(0.7)
        after = _marker_distance(marker_fn, marker_id)

        hal.set_motion(speed, 0)             # 원래 자리로
        time.sleep(FORWARD_PULSE_S)
        hal.stop()
        time.sleep(0.7)

        if after is None:
            log(f"  속도 {speed}: 물러난 뒤 마커를 놓쳤다 — 건너뜀")
            continue
        moved = after - before               # 물러났으니 거리가 늘어난다
        if moved <= 1.0:
            log(f"  속도 {speed}: 움직임 없음({moved:.1f}cm) — 건너뜀")
            continue
        rate = moved / FORWARD_PULSE_S
        table[str(speed)] = round(rate, 1)
        log(f"  속도 {speed}: {before:.1f} -> {after:.1f}cm · {moved:.1f}cm / "
            f"{FORWARD_PULSE_S}s = {rate:.1f} cm/s")
    return table


def measure_forward(hal, log=print):
    """속도별로 초당 몇 cm 가는지 잰다. 앞의 벽까지 거리 변화로 잰다."""
    table = {}
    for speed in FORWARD_SPEEDS:
        before = _distance(hal)
        if before is None:
            log(f"  속도 {speed}: 초음파를 못 읽어 건너뜀")
            continue
        if before < SAFE_MIN_CM + 25:
            log(f"  속도 {speed}: 앞이 {before:.0f}cm 뿐이라 위험 — 중단")
            break

        hal.set_motion(speed, 0)
        time.sleep(FORWARD_PULSE_S)
        hal.stop()
        time.sleep(0.6)                 # 관성이 멎을 때까지
        after = _distance(hal)

        # 되돌아간다. 같은 속도·시간이면 대칭이므로 제자리 근처로 온다.
        hal.set_motion(-speed, 0)
        time.sleep(FORWARD_PULSE_S)
        hal.stop()
        time.sleep(0.6)

        if after is None:
            log(f"  속도 {speed}: 측정 후 초음파를 못 읽어 건너뜀")
            continue
        moved = before - after
        if moved <= 1.0:
            log(f"  속도 {speed}: 움직임이 없다({moved:.1f}cm) — 건너뜀")
            continue
        rate = moved / FORWARD_PULSE_S
        table[str(speed)] = round(rate, 1)
        log(f"  속도 {speed}: {before:.1f} -> {after:.1f}cm · {moved:.1f}cm / "
            f"{FORWARD_PULSE_S}s = {rate:.1f} cm/s")
    return table


def _track_turn(hal, turn, seconds, log=print, detail=False):
    """도는 동안 계속 촬영해 프레임 사이 흐름을 누적한다. (총 각도, 실제 시간).

    한 번 돌고 전후를 비교하는 방식은 틀린다. 30도를 돌면 화면이 3분의 1이나
    흘러서 위상상관이 엉뚱한 봉우리를 잡는다. 대신 20분의 1초마다 찍어 프레임
    사이 1~2도씩을 재고 더한다. 각 조각은 작아서 확실히 맞고, 합은 정확하다.

    부수 효과로 정지마찰까지 그대로 담긴다 - 처음 0.1초는 안 돌고 그 뒤부터
    도는데, 그 손해가 총합에 반영된다.
    """
    prev = _gray(hal)
    hal.set_motion(0, turn)
    started = time.time()
    total_deg = 0.0
    misses = 0
    frames = 0
    while time.time() - started < seconds:
        frames += 1
        # 카메라가 30fps 이므로 이보다 빨리 찍으면 같은 프레임을 두 번 받는다.
        # 같은 프레임은 "안 움직였다"로 읽혀서 회전을 실제보다 적게 세게 된다.
        time.sleep(0.08)
        cur = _gray(hal)
        dx = _shift_px(prev, cur)
        if dx is None:
            misses += 1
        else:
            total_deg += abs(math.degrees(math.atan2(abs(dx), FOCAL_PX)))
        prev = cur
    hal.stop()
    elapsed = time.time() - started
    time.sleep(0.6)
    if misses:
        log(f"    (화면을 못 읽은 프레임 {misses}/{frames}개 — 무늬 없는 벽이면 늘어난다)")
    if detail:
        return total_deg, elapsed, misses, frames
    return total_deg, elapsed


def measure_turn(hal, log=print):
    """회전값별로 초당 몇 도 도는지 잰다. 도는 동안의 화면 흐름을 누적해 잰다."""
    table = {}
    for turn in TURN_VALUES:
        samples = []
        for direction in (1, -1):       # 좌우 둘 다 재서 평균낸다. 돌고 되돌아온다.
            deg, elapsed = _track_turn(hal, turn * direction, TURN_TRACK_S, log)
            if deg > 3.0:               # 이 이하는 아예 안 돈 것이다
                samples.append(deg / elapsed)
                log(f"    회전 {turn} {'오른쪽' if direction > 0 else '왼쪽'}: "
                    f"{deg:.1f}도 / {elapsed:.2f}s = {deg / elapsed:.1f} 도/s")
        if not samples:
            log(f"  회전 {turn}: 움직임을 못 읽어 건너뜀")
            continue
        rate = sum(samples) / len(samples)
        table[str(turn)] = round(rate, 1)
        log(f"  회전 {turn}: {rate:.1f} 도/s")
    return table


def run(hal, marker_fn=None, log=print):
    """전체 측정. 결과 dict 를 돌려준다(저장은 부르는 쪽에서).

    마커가 보이면 그걸 자로 쓴다(더 정확하고 벽이 필요없다). 없으면 초음파로
    앞의 벽까지 거리 변화를 본다.
    """
    forward = {}
    how = "초음파"
    if marker_fn is not None:
        log("직진 측정 — 마커를 자로 쓴다")
        forward = measure_forward_by_marker(hal, marker_fn, log)
        if forward:
            how = "마커"
    if not forward:
        log("직진 측정 — 앞의 벽까지 거리 변화로 잰다")
        forward = measure_forward(hal, log)
    log("회전 측정 — 화면이 흐른 픽셀로 잰다")
    turn = measure_turn(hal, log)
    hal.stop()

    result = {
        "forward_cm_per_s": forward,
        "turn_deg_per_s": turn,
        "min_move_speed": min((int(k) for k in forward), default=40),
        "min_turn": min((int(k) for k in turn), default=55),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": f"{how}(직진)·카메라 위상상관(회전)으로 로봇이 직접 측정",
    }
    if not forward:
        result["warning"] = "직진을 못 쟀다 — 마커가 보이거나 앞에 60cm 이상 공간이 필요하다"
    return result


# ---------------------------------------------------------------------------
# 검증과 보정
# ---------------------------------------------------------------------------
# 위의 측정은 0.8초짜리 짧은 이동으로 재기 때문에 오차가 5~8% 다. 250cm 를 가면
# 20cm 가 틀어지고, 그 차이로 벽에 박는다.
#
# 여기서는 반대로 간다. 이미 있는 모델을 믿고 "100cm 만큼" 달리게 시킨 뒤, 실제로
# 몇 cm 갔는지를 재서 모델을 그 비율만큼 고친다. 한 번 돌리면 오차가 크게 준다.
#
#     실제 간 거리가 130cm 였다면 -> 모델이 30% 느리게 알고 있었다 -> 표를 1.3배
#
# 회전도 똑같다. "360도" 를 돌게 시키고 실제로 몇 도 돌았는지 누적해서 잰다.

VERIFY_CM = 100.0
VERIFY_DEG = 360.0


def _ruler(hal, marker_fn):
    """지금 쓸 수 있는 자를 고른다. (읽는 함수, 이름, 뒤로 갈 때 늘어나는가)."""
    if marker_fn is not None:
        seen = marker_fn() or []
        if seen:
            mid = seen[0]["id"]
            if _marker_distance(marker_fn, mid) is not None:
                return (lambda: _marker_distance(marker_fn, mid)), f"마커 {mid}", True
    # 초음파로 1m 이동을 재는 건 못 믿는다 - 먼 거리에서 정확도가 떨어지고
    # 뒤에 뭐가 걸려도 알 수가 없다. 실제로 100cm 를 37.9cm 로 읽어 모델을
    # 망가뜨린 적이 있다. 마커가 없으면 검증을 포기하는 쪽이 낫다.
    return None, None, None


def verify_forward(hal, model, marker_fn=None, log=print):
    """모델이 믿는 100cm 를 실제로 가보고 배율을 돌려준다."""
    read, name, _ = _ruler(hal, marker_fn)
    if read is None:
        log("  직진 검증: 잴 기준이 없다(마커도 벽도 안 보임) — 건너뜀")
        return None
    speed = 65 if "65" in model["forward_cm_per_s"] else         int(sorted(model["forward_cm_per_s"], key=lambda k: -float(k))[0])
    rate = float(model["forward_cm_per_s"][str(speed)])
    seconds = VERIFY_CM / rate

    before = read()
    if before is None:
        return None
    # 뒤로 간다. 앞으로 가면 벽이나 마커에 부딪힌다.
    hal.set_motion(-speed, 0)
    time.sleep(seconds)
    hal.stop()
    time.sleep(0.8)
    after = read()

    hal.set_motion(speed, 0)          # 원래 자리로
    time.sleep(seconds)
    hal.stop()
    time.sleep(0.8)

    if after is None:
        log(f"  직진 검증: {name} 을(를) 놓쳤다 — 건너뜀")
        return None
    actual = after - before
    if actual < 10:
        log(f"  직진 검증: 움직임이 이상하다({actual:.1f}cm) — 건너뜀")
        return None
    scale = actual / VERIFY_CM
    log(f"  직진 검증({name}): {VERIFY_CM:.0f}cm 명령 -> 실제 {actual:.1f}cm "
        f"· 배율 {scale:.3f}")
    return scale


def verify_turn(hal, model, log=print):
    """모델이 믿는 360도를 실제로 돌아보고 배율을 돌려준다."""
    turn = 60 if "60" in model["turn_deg_per_s"] else         int(sorted(model["turn_deg_per_s"])[0])
    rate = float(model["turn_deg_per_s"][str(turn)])
    seconds = VERIFY_DEG / rate
    if seconds > 20:
        log("  회전 검증: 모델이 너무 느리다고 알고 있다 — 건너뜀")
        return None

    actual, elapsed, misses, frames = _track_turn(hal, turn, seconds, log, detail=True)
    if frames and misses > frames * 0.15:
        # 무늬 없는 벽을 보고 있으면 화면 흐름을 못 읽는다. 그때 나온 숫자는
        # 실제보다 한참 작게 나오는데, 그걸 믿고 모델을 고치면 크게 망가진다.
        log(f"  회전 검증: 화면을 {misses}/{frames} 프레임 못 읽었다 — 믿을 수 없어 건너뜀")
        _track_turn(hal, -turn, elapsed, log)
        return None
    if actual < 30:
        log(f"  회전 검증: 움직임이 이상하다({actual:.1f}도) — 건너뜀")
        return None
    _track_turn(hal, -turn, elapsed, log)      # 되돌아온다
    scale = actual / VERIFY_DEG
    log(f"  회전 검증: {VERIFY_DEG:.0f}도 명령 -> 실제 {actual:.0f}도 · 배율 {scale:.3f}")
    return scale


def refine(hal, model, marker_fn=None, log=print):
    """모델을 실제 주행 결과로 고친다. 고쳐진 모델을 돌려준다."""
    model = dict(model)
    log("직진 검증 — 모델이 믿는 100cm 를 실제로 가본다")
    fs = verify_forward(hal, model, marker_fn, log)
    if fs and 0.3 < fs < 3.0:
        model["forward_cm_per_s"] = {k: round(v * fs, 1)
                                     for k, v in model["forward_cm_per_s"].items()}
    log("회전 검증 — 모델이 믿는 360도를 실제로 돌아본다")
    ts = verify_turn(hal, model, log)
    if ts and 0.3 < ts < 3.0:
        model["turn_deg_per_s"] = {k: round(v * ts, 1)
                                   for k, v in model["turn_deg_per_s"].items()}
    hal.stop()
    model["refined_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    model["refine_scale"] = {"forward": round(fs, 3) if fs else None,
                             "turn": round(ts, 3) if ts else None}
    return model


# ---------------------------------------------------------------------------
# 직진 정렬(trim)
# ---------------------------------------------------------------------------
# 모터 두 개가 완전히 같을 수 없어서 직진 명령에도 한쪽으로 휜다. 이 로봇은
# 네 바퀴가 다 고정이라 자동차 같은 조향 정렬은 없고, 소프트웨어로 상쇄한다.
#
# 얼마나 휘는지는 카메라로 잰다. 똑바로 가면 화면은 앞으로만 다가오지 옆으로
# 흐르지 않는다. 왼쪽으로 휘면 화면이 오른쪽으로 흐른다. 그 흐름을 각도로 바꾸면
# 초당 몇 도씩 휘는지가 나오고, 그만큼을 회전 명령으로 되돌리면 된다.

AUTOTRIM_SPEED = 65
# 길게 달릴수록 정확하다. 1.6초(43cm)에서는 0.3도/s 를 재려면 5픽셀을 읽어야
# 해서 노이즈에 묻힌다. 3초(81cm)면 10픽셀이라 확실히 구분된다.
AUTOTRIM_S = 3.0
AUTOTRIM_ROUNDS = 3
AUTOTRIM_MIN_CLEAR_CM = 95.0   # 3초에 81cm 가고 정지 여유 10cm


def _drift_deg_per_s(hal, speed, trim, seconds, log=print):
    """앞으로 가면서 초당 몇 도씩 휘는지 잰다. 오른쪽으로 휘면 양수.

    안 움직였으면 None 을 돌려준다. 이게 중요하다 - 멈춰 있으면 휘지도 않으니
    "완벽하게 곧다"로 읽히고, 그대로 통과시키면 정렬이 안 된 채로 끝난다.
    """
    moved_from = _distance(hal, n=3)
    prev = _gray(hal)
    hal.set_motion(speed, trim)
    started = time.time()
    total = 0.0
    frames = misses = 0
    while time.time() - started < seconds:
        time.sleep(0.08)
        frames += 1
        cur = _gray(hal)
        dx = _shift_px(prev, cur)
        if dx is None:
            misses += 1
        else:
            # 화면이 오른쪽으로 흐르면(+dx) 로봇은 왼쪽으로 돈 것이다.
            total -= math.degrees(math.atan2(dx, FOCAL_PX))
        prev = cur
    hal.stop()
    elapsed = time.time() - started
    time.sleep(0.7)
    if frames and misses > frames * 0.2:
        log(f"    화면을 {misses}/{frames} 프레임 못 읽었다 — 무늬가 있는 쪽을 보게 하세요")
        return None
    moved_to = _distance(hal, n=3)
    if moved_from and moved_to and abs(moved_from - moved_to) < 8:
        log(f"    거의 안 움직였다({moved_from:.0f}->{moved_to:.0f}cm) — 측정 무효")
        return None
    return total / elapsed


def autotrim(hal, model, log=print):
    """직진 보정값을 스스로 찾아보려는 시도. 결과를 자동으로 적용하지 않는다.

    믿을 수 없는 이유(2026-08-31 실측)
    --------------------------------
    앞으로 갈 때 화면은 옆으로 흐르지 않고 확대된다. 위상상관은 그 확대를
    "옆으로 밀림"으로 잘못 읽고, 화면 한쪽에 무늬가 더 많으면 그쪽으로 치우친
    값을 낸다. 실제로 trim 을 0.7 -> 2.1 로 세 배 올렸는데 측정값이 -1.12 에서
    -1.10 으로 거의 그대로였다. 보정이 듣지 않은 게 아니라, 실제 회전이 아니라
    전진이 만든 착시를 재고 있었던 것이다.

    회전 측정(_track_turn)은 화면이 진짜로 옆으로 흐르므로 이 문제가 없다.

    직진 휨은 줄자로 재는 게 확실하다:
        /patrol/testdrive?cm=190  으로 달리게 하고, 옆으로 벗어난 거리를 재서
        /patrol/trim_from_offset?left_cm=<벗어난cm>&over_cm=190 으로 넣는다.
    """
    clear = _distance(hal)
    if clear is not None and 2 < clear < AUTOTRIM_MIN_CLEAR_CM:
        return {"error": f"앞이 {clear:.0f}cm 뿐이다. {AUTOTRIM_MIN_CLEAR_CM:.0f}cm 이상 필요"}

    # 회전 명령 1 단위가 초당 몇 도인지. 이걸 알아야 휜 만큼을 되돌릴 수 있다.
    turn_ref = float(sorted(model["turn_deg_per_s"])[0])
    deg_per_unit = float(model["turn_deg_per_s"][str(int(turn_ref))]) / turn_ref

    trim = float(model.get("drive_trim", 0.0))
    history = []
    for rnd in range(AUTOTRIM_ROUNDS):
        drift = _drift_deg_per_s(hal, AUTOTRIM_SPEED, trim, AUTOTRIM_S, log)
        # 왔던 만큼 되돌아온다. 같은 자리에서 반복해야 공간이 안 모자란다.
        hal.set_motion(-AUTOTRIM_SPEED, -trim)
        time.sleep(AUTOTRIM_S)
        hal.stop()
        time.sleep(0.7)

        if drift is None:
            return {"error": "화면 흐름을 못 읽었다 — 무늬가 있는 쪽을 보게 하세요",
                    "drive_trim": trim}
        history.append({"round": rnd + 1, "trim": round(trim, 1),
                        "drift_deg_per_s": round(drift, 2)})
        log(f"  {rnd + 1}회차: trim {trim:+.1f} 에서 "
            f"{drift:+.2f} 도/s ({'오른쪽' if drift > 0 else '왼쪽'}으로 휨)")
        # 250cm 를 가는 데 9.2초 걸린다. 1.5 도/s 를 통과시키면 그 사이 13도가
        # 틀어져 한참 옆으로 벗어난다. 0.3 도/s 면 3도 이내로 들어온다.
        # 190cm 를 가는 데 7초 걸린다. 0.2 도/s 면 그 사이 1.4도가 틀어지고
        # 옆으로 약 2cm 벗어난다. 그 정도면 눈에 안 띈다.
        if abs(drift) < 0.2:
            log("  충분히 곧다 — 여기서 멈춘다")
            break
        # 휜 만큼을 회전 명령으로 되돌린다. 한 번에 다 고치면 반대로 넘어가므로
        # 8할만 반영한다.
        trim -= drift / deg_per_unit * 0.8
        trim = max(-25.0, min(25.0, trim))

    return {"drive_trim": round(trim, 1), "history": history}
