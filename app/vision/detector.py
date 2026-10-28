from __future__ import annotations
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any
from .template import TemplateMatcher, MatchResult

LOGGER = logging.getLogger("dc3q")

@dataclass
class Detection:
    name: str
    match: MatchResult

class VisionDetector:
    def __init__(self, matcher: TemplateMatcher | None = None, yolo: Any | None = None):
        self.matcher = matcher or TemplateMatcher()
        self.yolo = yolo

    def enable_yolo(self, model_path: str | Path | None = None, device: str | None = None):
        """Khởi tạo hoặc nạp bộ nhận diện YOLOv11."""
        if self.yolo is None:
            from .yolo import YoloDetector
            self.yolo = YoloDetector(model_path=model_path, device=device)
        if not self.yolo.is_loaded:
            self.yolo.load(model_path)
        return self.yolo

    def find_template(
        self,
        screen,
        name: str,
        template,
        threshold: float = 0.85,
        roi: tuple[int, int, int, int] | list[int] | None = None,
        max_color_dist: float | None = None,
        scales: list[float] | None = None,
    ) -> Detection:
        match = self.matcher.match(
            screen, template, threshold, roi=roi, max_color_dist=max_color_dist, scales=scales
        )
        template_label = str(Path(template).resolve()) if isinstance(template, (str, Path)) else "<ảnh trong bộ nhớ>"
        color_info = f" | color_diff={match.color_diff:.1f}" if match.color_diff > 0 else ""
        LOGGER.info(
            "VISION | ảnh_hiện_tại=<ADB frame mới nhất> vs mẫu=%s | mục_đích=%s | "
            "độ_khớp=%.3f | ngưỡng=%.3f%s | nhận_diện=%s | kết_luận=%s | "
            "vị_trí=(%d,%d,%d,%d)",
            template_label, name, match.confidence, threshold, color_info,
            "CÓ" if match.found else "KHÔNG",
            "ĐẠT NGƯỠNG" if match.found else "KHÔNG ĐẠT NGƯỠNG",
            match.x, match.y, match.width, match.height,
        )
        return Detection(name, match)

    def find_objects(
        self,
        screen: Any,
        label: str | None = None,
        confidence: float = 0.25,
    ) -> list[Any]:
        """Phát hiện các đối tượng động trên màn hình bằng YOLOv11."""
        detector = self.enable_yolo()
        if label:
            return detector.find_by_label(screen, label, confidence=confidence)
        return detector.predict(screen, confidence=confidence)

    def find_first_object(
        self,
        screen: Any,
        label: str,
        confidence: float = 0.25,
    ) -> Any | None:
        """Tìm đối tượng đầu tiên/tốt nhất khớp nhãn với YOLOv11."""
        detector = self.enable_yolo()
        return detector.find_first(screen, label, confidence=confidence)
