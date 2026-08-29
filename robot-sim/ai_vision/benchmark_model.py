"""PT/NCNN 모델의 지연과 처리량을 같은 입력으로 측정한다."""

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
from ultralytics import YOLO


def image_paths(source: Path):
    if source.is_file():
        return [source]
    return sorted(
        path for path in source.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )


def percentile(values, q):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def benchmark(model_path: Path, source: Path, imgsz: int, iterations: int, warmup: int):
    paths = image_paths(source)
    if not paths:
        raise FileNotFoundError(f"벤치마크 이미지를 찾지 못했습니다: {source}")
    model = YOLO(str(model_path))
    frames = []
    for path in paths:
        frame = cv2.imread(str(path))
        if frame is not None:
            frames.append(frame)
    if not frames:
        raise RuntimeError("OpenCV로 읽을 수 있는 이미지가 없습니다.")

    for index in range(warmup):
        model.predict(frames[index % len(frames)], imgsz=imgsz, verbose=False)

    durations_ms = []
    detection_counts = []
    for index in range(iterations):
        started = time.perf_counter()
        result = model.predict(frames[index % len(frames)], imgsz=imgsz, verbose=False)[0]
        durations_ms.append((time.perf_counter() - started) * 1000.0)
        detection_counts.append(0 if result.boxes is None else len(result.boxes))

    mean_ms = statistics.fmean(durations_ms)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path.resolve()),
        "input_size": imgsz,
        "warmup": warmup,
        "iterations": iterations,
        "images": len(frames),
        "latency_ms": {
            "mean": round(mean_ms, 3),
            "median": round(statistics.median(durations_ms), 3),
            "p95": round(percentile(durations_ms, 0.95), 3),
            "min": round(min(durations_ms), 3),
            "max": round(max(durations_ms), 3),
        },
        "fps_from_mean_latency": round(1000.0 / mean_ms, 3),
        "mean_detections": round(statistics.fmean(detection_counts), 3),
        "note": "Includes Ultralytics preprocessing, inference and postprocessing; excludes camera capture and streaming.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = benchmark(args.model, args.source, args.imgsz, args.iterations, args.warmup)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
