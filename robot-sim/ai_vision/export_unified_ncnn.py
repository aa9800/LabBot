"""학습한 90클래스 모델을 로봇용 NCNN으로 내보낸다.

왜 직사각형으로 내보내는가
------------------------
카메라는 4:3인데 정사각형 입력(416x416)에 우겨넣으면 위아래가 회색 여백으로
채워진다. 416x416 중 실제 화면은 416x312뿐이라 25%를 헛계산한다.
416x320 으로 내보내면 그 낭비가 사라진다 — 같은 유효 해상도를 더 싸게 얻는다.

YOLO 는 가로/세로가 32의 배수여야 한다. 416 = 13x32, 320 = 10x32.

사용법
-----
    python export_unified_ncnn.py
    python export_unified_ncnn.py --weights models/unified90_v2/weights/last.pt
    python export_unified_ncnn.py --square      # 정사각형으로(비교용)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDGE = HERE / "models" / "edge"

LAB_NAMES = [
    "microscope", "centrifuge", "pipette", "beaker", "flask", "reagent_bottle",
    "fire_extinguisher", "spill_kit", "flammable_cabinet", "biohazard_bin",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(HERE / "models" / "unified90_v2" / "weights" / "best.pt"))
    ap.add_argument("--width", type=int, default=416)
    ap.add_argument("--height", type=int, default=320)
    ap.add_argument("--square", action="store_true", help="정사각형으로 내보낸다(비교용)")
    ap.add_argument("--name", default="lab_guardian_unified90_ncnn")
    args = ap.parse_args()

    weights = Path(args.weights)
    if not weights.exists():
        raise SystemExit(f"가중치가 없다: {weights}")

    w, h = args.width, args.height
    if args.square:
        h = w
    for v, label in ((w, "가로"), (h, "세로")):
        if v % 32:
            raise SystemExit(f"{label} {v}는 32의 배수가 아니다. YOLO 는 32 배수만 받는다.")

    from ultralytics import YOLO

    model = YOLO(str(weights))
    names = model.names
    classes = [names[i] for i in sorted(names)]
    print(f"가중치 : {weights}")
    print(f"클래스 : {len(classes)}종")
    print(f"입력   : {w}x{h}" + ("  (정사각형)" if w == h else "  (직사각형 — 레터박스 낭비 없음)"))
    print()

    # 이 저장소는 "바탕 화면/공부/피지컬ai" 처럼 한글이 든 경로에 있다. 변환에
    # 쓰이는 pnnx 가 그 경로를 깨뜨려서(한글이 통째로 사라진 채 전달된다)
    # "Parent directory ... does not exist" 로 죽는다. 그래서 ASCII 경로로
    # 가중치를 복사해 거기서 변환하고, 결과만 가져온다.
    work = Path(os.environ.get("LABBOT_DATA_ROOT", r"C:\labbot_datasets")) / "_export"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    local_weights = work / "model.pt"
    shutil.copy2(weights, local_weights)

    prev_cwd = os.getcwd()
    os.chdir(work)
    try:
        # ultralytics 의 imgsz 는 [세로, 가로] 순서다.
        (work / "model_ncnn_model").mkdir(parents=True, exist_ok=True)
        exported = YOLO(str(local_weights)).export(format="ncnn", imgsz=[h, w], half=False)
    finally:
        os.chdir(prev_cwd)
    src = Path(exported)
    if not src.is_absolute():
        src = work / src
    print(f"내보냄 : {src}")

    dst = EDGE / args.name
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.suffix in (".param", ".bin"):
            shutil.copy2(f, dst / f.name)

    param = dst / "model.ncnn.param"
    binf = dst / "model.ncnn.bin"
    if not (param.exists() and binf.exists()):
        raise SystemExit(f"NCNN 산출물이 없다: {dst}")

    manifest = {
        "schema_version": 2,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "format": "ncnn",
        # 직사각형 정보. edge_inference.NcnnYoloBackend 가 이걸 먼저 본다.
        "input_wh": [w, h],
        "input_size": w,                # 옛 코드 호환
        "source_model": weights.name,
        "source_model_sha256": sha256(weights),
        "classes": classes,
        "lab_classes": LAB_NAMES,
        "artifacts": {"param": param.name, "bin": binf.name},
        "note": "COCO 80종 + 실험실 10종 통합. 모델 하나로 사람·일상물체·실험실물품을 모두 본다.",
    }
    (dst / "model_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = sum(f.stat().st_size for f in dst.iterdir())
    print()
    print("─" * 58)
    print(f"배포 준비 완료 : {dst}")
    print(f"크기          : {total/1e6:.1f} MB")
    print(f"입력          : {w}x{h} · 클래스 {len(classes)}종")
    print("다음: scp 로 로봇에 넣고 benchmark_on_pi.py 로 실측할 것.")
    print("─" * 58)


if __name__ == "__main__":
    main()
