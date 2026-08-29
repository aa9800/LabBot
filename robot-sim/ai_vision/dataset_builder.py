"""LabBot 통합 비전 데이터셋 빌더.
Roboflow Universe 및 시뮬레이션 합성 데이터를 하나의 YOLO 포맷 데이터셋으로 통합합니다.
"""
import os
import sys
import shutil
import yaml
from pathlib import Path
from typing import List, Dict

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai_vision.config import TARGET_CLASSES, CLASS_METADATA
from ai_vision.roboflow_client import RoboflowManager

DATASETS_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "lab_guardian"

# Roboflow Universe 매핑 소스
UNIVERSE_SOURCES = [
    {
        "class": "fire_extinguisher",
        "project_id": "cv-projects-ab4ye/fire-extinguisher-8kk5k",
        "version": 1,
    },
    {
        "class": "microscope",
        "project_id": "lengineer/microscope",
        "version": 1,
    },
    {
        "class": "pipette",
        "project_id": "lengineer/pipette",
        "version": 1,
    },
    {
        "class": "beaker",
        "project_id": "ustb-tazql/beaker-hmvpc",
        "version": 1,
    },
    {
        "class": "biohazard_bin",
        "project_id": "test-roboflow-ikvmo/biohazard",
        "version": 1,
    },
]


def prepare_data_yaml(output_dir: Path = DATASETS_ROOT) -> Path:
    """YOLOv11 학습용 data.yaml 파일 생성."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    train_dir = (output_dir / "train" / "images").resolve()
    val_dir = (output_dir / "valid" / "images").resolve()
    test_dir = (output_dir / "test" / "images").resolve()

    train_dir.mkdir(parents=True, exist_ok=True)
    val_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    yaml_data = {
        "path": str(output_dir.resolve()).replace("\\", "/"),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "names": {i: name for i, name in enumerate(TARGET_CLASSES)},
        "nc": len(TARGET_CLASSES),
    }

    yaml_path = output_dir / "data.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, sort_keys=False, allow_unicode=True)

    print(f"[DatasetBuilder] data.yaml created at {yaml_path}")
    print(f"[DatasetBuilder] Classes ({len(TARGET_CLASSES)}): {TARGET_CLASSES}")
    return yaml_path


def download_universe_samples(limit_per_class: int = 100):
    """Roboflow Universe에서 핵심 클래스 데이터셋 다운로드 및 통합."""
    rf = RoboflowManager()
    raw_dir = DATASETS_ROOT / "raw_downloads"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for item in UNIVERSE_SOURCES:
        cls_name = item["class"]
        proj_id = item["project_id"]
        ver = item["version"]
        print(f"\n[DatasetBuilder] Fetching Universe dataset for '{cls_name}' ({proj_id})...")
        try:
            loc = rf.download_dataset(proj_id, version=ver, model_format="yolov11", target_dir=str(raw_dir / cls_name))
            print(f" -> Downloaded to {loc}")
        except Exception as e:
            print(f" -> Skipping {proj_id}: {e}")

    prepare_data_yaml(DATASETS_ROOT)


if __name__ == "__main__":
    download_universe_samples()
