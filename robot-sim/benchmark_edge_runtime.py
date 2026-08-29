"""Ultralytics/PyTorch 없이 Raspberry Pi용 ONNX 런타임을 실측한다."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from edge_inference import NcnnYoloBackend, OpenCVDnnYoloBackend


def percentile(values, ratio):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def collect_images(source: Path):
    if source.is_file():
        return [source]
    return sorted(
        path for path in source.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--runtime", choices=("onnx", "ncnn"), default="ncnn")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    image_files = collect_images(args.source)
    frames = [cv2.imread(str(path)) for path in image_files]
    frames = [frame for frame in frames if frame is not None]
    if not frames:
        raise FileNotFoundError(f"벤치마크 이미지를 읽을 수 없습니다: {args.source}")

    if args.runtime == "ncnn":
        backend = NcnnYoloBackend.from_manifest(
            args.model_dir, confidence=args.confidence, num_threads=args.threads
        )
        runtime_name = "ncnn"
    else:
        backend = OpenCVDnnYoloBackend.from_manifest(
            args.model_dir, confidence=args.confidence
        )
        runtime_name = "opencv-dnn-onnx"
    for index in range(args.warmup):
        backend.detect(frames[index % len(frames)])

    elapsed_ms = []
    detection_counts = []
    for index in range(args.iterations):
        started = time.perf_counter()
        detections = backend.detect(frames[index % len(frames)])
        elapsed_ms.append((time.perf_counter() - started) * 1000.0)
        detection_counts.append(len(detections))

    mean_ms = statistics.fmean(elapsed_ms)
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime_name,
        "opencv_version": cv2.__version__,
        "model_dir": str(args.model_dir.resolve()),
        "images": len(frames),
        "iterations": args.iterations,
        "threads": args.threads if args.runtime == "ncnn" else None,
        "latency_ms": {
            "mean": round(mean_ms, 3),
            "median": round(statistics.median(elapsed_ms), 3),
            "p95": round(percentile(elapsed_ms, 0.95), 3),
            "min": round(min(elapsed_ms), 3),
            "max": round(max(elapsed_ms), 3),
        },
        "fps_from_mean_latency": round(1000.0 / mean_ms, 3),
        "mean_detections": round(statistics.fmean(detection_counts), 3),
        "note": "전처리, OpenCV DNN 추론, NMS 후처리를 포함하며 카메라 캡처와 웹 스트리밍은 제외한다.",
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
