"""LabBot 실시간 객체 탐지 및 연구실 보안 순찰 AI 분석 엔진."""
import os
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple
from ultralytics import YOLO

from ai_vision.config import (
    TARGET_CLASSES,
    CLASS_METADATA,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_IOU_THRESHOLD,
)

MODELS_DIR = Path(__file__).resolve().parent / "models"
DEFAULT_MODEL_PATH = MODELS_DIR / "lab_guardian_yolo11.pt"
COCO_PERSON_MODEL_PATH = Path(__file__).resolve().parents[2] / "yolo11n.pt"


class LabPatrolDetector:
    """실시간 연구실 자산 및 안전 설비 탐지기."""

    def __init__(
        self,
        model_path: str = None,
        conf_thresh: float = DEFAULT_CONFIDENCE_THRESHOLD,
        iou_thresh: float = DEFAULT_IOU_THRESHOLD,
        imgsz: int = 320,
        enable_person_fallback: bool = True,
    ):
        self.conf_thresh = conf_thresh
        self.iou_thresh = iou_thresh
        self.imgsz = int(imgsz)

        # 1. 모델 로드 (학습된 가중치 없으면 기본 yolo11n.pt 사용)
        if model_path is None or not os.path.exists(model_path):
            if DEFAULT_MODEL_PATH.exists():
                chosen_path = str(DEFAULT_MODEL_PATH)
            else:
                chosen_path = "yolo11n.pt"
        else:
            chosen_path = model_path

        print(f"[LabPatrolDetector] Loading YOLO Model from: {chosen_path}")
        self.model = YOLO(chosen_path)
        self.person_model = None
        model_names = getattr(self.model, "names", {})
        if isinstance(model_names, dict):
            model_class_names = {str(value) for value in model_names.values()}
        else:
            model_class_names = {str(value) for value in model_names}
        has_person_class = "person" in model_class_names
        if enable_person_fallback and not has_person_class:
            person_path = str(COCO_PERSON_MODEL_PATH) if COCO_PERSON_MODEL_PATH.exists() else "yolo11n.pt"
            print(
                "[LabPatrolDetector] Unified model has no person class; "
                f"loading temporary fallback from: {person_path}"
            )
            self.person_model = YOLO(person_path)

    def detect(self, bgr_frame: np.ndarray) -> List[Dict[str, Any]]:
        """BGR 이미지 프레임에서 객체를 감지하고 탐지 목록을 반환한다."""
        if bgr_frame is None or bgr_frame.size == 0:
            return []

        results = self.model.predict(
            source=bgr_frame,
            conf=self.conf_thresh,
            iou=self.iou_thresh,
            imgsz=self.imgsz,
            verbose=False,
        )

        detections = self._convert_results(results)

        # 연구실 전용 모델에는 사람 클래스가 없으므로 COCO 모델을 병행한다.
        if self.person_model is not None:
            person_results = self.person_model.predict(
                source=bgr_frame,
                classes=[0],
                conf=max(0.30, self.conf_thresh),
                iou=self.iou_thresh,
                imgsz=self.imgsz,
                verbose=False,
            )
            detections.extend(self._convert_results(person_results, person_only=True))

        return detections

    def _convert_results(self, results, person_only: bool = False) -> List[Dict[str, Any]]:
        detections = []
        if not results:
            return detections
        r = results[0]
        if r.boxes is None:
            return detections
        for box in r.boxes:
            cls_id = int(box.cls[0].item())
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].tolist()

            # 클래스 이름 추출
            if hasattr(r, "names") and cls_id in r.names:
                cls_name = r.names[cls_id]
            elif cls_id < len(TARGET_CLASSES):
                cls_name = TARGET_CLASSES[cls_id]
            else:
                cls_name = f"class_{cls_id}"

            if person_only:
                if cls_name != "person":
                    continue
                meta = {"name_kr": "사람/침입자", "color": (0, 0, 255), "type": "SECURITY"}
            else:
                meta = CLASS_METADATA.get(
                    cls_name,
                    {"name_kr": cls_name, "color": (0, 255, 0), "type": "UNKNOWN"},
                )

            detections.append({
                "class_name": cls_name,
                "name_kr": meta["name_kr"],
                "type": meta["type"],
                "confidence": conf,
                "box": [int(v) for v in xyxy],  # [x1, y1, x2, y2]
                "color": meta["color"],
            })

        return detections

    def draw_detections(
        self,
        bgr_frame: np.ndarray,
        detections: List[Dict[str, Any]],
        show_hud: bool = True,
    ) -> np.ndarray:
        """탐지된 바운딩 박스와 사이버틱 HUD 오버레이를 렌더링한다."""
        out = bgr_frame.copy()
        h, w = out.shape[:2]

        safety_alerts = []

        for d in detections:
            x1, y1, x2, y2 = d["box"]
            color = d["color"]
            label = f"{d['name_kr']} {d['confidence']*100:.0f}%"

            # 1. 사이버틱 바운딩 박스 (테두리 + 코너 강조)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            corner_len = min(15, (x2 - x1) // 4, (y2 - y1) // 4)
            # 좌상단
            cv2.line(out, (x1, y1), (x1 + corner_len, y1), (255, 255, 255), 3)
            cv2.line(out, (x1, y1), (x1, y1 + corner_len), (255, 255, 255), 3)
            # 우상단
            cv2.line(out, (x2, y1), (x2 - corner_len, y1), (255, 255, 255), 3)
            cv2.line(out, (x2, y1), (x2, y1 + corner_len), (255, 255, 255), 3)
            # 좌하단
            cv2.line(out, (x1, y2), (x1 + corner_len, y2), (255, 255, 255), 3)
            cv2.line(out, (x1, y2), (x1, y2 - corner_len), (255, 255, 255), 3)
            # 우하단
            cv2.line(out, (x2, y2), (x2 - corner_len, y2), (255, 255, 255), 3)
            cv2.line(out, (x2, y2), (x2, y2 - corner_len), (255, 255, 255), 3)

            # 2. 라벨 뱃지 배경
            (lbl_w, lbl_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(out, (x1, max(0, y1 - 20)), (x1 + lbl_w + 6, max(20, y1)), color, -1)
            cv2.putText(
                out,
                label,
                (x1 + 3, max(14, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            if d["type"] == "SAFETY":
                safety_alerts.append(d["name_kr"])

        # 3. 상단 HUD 배너
        if show_hud:
            hud_bg = np.zeros((32, w, 3), dtype=np.uint8)
            cv2.rectangle(hud_bg, (0, 0), (w, 32), (20, 25, 30), -1)
            
            # 탐지 개수 표시
            asset_cnt = sum(1 for d in detections if d["type"] == "ASSET")
            safety_cnt = sum(1 for d in detections if d["type"] == "SAFETY")
            hud_text = f"AI VISION GUARD | ASSETS: {asset_cnt} | SAFETY/FACILITY: {safety_cnt}"
            cv2.putText(out, hud_text, (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 200), 1, cv2.LINE_AA)

        return out
