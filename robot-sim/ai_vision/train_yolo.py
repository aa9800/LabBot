"""LabKeeper YOLOv11 모델 학습 및 평가 스크립트."""
import os
import sys
import torch
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ultralytics import YOLO
from ai_vision.config import TARGET_CLASSES
from ai_vision.dataset_builder import DATASETS_ROOT, prepare_data_yaml

MODELS_DIR = Path(__file__).resolve().parent / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def train_model(
    epochs: int = 25,
    imgsz: int = 640,
    batch_size: int = 8,
    model_type: str = "yolo11n.pt",
    device: str = "auto",
    data_yaml: str = None,
):
    """YOLOv11 모델 파인튜닝 학습."""
    print("=" * 60)
    print("🚀 [LabKeeper AI] Starting YOLOv11 Model Training...")
    print(f" * Target Classes: {TARGET_CLASSES}")
    print(f" * Epochs: {epochs}, ImgSize: {imgsz}, Batch: {batch_size}")
    
    if device == "auto":
        device = "0" if torch.cuda.is_available() else "cpu"
    print(f" * Device: {device} (CUDA Available: {torch.cuda.is_available()})")
    print("=" * 60)

    # 1. data.yaml 경로 확인
    if data_yaml is None:
        balanced_yaml = DATASETS_ROOT.parent / "lab_guardian_v2" / "data.yaml"
        data_yaml = balanced_yaml if balanced_yaml.exists() else DATASETS_ROOT / "data.yaml"
    else:
        data_yaml = Path(data_yaml)
    if not data_yaml.exists():
        data_yaml = prepare_data_yaml()

    # 2. 사전학습된 YOLOv11 모델 로드
    model = YOLO(model_type)

    # 3. 모델 학습 시작
    results = model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch_size,
        device=device,
        project=str(MODELS_DIR),
        name="lab_guardian_run",
        exist_ok=True,
        verbose=True,
    )

    # 4. 최적 가중치 복사
    best_pt = MODELS_DIR / "lab_guardian_run" / "weights" / "best.pt"
    target_pt = MODELS_DIR / "lab_guardian_yolo11.pt"
    if best_pt.exists():
        import shutil
        shutil.copy(best_pt, target_pt)
        print(f"\n✅ [LabKeeper AI] Best model saved to: {target_pt}")
    else:
        print("\n⚠️ Best weights not found, saving current model...")
        model.save(str(target_pt))

    # 5. 검증 평가 (Evaluation)
    print("\n📊 [LabKeeper AI] Running Model Validation...")
    metrics = model.val()
    print(f" * mAP50-95: {metrics.box.map:.4f}")
    print(f" * mAP50:    {metrics.box.map50:.4f}")
    print(f" * Precision: {metrics.box.mp:.4f}")
    print(f" * Recall:    {metrics.box.mr:.4f}")

    return model, target_pt


if __name__ == "__main__":
    train_model(epochs=10, batch_size=4)
