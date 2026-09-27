from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass
class YoloDetection:
    class_id: int
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

class YoloDetector:
    """Adapter boundary. Model loading/inference is intentionally optional and not auto-started."""
    def __init__(self, model_path: str | Path | None = None):
        self.model_path=Path(model_path) if model_path else None
        self.model=None
    def load(self):
        if self.model_path is None: raise ValueError("Chưa cấu hình model_path")
        try:
            from ultralytics import YOLO
        except ImportError as exc: raise RuntimeError("Cần cài ultralytics để chạy YOLO") from exc
        self.model=YOLO(str(self.model_path)); return self
    def predict(self, image: Any, confidence: float = 0.25) -> list[YoloDetection]:
        if self.model is None: raise RuntimeError("YOLO model chưa load")
        results=self.model.predict(image, conf=confidence, verbose=False)
        out=[]
        for result in results:
            names=result.names
            boxes=getattr(result,"boxes",None)
            if boxes is None: continue
            for b in boxes:
                xyxy=b.xyxy[0].tolist(); cls=int(b.cls[0]); conf=float(b.conf[0])
                out.append(YoloDetection(cls, str(names[cls]), conf, *xyxy))
        return out
