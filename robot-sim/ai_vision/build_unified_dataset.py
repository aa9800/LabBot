"""COCO(리플레이) + 실험실 데이터를 하나의 90클래스 데이터셋으로 합친다.

왜 필요한가
----------
지금 로봇은 모델을 두 개 돌린다. 실험실 물품용 커스텀 모델과 사람/일상물체용
COCO 순정 모델이다. 추론이 두 번 도니까 CPU가 두 배로 들고, 그게 발열의 주범이다.

원래는 하나여야 했다. 그런데 예전에 yolo11n.pt(COCO 11.8만 장 학습)를 실험실
데이터 2,477장'만'으로 재학습시켰더니 COCO 80클래스를 통째로 잊었다. 옛 데이터를
하나도 안 섞은 게 원인이다(catastrophic forgetting).

이 스크립트는 그 실수를 되돌린다. COCO 이미지 일부를 '리플레이'로 같이 넣어서,
새 것을 배우는 동안 옛 것을 잊지 않게 한다.

클래스 매핑
----------
    COCO 0~79            그대로 0~79
    실험실 0~9           80~89 으로 밀어냄
    실험실 10 (person)   0 으로 합침 (COCO의 person과 같은 것이다)

주의: 실험실 데이터는 2,477장 중 49장에만 person 라벨이 있다. 나머지 이미지에
사람이 찍혀 있어도 라벨이 없으므로 학습에서 "사람 아님"이라는 반례로 작용한다.
COCO 리플레이에 사람 사진이 훨씬 많아 상쇄되지만, 리플레이를 너무 줄이면
사람 탐지가 다시 망가질 수 있다.

사용법
-----
    python build_unified_dataset.py                      # 기본값으로 생성
    python build_unified_dataset.py --coco-images 25000  # 리플레이 양 조절
    python build_unified_dataset.py --dry-run            # 계획만 출력
"""

from __future__ import annotations

import argparse
import collections
import os
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASETS = HERE.parent / "datasets"

COCO_ROOT = DATASETS / "coco_replay" / "coco"
LAB_ROOT = DATASETS / "lab_guardian_v3"
OUT_ROOT = DATASETS / "lab_guardian_unified"

# COCO 80클래스 (yolo11n.pt가 이미 아는 것들 — 순서를 바꾸면 안 된다)
COCO_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]

# 실험실 물품 10종 (lab_guardian_v3 의 0~9 순서 그대로 뒤에 붙인다)
LAB_NAMES = [
    "microscope", "centrifuge", "pipette", "beaker", "flask", "reagent_bottle",
    "fire_extinguisher", "spill_kit", "flammable_cabinet", "biohazard_bin",
]

MERGED_NAMES = COCO_NAMES + LAB_NAMES
LAB_OFFSET = len(COCO_NAMES)          # 80
LAB_PERSON_ID = len(LAB_NAMES)        # 실험실 데이터에서 person 은 10번
IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def remap_lab_class(cid: int) -> int | None:
    """실험실 클래스 번호를 통합 번호로 옮긴다. 모르는 번호면 None."""
    if cid == LAB_PERSON_ID:
        return 0                       # person 은 COCO 쪽과 같은 것이다
    if 0 <= cid < len(LAB_NAMES):
        return cid + LAB_OFFSET
    return None


def link_or_copy(src: Path, dst: Path) -> None:
    """같은 볼륨이면 하드링크로 둔다 — COCO 이미지가 19GB라 복사하면 낭비다."""
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def read_label(path: Path):
    """YOLO 라벨 한 장을 (class_id, 나머지문자열) 목록으로 읽는다."""
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 5:
                rows.append((int(parts[0]), " ".join(parts[1:])))
    except FileNotFoundError:
        pass
    return rows


def index_coco(split: str):
    """COCO 라벨을 훑어 (이미지stem -> 등장 클래스 집합)을 만든다."""
    label_dir = COCO_ROOT / "labels" / split
    if not label_dir.is_dir():
        sys.exit(f"COCO 라벨이 없다: {label_dir}\n"
                 f"coco2017labels.zip 을 coco_replay/ 아래에 풀었는지 확인할 것.")
    index = {}
    for f in label_dir.iterdir():
        if f.suffix != ".txt":
            continue
        index[f.stem] = {cid for cid, _ in read_label(f)}
    return index


def pick_balanced(index: dict, target: int, seed: int) -> list[str]:
    """클래스가 골고루 들어가게 COCO 이미지를 고른다.

    그냥 무작위로 뽑으면 사람·의자처럼 흔한 클래스만 잔뜩 들어오고 헤어드라이어
    같은 희귀 클래스는 한 장도 안 들어올 수 있다. 그러면 그 클래스를 잊는다.
    희귀 클래스부터 최소 할당량을 채우고, 남는 자리를 무작위로 메운다.
    """
    rng = random.Random(seed)
    per_class = collections.defaultdict(list)
    for stem, classes in index.items():
        for c in classes:
            per_class[c].append(stem)

    # 이미지 수가 적은 클래스부터 채운다 — 흔한 클래스는 어차피 딸려 들어온다.
    order = sorted(per_class, key=lambda c: len(per_class[c]))
    quota = max(1, target // (len(COCO_NAMES) * 2))

    chosen: set[str] = set()
    for c in order:
        pool = per_class[c]
        rng.shuffle(pool)
        have = sum(1 for s in chosen if c in index[s])
        for stem in pool:
            if have >= quota or len(chosen) >= target:
                break
            if stem not in chosen:
                chosen.add(stem)
                have += 1

    if len(chosen) < target:
        rest = [s for s in index if s not in chosen]
        rng.shuffle(rest)
        chosen.update(rest[: target - len(chosen)])

    return sorted(chosen)


def find_image(dirs: list[Path], stem: str) -> Path | None:
    for d in dirs:
        for ext in IMAGE_EXTS:
            p = d / f"{stem}{ext}"
            if p.exists():
                return p
    return None


def emit_coco(stems, split_out: str, coco_split: str, img_dirs, dry: bool):
    out_img = OUT_ROOT / split_out / "images"
    out_lbl = OUT_ROOT / split_out / "labels"
    label_dir = COCO_ROOT / "labels" / coco_split
    written = missing = 0
    counts = collections.Counter()

    for stem in stems:
        src = find_image(img_dirs, stem)
        if src is None:
            missing += 1
            continue
        rows = read_label(label_dir / f"{stem}.txt")
        counts.update(cid for cid, _ in rows)
        written += 1
        if dry:
            continue
        link_or_copy(src, out_img / f"coco_{stem}{src.suffix}")
        (out_lbl / f"coco_{stem}.txt").write_text(
            "".join(f"{cid} {rest}\n" for cid, rest in rows), encoding="utf-8"
        )
    return written, missing, counts


def emit_lab(lab_split: str, split_out: str, repeat: int, dry: bool):
    src_img = LAB_ROOT / lab_split / "images"
    src_lbl = LAB_ROOT / lab_split / "labels"
    if not src_img.is_dir():
        return 0, 0, collections.Counter()

    out_img = OUT_ROOT / split_out / "images"
    out_lbl = OUT_ROOT / split_out / "labels"
    written = dropped = 0
    counts = collections.Counter()

    for img in sorted(src_img.iterdir()):
        if img.suffix.lower() not in IMAGE_EXTS:
            continue
        rows = []
        for cid, rest in read_label(src_lbl / f"{img.stem}.txt"):
            new_id = remap_lab_class(cid)
            if new_id is None:
                dropped += 1
                continue
            rows.append((new_id, rest))
        counts.update(cid for cid, _ in rows)

        # 실험실 데이터는 COCO에 비해 턱없이 적다. 그대로 두면 한 에폭에서
        # 몇 번 못 보고 지나가므로 같은 이미지를 여러 번 넣어 비중을 맞춘다.
        for k in range(repeat):
            written += 1
            if dry:
                continue
            tag = f"lab_{img.stem}" if k == 0 else f"lab_{img.stem}_r{k}"
            link_or_copy(img, out_img / f"{tag}{img.suffix}")
            (out_lbl / f"{tag}.txt").write_text(
                "".join(f"{cid} {rest}\n" for cid, rest in rows), encoding="utf-8"
            )
    return written, dropped, counts


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coco-images", type=int, default=20000,
                    help="학습에 섞을 COCO 리플레이 이미지 수 (기본 20000)")
    ap.add_argument("--lab-repeat", type=int, default=3,
                    help="실험실 이미지를 한 에폭에 몇 번 넣을지 (기본 3)")
    ap.add_argument("--coco-val", type=int, default=2000,
                    help="검증에 쓸 COCO val 이미지 수 (기본 2000)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="파일은 안 만들고 계획만 출력")
    args = ap.parse_args()

    dry = args.dry_run
    print(f"출력 위치 : {OUT_ROOT}")
    print(f"COCO 리플레이 : {args.coco_images:,}장 / 실험실 반복 : x{args.lab_repeat}")
    print()

    if not dry:
        for split in ("train", "valid"):
            for kind in ("images", "labels"):
                (OUT_ROOT / split / kind).mkdir(parents=True, exist_ok=True)

    # 이미지가 어디 풀렸는지 모르니 흔한 위치를 모두 후보로 둔다.
    train_dirs = [COCO_ROOT / "images" / "train2017",
                  COCO_ROOT.parent / "train2017"]
    val_dirs = [COCO_ROOT / "images" / "val2017",
                COCO_ROOT.parent / "val2017"]

    print("[1/3] COCO 라벨 색인 중...")
    train_index = index_coco("train2017")
    val_index = index_coco("val2017")
    print(f"      train {len(train_index):,}장 · val {len(val_index):,}장")

    print("[2/3] 클래스가 골고루 들어가게 리플레이 이미지 선별 중...")
    train_stems = pick_balanced(train_index, args.coco_images, args.seed)
    val_stems = pick_balanced(val_index, args.coco_val, args.seed)
    print(f"      train {len(train_stems):,}장 · val {len(val_stems):,}장 선택")

    print("[3/3] 병합 중...")
    ctr, cmiss, ccnt = emit_coco(train_stems, "train", "train2017", train_dirs, dry)
    vtr, vmiss, vcnt = emit_coco(val_stems, "valid", "val2017", val_dirs, dry)
    ltr, ldrop, lcnt = emit_lab("train", "train", args.lab_repeat, dry)
    lva, _, lvcnt = emit_lab("valid", "valid", 1, dry)

    if cmiss or vmiss:
        print(f"      ⚠ 이미지 파일을 못 찾아 건너뛴 것: train {cmiss:,} · val {vmiss:,}")
        print(f"        (train2017.zip 압축 해제가 끝났는지 확인할 것)")

    if not dry:
        (OUT_ROOT / "data.yaml").write_text(
            "# COCO 리플레이 + 실험실 물품 통합 데이터셋 (build_unified_dataset.py 생성)\n"
            f"path: {OUT_ROOT.as_posix()}\n"
            "train: train/images\n"
            "val: valid/images\n"
            "names:\n"
            + "".join(f"  {i}: {n}\n" for i, n in enumerate(MERGED_NAMES)),
            encoding="utf-8",
        )

    print()
    print("─" * 58)
    print(f"train : COCO {ctr:,}장 + 실험실 {ltr:,}장  =  {ctr + ltr:,}장")
    print(f"valid : COCO {vtr:,}장 + 실험실 {lva:,}장  =  {vtr + lva:,}장")
    print(f"클래스: {len(MERGED_NAMES)} (COCO 80 + 실험실 10)")
    if ldrop:
        print(f"⚠ 알 수 없는 실험실 클래스 {ldrop}개를 버렸다")

    # 학습 뒤 무엇이 잘 되고 안 되는지 해석하려면 이 수치가 필요하다.
    total = ccnt + lcnt
    print()
    print("train 인스턴스 (실험실 10종 + person):")
    for i in [0] + list(range(LAB_OFFSET, len(MERGED_NAMES))):
        print(f"   {i:2d} {MERGED_NAMES[i]:<18} {total[i]:>7,}")
    thin = [MERGED_NAMES[c] for c in range(len(COCO_NAMES)) if total[c] < 30]
    if thin:
        print()
        print(f"⚠ 인스턴스 30개 미만인 COCO 클래스 {len(thin)}종 — 이건 잊을 수 있다:")
        print("   " + ", ".join(thin))
    print("─" * 58)
    if dry:
        print("(--dry-run 이라 파일은 만들지 않았다)")


if __name__ == "__main__":
    main()
