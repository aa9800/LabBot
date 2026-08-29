"""기존 연구실 데이터와 사람 데이터를 합쳐 단일 Physical AI 데이터셋을 만든다.

기존 ``lab_guardian_v2``는 절대 수정하지 않는다. COCO 계열 소스에서는 person
라벨만 가져오고 나머지 COCO 클래스는 버린다. 이 데이터는 단일 모델 파이프라인을
검증하기 위한 부트스트랩이며, 운영 승격 전 실제 라즈봇 연구실 사람 영상을 추가한다.
"""

import argparse
import hashlib
import json
import random
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ai_vision.config import TARGET_CLASSES


ROBOT_SIM_ROOT = Path(__file__).resolve().parents[1]
DATASETS_ROOT = ROBOT_SIM_ROOT / "datasets"
DEFAULT_LAB_SOURCE = DATASETS_ROOT / "lab_guardian_v2"
DEFAULT_PERSON_SOURCE = DATASETS_ROOT / "sources" / "coco128"
DEFAULT_OUTPUT = DATASETS_ROOT / "lab_guardian_physical_ai_v1"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
PERSON_SOURCE_CLASS_ID = 0
PERSON_TARGET_CLASS_ID = TARGET_CLASSES.index("person")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_valid_labels(label_path: Path, allowed_ids=None):
    labels = []
    if not label_path.exists():
        return labels
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.split()
        if len(parts) != 5:
            continue
        try:
            class_id = int(parts[0])
            coords = [float(value) for value in parts[1:]]
        except ValueError:
            continue
        if allowed_ids is not None and class_id not in allowed_ids:
            continue
        if not all(0.0 <= value <= 1.0 for value in coords):
            continue
        labels.append((class_id, coords))
    return labels


def _write_pair(image_path: Path, labels, output: Path, split: str, prefix: str):
    image_dir = output / split / "images"
    label_dir = output / split / "labels"
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}_{image_path.stem}"
    shutil.copy2(image_path, image_dir / f"{stem}{image_path.suffix.lower()}")
    lines = [
        " ".join([str(class_id), *[f"{value:.8f}" for value in coords]])
        for class_id, coords in labels
    ]
    (label_dir / f"{stem}.txt").write_text(
        ("\n".join(lines) + "\n") if lines else "", encoding="utf-8"
    )


def _copy_lab_dataset(source: Path, output: Path, counts: Counter):
    for split in ("train", "valid", "test"):
        image_dir = source / split / "images"
        label_dir = source / split / "labels"
        if not image_dir.exists():
            continue
        for image_path in sorted(image_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            labels = _read_valid_labels(label_dir / f"{image_path.stem}.txt")
            if any(class_id >= PERSON_TARGET_CLASS_ID for class_id, _ in labels):
                raise ValueError(f"기존 연구실 라벨 ID 범위 오류: {image_path}")
            _write_pair(image_path, labels, output, split, "lab")
            counts[f"images_{split}"] += 1
            for class_id, _ in labels:
                counts[f"class_{TARGET_CLASSES[class_id]}"] += 1


def _person_candidates(source: Path):
    image_roots = [source / "images" / "train2017", source / "train" / "images"]
    label_roots = [source / "labels" / "train2017", source / "train" / "labels"]
    for image_root, label_root in zip(image_roots, label_roots):
        if not image_root.exists():
            continue
        candidates = []
        for image_path in sorted(image_root.iterdir()):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            labels = _read_valid_labels(
                label_root / f"{image_path.stem}.txt", {PERSON_SOURCE_CLASS_ID}
            )
            if labels:
                candidates.append((image_path, labels))
        return candidates
    raise FileNotFoundError(f"사람 데이터 이미지 폴더를 찾지 못했습니다: {source}")


def _copy_person_dataset(source: Path, output: Path, counts: Counter, seed: int):
    candidates = _person_candidates(source)
    random.Random(seed).shuffle(candidates)
    total = len(candidates)
    valid_count = max(1, round(total * 0.1))
    test_count = max(1, round(total * 0.1))
    for index, (image_path, labels) in enumerate(candidates):
        if index < valid_count:
            split = "valid"
        elif index < valid_count + test_count:
            split = "test"
        else:
            split = "train"
        remapped = [(PERSON_TARGET_CLASS_ID, coords) for _, coords in labels]
        _write_pair(image_path, remapped, output, split, "person")
        counts[f"images_{split}"] += 1
        counts["class_person"] += len(remapped)
    return total


def build_dataset(lab_source: Path, person_source: Path, output: Path, seed: int):
    if output.exists():
        raise FileExistsError(
            f"출력 데이터셋이 이미 있습니다: {output}. 기존 버전을 보존하려고 중단합니다."
        )
    counts = Counter()
    _copy_lab_dataset(lab_source, output, counts)
    person_images = _copy_person_dataset(person_source, output, counts, seed)

    data = {
        "path": str(output.resolve()).replace("\\", "/"),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "names": {index: name for index, name in enumerate(TARGET_CLASSES)},
        "nc": len(TARGET_CLASSES),
    }
    (output / "data.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    source_zip = person_source.parent / "coco128.zip"
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "classes": TARGET_CLASSES,
        "sources": {
            "lab": str(lab_source.resolve()),
            "person": str(person_source.resolve()),
            "person_source_archive_sha256": _sha256(source_zip) if source_zip.exists() else None,
        },
        "counts": dict(sorted(counts.items())),
        "person_bootstrap_images": person_images,
        "limitations": [
            "COCO128 person subset is a pipeline bootstrap, not final real-lab validation data.",
            "Add real Raspbot laboratory person images before production promotion.",
        ],
    }
    (output / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-source", type=Path, default=DEFAULT_LAB_SOURCE)
    parser.add_argument("--person-source", type=Path, default=DEFAULT_PERSON_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20260829)
    args = parser.parse_args()
    manifest = build_dataset(args.lab_source, args.person_source, args.output, args.seed)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
