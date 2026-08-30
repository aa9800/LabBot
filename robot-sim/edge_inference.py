"""Raspberry Pi에서 실행하는 비동기 객체 인식 워커.

카메라 캡처·웹 스트리밍·모터 제어와 추론을 분리한다. 워커는 대기열을 만들지 않고
항상 가장 최신 프레임만 가져온다. 초기 운영 백엔드는 Pi에 이미 설치된 OpenCV DNN과
ONNX 모델이며, 동일 인터페이스로 NCNN 백엔드를 추가할 수 있다.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    box: List[int]


@dataclass(frozen=True)
class InferenceSnapshot:
    timestamp: float
    latency_ms: float
    detections: List[Detection]


class OpenCVDnnYoloBackend:
    """Ultralytics YOLO11 detect ONNX 출력용 OpenCV DNN 백엔드."""

    def __init__(
        self,
        model_path: str | Path,
        class_names: Sequence[str],
        input_size: int = 320,
        confidence: float = 0.40,
        iou: float = 0.45,
    ):
        self.model_path = Path(model_path)
        self.class_names = list(class_names)
        self.input_size = int(input_size)
        self.confidence = float(confidence)
        self.iou = float(iou)
        self.net = cv2.dnn.readNetFromONNX(str(self.model_path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    @classmethod
    def from_manifest(cls, model_dir: str | Path, confidence=0.40, iou=0.45):
        model_dir = Path(model_dir)
        manifest = json.loads((model_dir / "model_manifest.json").read_text(encoding="utf-8"))
        onnx_files = sorted(model_dir.glob("*.onnx"))
        if not onnx_files:
            raise FileNotFoundError(f"ONNX 모델 파일이 없습니다: {model_dir}")
        return cls(
            onnx_files[0],
            manifest["classes"],
            manifest.get("input_size", 320),
            confidence,
            iou,
        )

    def _letterbox(self, frame: np.ndarray):
        height, width = frame.shape[:2]
        scale = min(self.input_size / width, self.input_size / height)
        resized_width = max(1, round(width * scale))
        resized_height = max(1, round(height * scale))
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        pad_x = (self.input_size - resized_width) // 2
        pad_y = (self.input_size - resized_height) // 2
        canvas = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + resized_height, pad_x:pad_x + resized_width] = resized
        return canvas, scale, pad_x, pad_y

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if frame is None or frame.size == 0:
            return []
        prepared, scale, pad_x, pad_y = self._letterbox(frame)
        blob = cv2.dnn.blobFromImage(
            prepared, scalefactor=1.0 / 255.0, size=(self.input_size, self.input_size),
            swapRB=True, crop=False,
        )
        self.net.setInput(blob)
        output = self.net.forward()
        return _decode_yolo_output(
            output,
            self.class_names,
            self.confidence,
            self.iou,
            scale,
            pad_x,
            pad_y,
            frame.shape,
        )


class NcnnYoloBackend:
    """Pi 5에서 PyTorch 없이 실행하는 YOLO11 NCNN 백엔드."""

    def __init__(
        self,
        model_dir: str | Path,
        class_names: Sequence[str],
        input_size: int = 320,
        confidence: float = 0.40,
        iou: float = 0.45,
        num_threads: int = 2,
    ):
        try:
            import ncnn
        except ImportError as exc:
            raise RuntimeError(
                "NCNN 런타임이 없습니다. Raspberry Pi 후보 가상환경에 ncnn wheel을 설치하세요."
            ) from exc
        self._ncnn = ncnn
        self.model_dir = Path(model_dir)
        self.class_names = list(class_names)
        # 입력은 정사각형(int)일 수도, (가로, 세로) 직사각형일 수도 있다.
        # 카메라가 4:3인데 정사각형에 우겨넣으면 위아래 25%가 회색 여백으로
        # 낭비된다. 모델을 416x320 처럼 화면 비율에 맞춰 내보내면 그 낭비가
        # 사라진다 — 같은 유효 해상도를 더 싸게 얻는다.
        if isinstance(input_size, (tuple, list)):
            self.input_w, self.input_h = int(input_size[0]), int(input_size[1])
        else:
            self.input_w = self.input_h = int(input_size)
        self.input_size = self.input_w   # 기존 호출부 호환
        self.confidence = float(confidence)
        self.iou = float(iou)
        self.net = ncnn.Net()
        self.net.opt.num_threads = max(1, int(num_threads))
        param_path = self.model_dir / "model.ncnn.param"
        bin_path = self.model_dir / "model.ncnn.bin"
        if self.net.load_param(str(param_path)) != 0:
            raise RuntimeError(f"NCNN param 로드 실패: {param_path}")
        if self.net.load_model(str(bin_path)) != 0:
            raise RuntimeError(f"NCNN bin 로드 실패: {bin_path}")

    @classmethod
    def from_manifest(cls, model_dir: str | Path, confidence=0.40, iou=0.45, num_threads=2):
        model_dir = Path(model_dir)
        manifest = json.loads((model_dir / "model_manifest.json").read_text(encoding="utf-8"))
        # 직사각형으로 내보낸 모델은 input_wh: [가로, 세로] 를 싣는다.
        # 없으면 예전처럼 정사각형 input_size 를 쓴다.
        size = manifest.get("input_wh") or manifest.get("input_size", 320)
        return cls(
            model_dir,
            manifest["classes"],
            size,
            confidence,
            iou,
            num_threads,
        )

    def _letterbox(self, frame: np.ndarray):
        height, width = frame.shape[:2]
        scale = min(self.input_w / width, self.input_h / height)
        resized_width = max(1, round(width * scale))
        resized_height = max(1, round(height * scale))
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        pad_x = (self.input_w - resized_width) // 2
        pad_y = (self.input_h - resized_height) // 2
        canvas = np.full((self.input_h, self.input_w, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + resized_height, pad_x:pad_x + resized_width] = resized
        return canvas, scale, pad_x, pad_y

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if frame is None or frame.size == 0:
            return []
        prepared, scale, pad_x, pad_y = self._letterbox(frame)
        blob = cv2.dnn.blobFromImage(
            prepared, scalefactor=1.0 / 255.0, size=(self.input_w, self.input_h),
            swapRB=True, crop=False,
        )
        with self.net.create_extractor() as extractor:
            tensor = self._ncnn.Mat(np.ascontiguousarray(blob[0])).clone()
            if extractor.input("in0", tensor) != 0:
                raise RuntimeError("NCNN 입력 텐서 전달에 실패했습니다.")
            result_code, output = extractor.extract("out0")
            if result_code != 0:
                raise RuntimeError(f"NCNN 추론 실패: code={result_code}")
        return _decode_yolo_output(
            np.array(output),
            self.class_names,
            self.confidence,
            self.iou,
            scale,
            pad_x,
            pad_y,
            frame.shape,
        )


def _decode_yolo_output(
    output,
    class_names: Sequence[str],
    confidence_threshold: float,
    iou_threshold: float,
    scale: float,
    pad_x: int,
    pad_y: int,
    frame_shape,
) -> List[Detection]:
        predictions = np.squeeze(output)
        expected_channels = 4 + len(class_names)
        if predictions.ndim != 2:
            raise RuntimeError(f"예상하지 못한 YOLO 출력 shape: {output.shape}")
        if predictions.shape[0] == expected_channels:
            predictions = predictions.T
        elif predictions.shape[1] != expected_channels:
            raise RuntimeError(
                f"모델 클래스 수와 출력 shape가 다릅니다: {output.shape}, classes={len(class_names)}"
            )

        boxes_xywh = []
        confidences = []
        class_ids = []
        for row in predictions:
            scores = row[4:]
            class_id = int(np.argmax(scores))
            confidence = float(scores[class_id])
            if confidence < confidence_threshold:
                continue
            center_x, center_y, box_width, box_height = [float(value) for value in row[:4]]
            x = (center_x - box_width / 2.0 - pad_x) / scale
            y = (center_y - box_height / 2.0 - pad_y) / scale
            width = box_width / scale
            height = box_height / scale
            boxes_xywh.append([int(round(x)), int(round(y)), int(round(width)), int(round(height))])
            confidences.append(confidence)
            class_ids.append(class_id)

        if not boxes_xywh:
            return []
        kept = cv2.dnn.NMSBoxes(boxes_xywh, confidences, confidence_threshold, iou_threshold)
        if kept is None or len(kept) == 0:
            return []
        frame_height, frame_width = frame_shape[:2]
        detections = []
        for raw_index in np.array(kept).reshape(-1):
            index = int(raw_index)
            x, y, width, height = boxes_xywh[index]
            x1 = max(0, min(frame_width - 1, x))
            y1 = max(0, min(frame_height - 1, y))
            x2 = max(0, min(frame_width - 1, x + width))
            y2 = max(0, min(frame_height - 1, y + height))
            if x2 <= x1 or y2 <= y1:
                continue
            class_id = class_ids[index]
            detections.append(
                Detection(
                    class_id=class_id,
                    class_name=class_names[class_id],
                    confidence=confidences[index],
                    box=[x1, y1, x2, y2],
                )
            )
        return detections


class EdgeInferenceWorker:
    """최신 프레임만 추론하고 제어 루프와 완전히 분리된 워커."""

    def __init__(
        self,
        frame_provider: Callable[[], Optional[np.ndarray]],
        backend,
        target_fps: float = 15.0,
        result_callback=None,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.frame_provider = frame_provider
        self.backend = backend
        self.target_fps = max(0.5, float(target_fps))
        self.result_callback = result_callback
        self._clock = clock
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._latest: Optional[InferenceSnapshot] = None
        self._latencies = deque(maxlen=120)
        self._cycles = deque(maxlen=120)     # 콜백까지 포함한 한 주기 전체 시간
        self._completed_at = deque(maxlen=120)
        self._error = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="edge-inference", daemon=True)
        self._thread.start()

    def stop(self, timeout=3.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _run(self):
        interval = 1.0 / self.target_fps
        next_run = self._clock()
        while not self._stop.is_set():
            now = self._clock()
            if now < next_run:
                self._stop.wait(min(next_run - now, 0.05))
                continue
            frame = self.frame_provider()
            if frame is None:
                next_run = self._clock() + min(interval, 0.1)
                continue
            started = self._clock()
            try:
                detections = self.backend.detect(frame)
                finished = self._clock()
                latency_ms = (finished - started) * 1000.0
                snapshot = InferenceSnapshot(time.time(), latency_ms, detections)
                with self._lock:
                    self._latest = snapshot
                    self._latencies.append(latency_ms)
                    self._completed_at.append(finished)
                    self._error = None
                if self.result_callback is not None:
                    self.result_callback(snapshot, frame)
                # latency_ms 는 이 백엔드 하나의 시간이다. 콜백 안에서 두 번째
                # 모델(사람 판정)을 더 돌리는 구성이라, 그것까지 포함한 실제 한
                # 주기의 비용은 여기서 따로 잰다. 이 둘을 구분하지 않으면 로봇이
                # 실제보다 빠른 것처럼 보인다.
                cycle_end = self._clock()
                with self._lock:
                    self._cycles.append((cycle_end - started) * 1000.0)
                finished = cycle_end
            except Exception as exc:
                finished = self._clock()
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"
            # 처리 시간이 목표 간격보다 길면 밀린 프레임을 따라잡지 않고 즉시 최신 프레임으로 간다.
            next_run = max(next_run + interval, finished)

    def latest(self) -> Optional[InferenceSnapshot]:
        with self._lock:
            return self._latest

    def status(self) -> Dict:
        with self._lock:
            latencies = list(self._latencies)
            cycles = list(self._cycles)
            completed_at = list(self._completed_at)
            latest = self._latest
            error = self._error
        actual_fps = 0.0
        if len(completed_at) >= 2 and completed_at[-1] > completed_at[0]:
            actual_fps = (len(completed_at) - 1) / (completed_at[-1] - completed_at[0])
        result = {
            "running": bool(self._thread and self._thread.is_alive()),
            "target_fps": self.target_fps,
            "actual_fps": round(actual_fps, 2),
            "error": error,
        }
        if latencies:
            ordered = sorted(latencies)
            p95_index = min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))
            result["latency_ms"] = {
                "mean": round(statistics.fmean(latencies), 2),
                "p95": round(ordered[p95_index], 2),
            }
        if cycles:
            # 콜백(두 번째 모델·그리기·이벤트)까지 포함한 한 주기 전체 시간.
            ordered = sorted(cycles)
            p95_index = min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))
            result["cycle_ms"] = {
                "mean": round(statistics.fmean(cycles), 2),
                "p95": round(ordered[p95_index], 2),
            }
        if latest:
            result["latest"] = {
                **asdict(latest),
                "detections": [asdict(item) for item in latest.detections],
            }
        return result


# 글자가 읽히려면 대략 이 정도 가로폭은 있어야 한다. 이보다 작은 화면만
# 확대한다 — 카메라를 640x480으로 올린 뒤에는 확대가 낭비다.
MIN_LEGIBLE_WIDTH = 600


def draw_detections(frame: np.ndarray, detections: Sequence[Detection], scale: int | None = None):
    """탐지 박스와 라벨을 그린다.

    화면이 작으면(예전 320x240) 원본 위에 바로 글자를 쓰면 몇 픽셀짜리가 되어
    읽을 수 없다. 그래서 먼저 확대한 뒤 그린다 — 선과 글자가 확대 후 그려지므로
    계단현상이 없다(확대를 나중에 하면 그려둔 글자까지 같이 뭉개진다).

    scale 을 주지 않으면 화면 크기를 보고 알아서 정한다. 카메라를 640x480으로
    올리면 확대할 필요가 없어져 INTER_CUBIC 비용이 통째로 사라진다.
    추론은 원본 해상도로 하므로 정확도·속도에는 영향이 없다.
    """
    if scale is None:
        width = frame.shape[1] if frame is not None and frame.size else MIN_LEGIBLE_WIDTH
        scale = max(1, -(-MIN_LEGIBLE_WIDTH // max(1, width)))  # 올림 나눗셈
    if scale > 1:
        output = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    else:
        output = frame.copy()

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.45 * scale
    thickness = max(1, scale)

    for detection in detections:
        x1, y1, x2, y2 = (v * scale for v in detection.box)
        color = (0, 0, 255) if detection.class_name == "person" else (0, 220, 170)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, thickness)

        label = f"{detection.class_name} {detection.confidence:.0%}"
        (tw, th), base = cv2.getTextSize(label, font, font_scale, thickness)
        ty = max(th + 4, y1 - 4)
        # 글자 뒤에 색 띠를 깔아 배경이 밝든 어둡든 읽히게 한다.
        cv2.rectangle(output, (x1, ty - th - base), (x1 + tw + 4, ty + base), color, -1)
        cv2.putText(output, label, (x1 + 2, ty), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
    return output
