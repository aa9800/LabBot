"""Roboflow에서 다운로드받은 각 클래스별 데이터셋을 하나의 YOLOv11 데이터셋으로 병합."""
import os
import sys
import shutil
import random
import yaml
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai_vision.config import TARGET_CLASSES
from ai_vision.dataset_builder import DATASETS_ROOT, prepare_data_yaml

def merge_all_classes():
    raw_dir = DATASETS_ROOT / "raw_downloads"
    output_dir = DATASETS_ROOT

    # 1. 디렉토리 초기화
    for split in ("train", "valid", "test"):
        (output_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (output_dir / split / "labels").mkdir(parents=True, exist_ok=True)

    print(f"[MergeSplits] Merging datasets from {raw_dir} into {output_dir}...")

    total_merged = 0

    for cls_dir in raw_dir.iterdir():
        if not cls_dir.is_dir():
            continue

        target_cls_name = cls_dir.name
        if target_cls_name not in TARGET_CLASSES:
            # 매핑 찾기
            for tc in TARGET_CLASSES:
                if tc in target_cls_name or target_cls_name in tc:
                    target_cls_name = tc
                    break

        if target_cls_name not in TARGET_CLASSES:
            continue

        target_cls_id = TARGET_CLASSES.index(target_cls_name)
        print(f" -> Processing '{cls_dir.name}' -> Class ID {target_cls_id} ({target_cls_name})")

        source_names = {}
        yaml_path = cls_dir / "data.yaml"
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as yaml_file:
                raw_names = (yaml.safe_load(yaml_file) or {}).get("names", {})
            if isinstance(raw_names, list):
                source_names = {index: name for index, name in enumerate(raw_names)}
            elif isinstance(raw_names, dict):
                source_names = {int(index): name for index, name in raw_names.items()}

        accepted_source_ids = {
            source_id for source_id, source_name in source_names.items()
            if str(source_name).lower().replace(" ", "_") == target_cls_name
            or target_cls_name in str(source_name).lower().replace(" ", "_")
        }

        # 각 split (train, valid, test) 폴더 탐색
        for split in ("train", "valid", "test"):
            src_img_dir = cls_dir / split / "images"
            src_lbl_dir = cls_dir / split / "labels"

            if not src_img_dir.exists():
                src_img_dir = cls_dir / "images"
                src_lbl_dir = cls_dir / "labels"

            if not src_img_dir.exists():
                continue

            dest_img_dir = output_dir / split / "images"
            dest_lbl_dir = output_dir / split / "labels"

            for img_path in src_img_dir.glob("*.*"):
                if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    continue

                stem = img_path.stem
                lbl_path = src_lbl_dir / f"{stem}.txt"

                new_stem = f"{target_cls_name}_{stem}"
                target_img_path = dest_img_dir / f"{new_stem}{img_path.suffix}"
                target_lbl_path = dest_lbl_dir / f"{new_stem}.txt"

                # 이미지 복사
                shutil.copy(img_path, target_img_path)

                # 라벨 클래스 ID 리매핑
                if lbl_path.exists():
                    with open(lbl_path, "r", encoding="utf-8") as lf:
                        lines = lf.readlines()
                    
                    remapped_lines = []
                    for line in lines:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            source_id = int(parts[0])
                            if source_names and source_id not in accepted_source_ids:
                                continue
                            # class_id x_center y_center width height
                            parts[0] = str(target_cls_id)
                            remapped_lines.append(" ".join(parts) + "\n")
                    
                    with open(target_lbl_path, "w", encoding="utf-8") as out_lf:
                        out_lf.writelines(remapped_lines)
                else:
                    # 라벨이 없는 이미지는 학습에 넣지 않는다. 전체 화면 가짜 박스는
                    # 모델이 배경을 물체로 학습하게 만드는 가장 큰 원인이 된다.
                    target_img_path.unlink(missing_ok=True)
                    continue

                total_merged += 1

    prepare_data_yaml(output_dir)
    print(f"\n✅ [MergeSplits] Total {total_merged} images successfully merged into unified YOLO dataset!")

if __name__ == "__main__":
    merge_all_classes()
