from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import logging

LOGGER = logging.getLogger("dc3q")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "img" / "yolo" / "yolo26n.pt"


def resolve_default_yolo_model() -> Path | None:
    """Tìm mô hình YOLO tốt nhất hiện có trong dự án (ưu tiên v26, sau đó v11)."""
    candidates = [
        PROJECT_ROOT / "data" / "img" / "yolo" / "dc3q_yolo26_best.pt",
        PROJECT_ROOT / "data" / "img" / "yolo" / "dc3q_yolo26_best.onnx",
        PROJECT_ROOT / "data" / "img" / "yolo" / "yolo26n.pt",
        PROJECT_ROOT / "data" / "img" / "yolo" / "dc3q_yolo11_best.pt",
        PROJECT_ROOT / "data" / "img" / "yolo" / "dc3q_yolo11_best.onnx",
        PROJECT_ROOT / "data" / "img" / "yolo" / "yolo11n.pt",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return DEFAULT_MODEL_PATH if DEFAULT_MODEL_PATH.is_file() else None


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
    def box(self) -> tuple[int, int, int, int]:
        return int(self.x1), int(self.y1), int(self.x2), int(self.y2)

    @property
    def center(self) -> tuple[int, int]:
        return int((self.x1 + self.x2) / 2), int((self.y1 + self.y2) / 2)

    @property
    def width(self) -> int:
        return int(self.x2 - self.x1)

    @property
    def height(self) -> int:
        return int(self.y2 - self.y1)


class YoloDetector:
    """YOLO Detection Adapter hỗ trợ YOLO26 (YOLOv26) và các thế hệ YOLO trước.
    Tối ưu hóa chạy CPU/ONNX cho bot giả lập.
    """

    def __init__(self, model_path: str | Path | None = None):
        self.model_path = Path(model_path) if model_path else resolve_default_yolo_model()
        self.model = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def load(self) -> YoloDetector:
        if self.model_path is None or not self.model_path.exists():
            resolved = resolve_default_yolo_model()
            if resolved and resolved.exists():
                self.model_path = resolved
            else:
                raise ValueError(f"Không tìm thấy model_path: {self.model_path}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Cần cài đặt ultralytics: pip install ultralytics") from exc

        LOGGER.info("YOLO | Đang nạp mô hình: %s", self.model_path)
        self.model = YOLO(str(self.model_path))
        return self

    def predict(self, image: Any, confidence: float = 0.25, imgsz: int = 640) -> list[YoloDetection]:
        if self.model is None:
            self.load()
        results = self.model.predict(image, conf=confidence, imgsz=imgsz, verbose=False)
        out: list[YoloDetection] = []
        for result in results:
            names = result.names
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for b in boxes:
                xyxy = b.xyxy[0].tolist()
                cls = int(b.cls[0])
                conf = float(b.conf[0])
                label_name = str(names.get(cls, cls)) if isinstance(names, dict) else str(names[cls])
                out.append(YoloDetection(cls, label_name, conf, *xyxy))
        return out

    def find_first(self, image: Any, label: str, confidence: float = 0.25) -> YoloDetection | None:
        """Tìm đối tượng đầu tiên khớp với nhãn yêu cầu."""
        detections = self.predict(image, confidence=confidence)
        label_lower = label.lower()
        for det in detections:
            if det.label.lower() == label_lower:
                return det
        return None

    def find_all(self, image: Any, label: str, confidence: float = 0.25) -> list[YoloDetection]:
        """Tìm tất cả đối tượng khớp với nhãn yêu cầu."""
        detections = self.predict(image, confidence=confidence)
        label_lower = label.lower()
        return [det for det in detections if det.label.lower() == label_lower]
