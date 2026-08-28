"""깨끗한 실제 이미지와 Isaac 합성 이미지를 균형 있게 합친다."""
import random
import shutil
import sys
from pathlib import Path

import yaml

_DIR = Path(__file__).resolve().parent
_ROOT = _DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai_vision.config import TARGET_CLASSES
from ai_vision.dataset_builder import DATASETS_ROOT, prepare_data_yaml

RAW_ROOT = DATASETS_ROOT / "raw_downloads"
SYNTHETIC_ROOT = DATASETS_ROOT.parent / "synthetic_isaac"
OUTPUT_ROOT = DATASETS_ROOT.parent / "lab_guardian_v2"


def source_names(dataset_dir):
    yaml_path = dataset_dir / "data.yaml"
    if not yaml_path.exists():
        return {}
    raw = (yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}).get("names", {})
    if isinstance(raw, list):
        return {index: str(name) for index, name in enumerate(raw)}
    return {int(index): str(name) for index, name in raw.items()}


def copy_pair(image_path, label_path, output_split, prefix, mapper=None, allow_empty=False):
    lines = []
    if label_path.exists():
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            source_id = int(parts[0])
            if mapper is not None and source_id not in mapper:
                continue
            parts[0] = str(mapper[source_id] if mapper is not None else source_id)
            lines.append(" ".join(parts))
    if not lines and not allow_empty:
        return False
    image_out = OUTPUT_ROOT / output_split / "images"
    label_out = OUTPUT_ROOT / output_split / "labels"
    image_out.mkdir(parents=True, exist_ok=True)
    label_out.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}_{image_path.stem}"
    shutil.copy2(image_path, image_out / f"{stem}{image_path.suffix.lower()}")
    (label_out / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def main(real_limit_per_class=90):
    random.seed(20260827)
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)

    counts = {name: 0 for name in TARGET_CLASSES}
    for split in ("train", "valid", "test"):
        image_dir = SYNTHETIC_ROOT / split / "images"
        for image_path in image_dir.glob("*.*") if image_dir.exists() else []:
            label_path = SYNTHETIC_ROOT / split / "labels" / f"{image_path.stem}.txt"
            is_background = not label_path.read_text(encoding="utf-8").strip()
            if copy_pair(image_path, label_path, split, "sim", allow_empty=is_background):
                if not is_background:
                    class_id = int(label_path.read_text(encoding="utf-8").split()[0])
                    counts[TARGET_CLASSES[class_id]] += 1

    if RAW_ROOT.exists():
        for class_dir in RAW_ROOT.iterdir():
            if not class_dir.is_dir():
                continue
            class_name = next((name for name in TARGET_CLASSES if name == class_dir.name or name in class_dir.name), None)
            if class_name is None:
                continue
            names = source_names(class_dir)
            accepted = {
                source_id for source_id, name in names.items()
                if name.lower().replace(" ", "_") == class_name
                or class_name in name.lower().replace(" ", "_")
            }
            mapper = {source_id: TARGET_CLASSES.index(class_name) for source_id in accepted}
            candidates = []
            for split in ("train", "valid", "test"):
                image_dir = class_dir / split / "images"
                if image_dir.exists():
                    candidates.extend((split, path) for path in image_dir.glob("*.*"))
            random.shuffle(candidates)
            copied = 0
            for original_split, image_path in candidates:
                if copied >= real_limit_per_class:
                    break
                label_path = image_path.parent.parent / "labels" / f"{image_path.stem}.txt"
                output_split = "valid" if copied % 10 == 8 else "test" if copied % 10 == 9 else "train"
                if copy_pair(image_path, label_path, output_split, f"real_{class_name}", mapper):
                    copied += 1
                    counts[class_name] += 1

    prepare_data_yaml(OUTPUT_ROOT)
    print("[Balanced Dataset]", counts)
    print(f"[Balanced Dataset] output: {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
