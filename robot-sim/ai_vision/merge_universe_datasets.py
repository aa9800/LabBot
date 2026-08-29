"""Roboflow Universe에서 받은 단일 클래스 데이터셋들을 우리 11클래스 체계로 병합한다.

왜 필요한가: 각 데이터셋은 자기만의 클래스 번호를 쓴다(대부분 0번 하나). 그대로 합치면
'0번'이 데이터셋마다 다른 물체를 가리켜 학습이 망가진다. 그래서 라벨 파일의 클래스 번호를
우리 체계로 다시 쓴 뒤 합친다.

사람(person)은 일부러 넣지 않는다 — 실측 결과 파인튜닝이 오히려 사람 판별을 망가뜨려서
(정밀도 0.356 vs 순정 0.640), 사람은 순정 COCO 모델이 따로 담당한다.
"""
from __future__ import annotations

import argparse
import shutil
from collections import Counter
from pathlib import Path

# 우리 체계 (person은 학습에서 제외하므로 10개까지만 쓴다)
OUR_CLASSES = [
    "microscope", "centrifuge", "pipette", "beaker", "flask",
    "reagent_bottle", "fire_extinguisher", "spill_kit",
    "flammable_cabinet", "biohazard_bin", "person",
]

# 받은 데이터셋의 (원본 클래스 번호 -> 우리 클래스 이름).
# 원본에 우리와 무관한 클래스가 섞여 있으면 매핑에서 빼면 그 라벨은 버려진다.
DATASET_MAP = {
    "fire_extinguisher__fire-extinguisher-8kk5k": {0: "fire_extinguisher"},
    "fire_extinguisher__fire-extinguisher-manii": {0: "fire_extinguisher"},
    "pipette__pipette-epucw":                     {0: "pipette"},  # 1=volumetric flask는 버림
    "reagent_bottle__reagent-viqoz":              {0: "reagent_bottle"},
    "beaker__beaker-hmvpc":                       {0: "beaker"},
    "biohazard_bin__biohazard":                   {0: "biohazard_bin"},
}


def convert(src_root: Path, out_root: Path, limit_per_class: int) -> Counter:
    idx = {n: i for i, n in enumerate(OUR_CLASSES)}
    kept = Counter()
    copied = Counter()

    for ds_name, mapping in DATASET_MAP.items():
        ds = src_root / ds_name
        if not ds.is_dir():
            print(f"  건너뜀(없음): {ds_name}")
            continue
        remap = {old: idx[new] for old, new in mapping.items()}
        target_class = next(iter(mapping.values()))

        for split in ("train", "valid", "test"):
            img_dir, lbl_dir = ds / split / "images", ds / split / "labels"
            if not img_dir.is_dir():
                continue
            out_img = out_root / split / "images"
            out_lbl = out_root / split / "labels"
            out_img.mkdir(parents=True, exist_ok=True)
            out_lbl.mkdir(parents=True, exist_ok=True)

            for img in sorted(img_dir.glob("*.jpg")):
                # 클래스별 상한 — 소화기가 2851장이라 그대로 두면 다른 클래스를 압도한다.
                if copied[target_class] >= limit_per_class:
                    break
                lbl = lbl_dir / f"{img.stem}.txt"
                if not lbl.exists():
                    continue
                lines = []
                for line in lbl.read_text().splitlines():
                    p = line.split()
                    if len(p) < 5:
                        continue
                    old = int(p[0])
                    if old not in remap:
                        continue  # 우리와 무관한 클래스는 버린다
                    lines.append(" ".join([str(remap[old])] + p[1:]))
                if not lines:
                    continue  # 라벨이 하나도 안 남으면 이미지도 넣지 않는다

                stem = f"{ds_name[:24]}_{img.stem}"[:80]
                shutil.copy2(img, out_img / f"{stem}.jpg")
                (out_lbl / f"{stem}.txt").write_text("\n".join(lines), encoding="utf-8")
                copied[target_class] += 1
                for ln in lines:
                    kept[OUR_CLASSES[int(ln.split()[0])]] += 1
        print(f"  {ds_name[:44]:44} -> {target_class} {copied[target_class]}장")
    return kept


def main():
    ap = argparse.ArgumentParser(description="Universe 데이터셋을 우리 클래스 체계로 병합")
    ap.add_argument("--src", default="datasets/rf_downloads")
    ap.add_argument("--out", default="datasets/universe_merged")
    ap.add_argument("--limit-per-class", type=int, default=600,
                    help="클래스당 최대 이미지 수(불균형 방지)")
    a = ap.parse_args()

    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    kept = convert(Path(a.src), out, a.limit_per_class)

    print("\n클래스별 인스턴스:")
    for name, n in kept.most_common():
        print(f"  {name:20} {n}")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
