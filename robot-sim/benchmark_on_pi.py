"""로봇에서 모델 구성을 직접 비교한다 — 지금 2모델 vs 새 통합 1모델.

왜 필요한가
----------
PC에서 잰 mAP 는 "얼마나 잘 맞히는가"만 말해준다. 로봇에서 실제로 쓸 수 있는지는
한 주기에 몇 ms 가 드는지, 그래서 발열이 어떻게 되는지가 정한다. 그 둘은 같이
봐야 한다 — 정확도가 조금 올라도 주기가 두 배가 되면 못 쓴다.

같은 프레임으로 두 구성을 번갈아 돌려서, 하드웨어 상태가 다른 탓에 생기는
착시를 없앤다.

사용법 (로봇에서)
----------------
    sudo systemctl stop labkeeper-robot
    python3 benchmark_on_pi.py
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODELS = Path("/home/pi/labkeeper/ai_vision/models/edge")


def read_temp() -> float:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return float("nan")


def throttled() -> str:
    try:
        with open("/sys/devices/platform/soc/soc:firmware/get_throttled") as f:
            return f.read().strip()
    except Exception:
        return "?"


def bench(backends, frames, label, warmup=5):
    """한 프레임을 backends 전부에 통과시키는 것을 '한 주기'로 본다."""
    for f in frames[:warmup]:
        for b in backends:
            b.detect(f)

    cycles = []
    t_start = time.time()
    for f in frames:
        s = time.perf_counter()
        for b in backends:
            b.detect(f)
        cycles.append((time.perf_counter() - s) * 1000.0)
    elapsed = time.time() - t_start

    cycles.sort()
    p95 = cycles[min(len(cycles) - 1, int(len(cycles) * 0.95))]
    print(f"  {label}")
    print(f"    한 주기   평균 {statistics.fmean(cycles):6.1f} ms   p95 {p95:6.1f} ms")
    print(f"    최대 처리 {len(cycles)/elapsed:5.1f} fps   (이론상, 다른 작업 없을 때)")
    print(f"    끝난 뒤   {read_temp():.1f}°C   throttled={throttled()}")
    return statistics.fmean(cycles)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--unified", default="lab_guardian_unified90_ncnn")
    args = ap.parse_args()

    import numpy as np
    from edge_inference import NcnnYoloBackend

    # 실제 카메라 프레임으로 재는 게 가장 정직하다. 카메라를 못 열면
    # (서비스가 잡고 있으면) 난수 프레임으로 대신한다 — 연산량은 같다.
    frames = []
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={"format": "BGR888", "size": (640, 480)}))
        cam.start()
        time.sleep(1.5)
        for _ in range(args.frames):
            frames.append(cam.capture_array())
        cam.stop()
        cam.close()
        print(f"실제 카메라 프레임 {len(frames)}장으로 측정한다.")
    except Exception as e:
        print(f"카메라를 못 열어 난수 프레임으로 대신한다 ({type(e).__name__}).")
        print("서비스가 카메라를 잡고 있다면 먼저 멈출 것: sudo systemctl stop labkeeper-robot")
        frames = [(np.random.rand(480, 640, 3) * 255).astype(np.uint8) for _ in range(args.frames)]

    print(f"시작 온도 {read_temp():.1f}°C · throttled={throttled()}")
    print()

    print("=" * 58)
    print("A) 지금 구성 — 모델 2개 순차")
    print("=" * 58)
    lab = NcnnYoloBackend.from_manifest(MODELS / "lab_guardian_physical_ai_ncnn", num_threads=args.threads)
    person = NcnnYoloBackend.from_manifest(MODELS / "person_coco_ncnn", num_threads=args.threads)
    a = bench([lab, person], frames, "실험실 모델 + COCO 순정 모델")
    del lab, person

    unified_dir = MODELS / args.unified
    if not unified_dir.is_dir():
        print()
        print(f"새 통합 모델이 아직 없다: {unified_dir}")
        print("PC 에서 export_unified_ncnn.py 로 만들어 scp 로 넣을 것.")
        return

    time.sleep(5)  # 앞 측정의 열이 남아 다음 측정을 불리하게 만들지 않도록
    print()
    print("=" * 58)
    print("B) 새 구성 — 통합 90클래스 모델 1개")
    print("=" * 58)
    uni = NcnnYoloBackend.from_manifest(unified_dir, num_threads=args.threads)
    print(f"  입력 {uni.input_w}x{uni.input_h} · 클래스 {len(uni.class_names)}종")
    b = bench([uni], frames, "통합 모델 단독")

    print()
    print("=" * 58)
    gain = (a - b) / a * 100 if a else 0
    print(f"한 주기 {a:.1f} ms -> {b:.1f} ms   ({gain:+.0f}%)")
    if b < a:
        print("연산이 줄었다. 남는 여유를 fps 로 쓸지 해상도로 쓸지 정하면 된다.")
    else:
        print("빨라지지 않았다. 배포하지 말고 원인을 먼저 찾을 것.")
    print("=" * 58)


if __name__ == "__main__":
    main()
