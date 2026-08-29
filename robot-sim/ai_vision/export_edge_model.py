"""학습된 단일 YOLO11 모델을 Raspberry Pi용 경량 형식으로 내보낸다."""

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ultralytics import YOLO


AI_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = AI_DIR / "models" / "lab_guardian_physical_ai_yolo11.pt"
DEFAULT_OUTPUT_ROOT = AI_DIR / "models" / "edge"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_model(model_path: Path, output: Path, imgsz: int, export_format: str):
    if output.exists():
        raise FileExistsError(f"기존 edge 모델을 보존하려고 중단합니다: {output}")
    model = YOLO(str(model_path))
    raw_names = getattr(model, "names", {})
    names = list(raw_names.values()) if isinstance(raw_names, dict) else list(raw_names)
    if "person" not in names:
        raise ValueError("단일 모델에 person 클래스가 없습니다. 통합 모델 학습부터 완료하세요.")

    export_args = {
        "format": export_format,
        "imgsz": imgsz,
        "dynamic": False,
        "simplify": True,
    }
    if export_format == "onnx":
        # Pi의 OpenCV 4.6 DNN과 호환되는 보수적인 opset을 사용한다.
        export_args["opset"] = 12
    exported = Path(model.export(**export_args))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True)
    if exported.is_dir():
        for path in exported.iterdir():
            if path.is_file():
                shutil.copy2(path, output / path.name)
    else:
        shutil.copy2(exported, output / f"model{exported.suffix.lower()}")
    artifacts = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": export_format,
        "input_size": imgsz,
        "source_model": model_path.name,
        "source_model_sha256": sha256(model_path),
        "classes": names,
        "artifacts": artifacts,
    }
    (output / "model_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--format", choices=("onnx", "ncnn"), default="ncnn")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--imgsz", type=int, default=320)
    args = parser.parse_args()
    output = args.output or (
        DEFAULT_OUTPUT_ROOT / f"lab_guardian_physical_ai_{args.format}"
    )
    print(export_model(args.model, output, args.imgsz, args.format))


if __name__ == "__main__":
    main()
