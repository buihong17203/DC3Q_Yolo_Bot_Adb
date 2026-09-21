from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

import numpy as np

from .screenshot import ScreenshotCapture


class YOLODetectorError(RuntimeError):
    """Raised when the YOLO model cannot be loaded or used."""


@dataclass(frozen=True, slots=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    center: tuple[int, int]

    @property
    def x(self) -> int:
        return self.center[0]

    @property
    def y(self) -> int:
        return self.center[1]

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]


class YOLODetector:
    """Lazy Ultralytics YOLO detector suitable for one worker/device instance."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        confidence: float = 0.50,
        iou: float = 0.45,
        device: str | int | None = None,
        image_size: int | tuple[int, int] | None = None,
        enabled: bool = True,
    ) -> None:
        self.model_path = Path(model_path).expanduser() if model_path else None
        self.confidence = float(confidence)
        self.iou = float(iou)
        self.device = device
        self.image_size = image_size
        self.enabled = bool(enabled)

        self._model: Any | None = None
        self._lock = RLock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def available(self) -> bool:
        return self.enabled and self.model_path is not None

    def load(self) -> Any:
        if not self.enabled:
            raise YOLODetectorError("YOLO detector is disabled")
        if self.model_path is None:
            raise YOLODetectorError("YOLO model_path is not configured")
        if not self.model_path.is_file():
            raise FileNotFoundError(f"YOLO model not found: {self.model_path}")

        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise YOLODetectorError(
                    "Ultralytics is not installed. Install the project's requirements first."
                ) from exc

            try:
                self._model = YOLO(str(self.model_path))
            except Exception as exc:
                raise YOLODetectorError(f"Unable to load YOLO model {self.model_path}: {exc}") from exc
            return self._model

    @staticmethod
    def _normalize_names(names: Any) -> dict[int, str]:
        if isinstance(names, dict):
            return {int(k): str(v) for k, v in names.items()}
        if isinstance(names, (list, tuple)):
            return {idx: str(value) for idx, value in enumerate(names)}
        return {}

    @staticmethod
    def _class_filter(
        class_filter: str | int | Iterable[str | int] | None,
    ) -> set[str | int] | None:
        if class_filter is None:
            return None
        if isinstance(class_filter, (str, int)):
            return {class_filter}
        return set(class_filter)

    def detect(
        self,
        image: np.ndarray,
        class_filter: str | int | Iterable[str | int] | None = None,
        confidence: float | None = None,
        iou: float | None = None,
        roi: tuple[int, int, int, int] | None = None,
        max_results: int | None = None,
    ) -> list[Detection]:
        model = self.load()
        source, offset = ScreenshotCapture.crop(image, roi)
        offset_x, offset_y = offset

        predict_args: dict[str, Any] = {
            "source": source,
            "conf": self.confidence if confidence is None else float(confidence),
            "iou": self.iou if iou is None else float(iou),
            "verbose": False,
        }
        if self.device is not None:
            predict_args["device"] = self.device
        if self.image_size is not None:
            predict_args["imgsz"] = self.image_size

        try:
            results = model.predict(**predict_args)
        except Exception as exc:
            raise YOLODetectorError(f"YOLO inference failed: {exc}") from exc

        wanted = self._class_filter(class_filter)
        detections: list[Detection] = []

        for result in results:
            names = self._normalize_names(getattr(result, "names", None) or getattr(model, "names", None))
            boxes = getattr(result, "boxes", None)
            if boxes is None or len(boxes) == 0:
                continue

            xyxy = boxes.xyxy.detach().cpu().numpy()
            confs = boxes.conf.detach().cpu().numpy()
            classes = boxes.cls.detach().cpu().numpy().astype(int)

            for bbox_raw, conf_raw, class_id_raw in zip(xyxy, confs, classes):
                class_id = int(class_id_raw)
                class_name = names.get(class_id, str(class_id))
                if wanted is not None and class_id not in wanted and class_name not in wanted:
                    continue

                x1, y1, x2, y2 = (int(round(float(v))) for v in bbox_raw)
                x1 += offset_x
                x2 += offset_x
                y1 += offset_y
                y2 += offset_y

                detections.append(
                    Detection(
                        class_id=class_id,
                        class_name=class_name,
                        confidence=float(conf_raw),
                        bbox=(x1, y1, x2, y2),
                        center=((x1 + x2) // 2, (y1 + y2) // 2),
                    )
                )

        detections.sort(key=lambda item: item.confidence, reverse=True)
        if max_results is not None:
            detections = detections[: max(0, int(max_results))]
        return detections

    def detect_one(self, *args, **kwargs) -> Detection | None:
        kwargs["max_results"] = 1
        detections = self.detect(*args, **kwargs)
        return detections[0] if detections else None
