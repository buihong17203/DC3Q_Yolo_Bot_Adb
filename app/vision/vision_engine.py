from __future__ import annotations

from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Iterable

import numpy as np

from .screenshot import ScreenshotCapture, ScreenshotFrame
from .template_matcher import TemplateMatch, TemplateMatcher
from .yolo_detector import Detection, YOLODetector


class VisionEngine:
    """Single entry point used by automation for all screen perception."""

    def __init__(
        self,
        device,
        *,
        screenshot: ScreenshotCapture | None = None,
        template_matcher: TemplateMatcher | None = None,
        yolo_detector: YOLODetector | None = None,
        template_dir: str | Path | None = None,
        frame_cache_seconds: float = 0.0,
    ) -> None:
        self.device = device
        self.screenshot = screenshot or ScreenshotCapture(device)
        self.template_matcher = template_matcher or TemplateMatcher()
        self.yolo_detector = yolo_detector
        self.template_dir = Path(template_dir).expanduser().resolve() if template_dir else None
        self.frame_cache_seconds = max(0.0, float(frame_cache_seconds))

        self._last_frame: ScreenshotFrame | None = None
        self._last_capture_monotonic = 0.0
        self._lock = RLock()

    @property
    def last_frame(self) -> ScreenshotFrame | None:
        return self._last_frame

    @property
    def yolo_available(self) -> bool:
        return self.yolo_detector is not None and self.yolo_detector.available

    def resolve_template(self, template: str | Path) -> Path:
        path = Path(template).expanduser()
        if path.is_absolute() or self.template_dir is None:
            return path
        return self.template_dir / path

    def capture(self, force: bool = True) -> ScreenshotFrame:
        with self._lock:
            now = monotonic()
            if (
                not force
                and self._last_frame is not None
                and now - self._last_capture_monotonic <= self.frame_cache_seconds
            ):
                return self._last_frame

            self._last_frame = self.screenshot.capture()
            self._last_capture_monotonic = now
            return self._last_frame

    def _image(self, frame: ScreenshotFrame | np.ndarray | None, refresh: bool) -> np.ndarray:
        if isinstance(frame, ScreenshotFrame):
            return frame.image
        if isinstance(frame, np.ndarray):
            return frame
        return self.capture(force=refresh).image

    def find_template(
        self,
        template: str | Path,
        *,
        threshold: float | None = None,
        roi: tuple[int, int, int, int] | None = None,
        scales: Iterable[float] | None = None,
        frame: ScreenshotFrame | np.ndarray | None = None,
        refresh: bool = True,
    ) -> TemplateMatch | None:
        image = self._image(frame, refresh)
        return self.template_matcher.find_best(
            image=image,
            template=self.resolve_template(template),
            threshold=threshold,
            roi=roi,
            scales=scales,
        )

    def find_all_templates(
        self,
        template: str | Path,
        *,
        threshold: float | None = None,
        roi: tuple[int, int, int, int] | None = None,
        scales: Iterable[float] | None = None,
        max_results: int = 20,
        frame: ScreenshotFrame | np.ndarray | None = None,
        refresh: bool = True,
    ) -> list[TemplateMatch]:
        image = self._image(frame, refresh)
        return self.template_matcher.find_all(
            image=image,
            template=self.resolve_template(template),
            threshold=threshold,
            roi=roi,
            scales=scales,
            max_results=max_results,
        )

    def exists(self, template: str | Path, **kwargs) -> bool:
        return self.find_template(template, **kwargs) is not None

    def detect(
        self,
        class_name: str | int | Iterable[str | int] | None = None,
        *,
        confidence: float | None = None,
        iou: float | None = None,
        roi: tuple[int, int, int, int] | None = None,
        max_results: int | None = None,
        frame: ScreenshotFrame | np.ndarray | None = None,
        refresh: bool = True,
    ) -> list[Detection]:
        if self.yolo_detector is None or not self.yolo_detector.available:
            return []
        image = self._image(frame, refresh)
        return self.yolo_detector.detect(
            image=image,
            class_filter=class_name,
            confidence=confidence,
            iou=iou,
            roi=roi,
            max_results=max_results,
        )

    def detect_one(self, class_name: str | int | None = None, **kwargs) -> Detection | None:
        detections = self.detect(class_name, max_results=1, **kwargs)
        return detections[0] if detections else None

    def yolo_exists(self, class_name: str | int | None = None, **kwargs) -> bool:
        return self.detect_one(class_name, **kwargs) is not None

    def save_last(self, path: str | Path) -> Path:
        if self._last_frame is None:
            self.capture(force=True)
        assert self._last_frame is not None
        return self.screenshot.save(self._last_frame.image, path)
