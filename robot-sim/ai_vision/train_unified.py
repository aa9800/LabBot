"""통합 90클래스 모델을 학습한다 (COCO 리플레이 + 실험실 물품).

목표
----
지금 로봇은 모델 두 개를 순차로 돌린다(실험실용 + COCO 순정). 한 주기가 74.5ms라
6Hz가 한계고, 그게 발열의 주범이다. 하나로 합치면 추론이 절반이 되어 10Hz까지
올릴 수 있다.

왜 yolo11n.pt 에서 출발하는가
---------------------------
이 가중치는 COCO 11.8만 장으로 이미 학습된 상태다. 여기서 출발해야 80클래스
지식을 물려받는다. 처음부터(scratch) 학습하면 우리가 가진 2만 장으로는 절대
따라잡을 수 없다.

왜 학습률을 낮추는가
------------------
이미 잘 학습된 가중치를 크게 흔들면 옛 지식이 날아간다(예전 실패가 그것이다).
사전학습 가중치를 살짝만 조정하는 것이 목적이므로 기본값보다 낮게 잡는다.

사용법
-----
    python train_unified.py                    # 기본 60에폭
    python train_unified.py --epochs 40        # 짧게
    python train_unified.py --resume           # 중단된 학습 이어서
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("LABBOT_DATA_ROOT", r"C:\labbot_datasets"))
DATA_YAML = DATA_ROOT / "lab_guardian_unified" / "data.yaml"
BASE_WEIGHTS = HERE / "yolo11n.pt"
RUNS_DIR = HERE / "models"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=320,
                    help="로봇이 320으로 추론하므로 학습도 320으로 맞춘다")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr0", type=float, default=0.002,
                    help="기본값(0.01)보다 낮게 — 사전학습 지식을 지키기 위해")
    ap.add_argument("--name", default="unified90")
    ap.add_argument("--device", default="0")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--workers", type=int, default=2,
                    help="Windows에서는 낮게 — 높으면 CUDA pinned memory 오류로 죽는다")
    ap.add_argument("--freeze", type=int, default=0,
                    help="앞쪽 N개 층을 얼린다. 사전학습 지식을 지키는 가장 확실한 수단")
    args = ap.parse_args()

    if not DATA_YAML.exists():
        raise SystemExit(f"데이터셋이 없다: {DATA_YAML}\n"
                         "먼저 build_unified_dataset.py 를 돌릴 것.")

    from ultralytics import YOLO

    weights = BASE_WEIGHTS if BASE_WEIGHTS.exists() else "yolo11n.pt"
    print(f"베이스 가중치 : {weights}")
    print(f"데이터셋      : {DATA_YAML}")
    print(f"에폭/이미지크기/배치 : {args.epochs} / {args.imgsz} / {args.batch}")
    print(f"학습률        : {args.lr0} (기본 0.01보다 낮춤)")
    print()

    model = YOLO(str(weights))
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(RUNS_DIR),
        name=args.name,
        exist_ok=True,
        resume=args.resume,

        lr0=args.lr0,
        lrf=0.01,
        warmup_epochs=3.0,       # 처음부터 세게 밀면 사전학습 지식이 흔들린다
        optimizer="AdamW",
        cos_lr=True,

        # 앞쪽 층은 "무엇이 물체인가"라는 일반 지식을 담고 있다. 이걸 얼려두면
        # COCO 80종을 잊는 것을 크게 막을 수 있다. 1차 학습(동결 없음, 리플레이
        # 17%)에서 COCO mAP50이 0.42 -> 0.32로 24% 빠졌다.
        freeze=args.freeze if args.freeze > 0 else None,

        # 실험실 물품은 대개 정면·정립이라 상하 뒤집기는 오히려 방해가 된다.
        fliplr=0.5,
        flipud=0.0,
        degrees=8.0,
        scale=0.4,               # 로봇이 다양한 거리에서 보므로 크기 변화를 크게
        mosaic=1.0,
        close_mosaic=10,         # 마지막 10에폭은 모자이크를 꺼서 실제 분포에 맞춘다
        hsv_v=0.5,               # 실험실 조명 변화 대비
        hsv_s=0.6,

        patience=20,
        val=True,
        plots=True,
        seed=42,
        # Windows에서 워커를 많이 두면 pinned memory 쪽에서
        # "CUDA error: resource already mapped"로 죽는다(실측 2026-08-30).
        # 데이터 로딩이 조금 느려져도 안 죽는 쪽을 택한다.
        workers=args.workers,
    )

    best = RUNS_DIR / args.name / "weights" / "best.pt"
    print()
    print("─" * 58)
    print(f"학습 완료. best: {best}")
    print("다음: evaluate_unified.py 로 지금 2모델 구성과 비교할 것.")
    print("검증을 통과하기 전에는 로봇에 배포하지 않는다.")
    print("─" * 58)


if __name__ == "__main__":
    main()
