from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import logging

LOGGER = logging.getLogger("dc3q.yolo")

DEFAULT_MODEL_PATH = Path("data/img/yolo/yolo11n.pt")
BEST_MODEL_PATH = Path("data/img/yolo/dc3q_yolo11_best.pt")
BEST_ONNX_PATH = Path("data/img/yolo/dc3q_yolo11_best.onnx")
RUNS_BEST_PATH = Path("data/img/yolo/runs/dc3q_yolo11/weights/best.pt")


def resolve_default_yolo_model() -> Path | None:
    """Tự động ưu tiên ONNX runtime (nhanh nhất trên CPU ~170ms), sau đó đến fine-tune PyTorch (best.pt), cuối cùng là base weights."""
    if BEST_ONNX_PATH.exists():
        return BEST_ONNX_PATH
    if BEST_MODEL_PATH.exists():
        return BEST_MODEL_PATH
    if RUNS_BEST_PATH.exists():
        return RUNS_BEST_PATH
    if DEFAULT_MODEL_PATH.exists():
        return DEFAULT_MODEL_PATH
    return None


@dataclass
class YoloDetection:
    class_id: int
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def center(self) -> tuple[int, int]:
        """Tọa độ tâm (x, y) nguyên để click ADB."""
        return int(round(self.center_x)), int(round(self.center_y))

    @property
    def box(self) -> tuple[int, int, int, int]:
        """Tọa độ hộp (x1, y1, x2, y2) nguyên."""
        return int(round(self.x1)), int(round(self.y1)), int(round(self.x2)), int(round(self.y2))


class YoloDetector:
    """YOLO11 / YOLO Object Detector adapter boundary.
    Hỗ trợ phát hiện đối tượng game UI, quái, vật phẩm trên màn hình ADB.
    """

    def __init__(self, model_path: str | Path | None = None, device: str | None = None):
        self.model_path = Path(model_path) if model_path else resolve_default_yolo_model()
        self.device = device
        self.model = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def load(self, model_path: str | Path | None = None) -> YoloDetector:
        if model_path:
            self.model_path = Path(model_path)
        if self.model_path is None:
            raise ValueError("Chưa cấu hình model_path cho YOLO11")

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Cần cài đặt ultralytics để chạy YOLO: pip install ultralytics") from exc

        LOGGER.info("Đang nạp mô hình YOLO11 từ: %s", self.model_path)
        self.model = YOLO(str(self.model_path))
        return self

    def predict(
        self,
        image: Any,
        confidence: float = 0.25,
        iou: float = 0.45,
        device: str | None = None,
        imgsz: int = 640,
    ) -> list[YoloDetection]:
        if self.model is None:
            raise RuntimeError("YOLO model chưa load. Vui lòng gọi detector.load() trước.")

        pred_device = device if device is not None else self.device
        results = self.model.predict(
            image,
            conf=confidence,
            iou=iou,
            device=pred_device,
            imgsz=imgsz,
            verbose=False,
        )

        detections: list[YoloDetection] = []
        for result in results:
            names = result.names
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for b in boxes:
                raw_xyxy = b.xyxy[0]
                xyxy = raw_xyxy.tolist() if hasattr(raw_xyxy, "tolist") else list(raw_xyxy)
                cls = int(b.cls[0])
                conf = float(b.conf[0])
                label = str(names.get(cls, cls)) if isinstance(names, dict) else str(names[cls])
                detections.append(YoloDetection(cls, label, conf, *xyxy))

        return detections

    def find_by_label(
        self,
        image: Any,
        label: str,
        confidence: float = 0.25,
    ) -> list[YoloDetection]:
        """Lọc danh sách các đối tượng khớp với label cụ thể."""
        all_dets = self.predict(image, confidence=confidence)
        label_lower = label.strip().lower()
        return [d for d in all_dets if d.label.lower() == label_lower]

    def find_first(
        self,
        image: Any,
        label: str,
        confidence: float = 0.25,
    ) -> YoloDetection | None:
        """Tìm đối tượng đầu tiên khớp label (hoặc có độ tin cậy cao nhất)."""
        matches = self.find_by_label(image, label, confidence=confidence)
        if not matches:
            return None
        return max(matches, key=lambda d: d.confidence)
