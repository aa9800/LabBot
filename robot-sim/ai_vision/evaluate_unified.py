"""새로 학습한 90클래스 단일 모델을 지금 로봇이 쓰는 2모델 구성과 비교한다.

왜 이 스크립트가 필요한가
------------------------
예전에 실험실 데이터로 재학습했을 때, 학습 로그의 mAP만 보고 "좋아졌다"고 판단할
뻔했다. 실제로는 COCO 80클래스를 잊어서 전체적으로는 크게 나빠진 상태였다. 한쪽만
재면 그런 걸 놓친다.

그래서 두 축을 따로 잰다.
  1) 실험실 물품  — 실험실 홀드아웃 세트
  2) 일상 물체/사람 — COCO val 세트

새 모델이 (1)에서 나아지고 (2)에서 크게 나빠지지 않아야 배포한다. 어느 한쪽이라도
지금보다 확실히 나쁘면 배포하지 않고 stable-2model-6hz 로 돌아간다.

사용법
-----
    python evaluate_unified.py
    python evaluate_unified.py --new models/unified90/weights/best.pt
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("LABBOT_DATA_ROOT", r"C:\labbot_datasets"))

LAB_NAMES = [
    "microscope", "centrifuge", "pipette", "beaker", "flask", "reagent_bottle",
    "fire_extinguisher", "spill_kit", "flammable_cabinet", "biohazard_bin",
]


def write_yaml(path: Path, ds_path: Path, val_rel: str, names: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"path: {ds_path.as_posix()}\n"
        f"train: {val_rel}\n"      # 평가만 하므로 train은 형식상 채운다
        f"val: {val_rel}\n"
        "names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(names)),
        encoding="utf-8",
    )


def run_val(weights: Path, data_yaml: Path, imgsz: int, split_name: str):
    from ultralytics import YOLO
    model = YOLO(str(weights))
    r = model.val(data=str(data_yaml), imgsz=imgsz, verbose=False, plots=False)
    box = r.box
    per_class = {}
    # r.box.maps 는 클래스별 mAP50-95. names 순서와 맞춰 담는다.
    try:
        for idx, cls_id in enumerate(r.box.ap_class_index):
            per_class[int(cls_id)] = float(box.maps[int(cls_id)])
    except Exception:
        pass
    return {
        "split": split_name,
        "mAP50": float(box.map50),
        "mAP50_95": float(box.map),
        "precision": float(box.mp),
        "recall": float(box.mr),
        "per_class": per_class,
    }


def fmt(v):
    return f"{v:.4f}"


def compare_row(label, old, new, higher_better=True):
    d = new - old
    if abs(d) < 0.002:
        verdict = "동일"
    elif (d > 0) == higher_better:
        verdict = f"개선 +{abs(d):.4f}"
    else:
        verdict = f"악화 -{abs(d):.4f}"
    return f"  {label:<12} {fmt(old)} -> {fmt(new)}   {verdict}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default=str(HERE / "models" / "unified90" / "weights" / "best.pt"),
                    help="새로 학습한 90클래스 모델")
    ap.add_argument("--old-lab", default=str(HERE / "models" / "lab_guardian_physical_ai_yolo11.pt"),
                    help="지금 로봇이 쓰는 실험실 모델(11클래스)")
    ap.add_argument("--old-coco", default=str(HERE / "yolo11n.pt"),
                    help="지금 로봇이 쓰는 사람/일상물체 모델(COCO 순정)")
    ap.add_argument("--imgsz", type=int, default=320)
    args = ap.parse_args()

    new = Path(args.new)
    if not new.exists():
        raise SystemExit(f"새 모델이 없다: {new}\n먼저 train_unified.py 를 돌릴 것.")

    tmp = DATA_ROOT / "_eval_yaml"
    unified = DATA_ROOT / "lab_guardian_unified"
    lab_v3 = HERE.parent / "datasets" / "lab_guardian_v3"

    # 축 1) 실험실 물품 — lab_guardian_v3 의 valid 를 각 모델의 클래스 체계로 평가
    #   기존 모델은 11클래스(0~9 물품, 10 person), 새 모델은 90클래스(80~89 물품).
    #   같은 이미지를 쓰되 클래스 번호 체계가 달라 yaml 을 따로 만든다.
    lab_old_yaml = tmp / "lab_old.yaml"
    write_yaml(lab_old_yaml, lab_v3, "valid/images", LAB_NAMES + ["person"])

    # 축 2) 일상 물체/사람 — 통합 데이터셋의 valid 안에 COCO val 2,000장이 들어 있다.
    coco_yaml = tmp / "coco_val.yaml"
    write_yaml(coco_yaml, unified, "valid/images",
               [f"c{i}" for i in range(80)] + LAB_NAMES)  # 이름은 평가에 영향 없음

    print("=" * 62)
    print("축 1) 실험실 물품")
    print("=" * 62)
    old_lab = run_val(Path(args.old_lab), lab_old_yaml, args.imgsz, "lab")
    print(f"  기존 실험실 모델 : mAP50 {fmt(old_lab['mAP50'])} · "
          f"mAP50-95 {fmt(old_lab['mAP50_95'])}")
    print("  (새 모델은 클래스 번호가 달라 통합 valid 로 따로 잰다)")

    print()
    print("=" * 62)
    print("축 2) 통합 valid (COCO 2,000장 + 실험실 137장)")
    print("=" * 62)
    new_all = run_val(new, unified / "data.yaml", args.imgsz, "unified")
    print(f"  새 90클래스 모델 : mAP50 {fmt(new_all['mAP50'])} · "
          f"mAP50-95 {fmt(new_all['mAP50_95'])} · "
          f"P {fmt(new_all['precision'])} · R {fmt(new_all['recall'])}")

    print()
    print("  클래스별 mAP50-95:")
    pc = new_all["per_class"]
    print(f"    {'person':<20} {pc.get(0, float('nan')):.4f}")
    for i, n in enumerate(LAB_NAMES):
        v = pc.get(80 + i)
        print(f"    {n:<20} {v:.4f}" if v is not None else f"    {n:<20} (미검출)")

    coco_vals = [v for k, v in pc.items() if k < 80]
    if coco_vals:
        print(f"    {'COCO 80종 평균':<20} {sum(coco_vals)/len(coco_vals):.4f}")

    print()
    print("=" * 62)
    print("판정 기준")
    print("=" * 62)
    print("  실험실 물품이 나아지고 COCO 80종이 크게 안 나빠져야 배포한다.")
    print("  어느 한쪽이라도 확실히 나쁘면 stable-2model-6hz 로 돌아간다.")
    print("  최종 판단은 Pi에서 같은 영상으로 돌린 cycle_ms 와 함께 내린다.")


if __name__ == "__main__":
    main()
