from __future__ import annotations
from dataclasses import dataclass
import logging
from pathlib import Path
from .template import TemplateMatcher, MatchResult

LOGGER = logging.getLogger("dc3q")

@dataclass
class Detection:
    name: str
    match: MatchResult

class VisionDetector:
    def __init__(self, matcher: TemplateMatcher | None = None):
        self.matcher = matcher or TemplateMatcher()
    def find_template(self, screen, name: str, template, threshold: float = 0.85) -> Detection:
        match = self.matcher.match(screen, template, threshold)
        template_label = str(Path(template).resolve()) if isinstance(template, (str, Path)) else "<ảnh trong bộ nhớ>"
        LOGGER.info(
            "VISION | ảnh_hiện_tại=<ADB frame mới nhất> vs mẫu=%s | mục_đích=%s | "
            "độ_khớp=%.3f | ngưỡng=%.3f | nhận_diện=%s | kết_luận=%s | "
            "vị_trí=(%d,%d,%d,%d)",
            template_label, name, match.confidence, threshold,
            "CÓ" if match.found else "KHÔNG",
            "ĐẠT NGƯỠNG" if match.found else "KHÔNG ĐẠT NGƯỠNG",
            match.x, match.y, match.width, match.height,
        )
        return Detection(name, match)
