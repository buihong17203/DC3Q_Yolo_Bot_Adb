from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Iterable

import cv2
import numpy as np

from .screenshot import ScreenshotCapture


class TemplateMatcherError(RuntimeError):
    """Raised when template matching cannot be performed."""


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    template: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    center: tuple[int, int]
    scale: float = 1.0

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


class TemplateMatcher:
    """OpenCV template matching with cache, ROI and multi-scale support."""

    def __init__(
        self,
        default_threshold: float = 0.85,
        grayscale: bool = True,
        method: int = cv2.TM_CCOEFF_NORMED,
        default_scales: Iterable[float] = (1.0,),
    ) -> None:
        if not 0.0 <= default_threshold <= 1.0:
            raise ValueError("default_threshold must be between 0 and 1")

        self.default_threshold = float(default_threshold)
        self.grayscale = bool(grayscale)
        self.method = int(method)
        self.default_scales = tuple(float(s) for s in default_scales if float(s) > 0)
        if not self.default_scales:
            self.default_scales = (1.0,)

        self._cache: dict[Path, tuple[int, np.ndarray]] = {}
        self._lock = RLock()

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _read_template(self, template: str | Path | np.ndarray) -> tuple[str, np.ndarray]:
        if isinstance(template, np.ndarray):
            return "<ndarray>", self._normalize_image(template)

        path = Path(template).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Template not found: {path}")

        mtime_ns = path.stat().st_mtime_ns
        with self._lock:
            cached = self._cache.get(path)
            if cached and cached[0] == mtime_ns:
                return str(path), cached[1]

        # cv2.imread cannot reliably open Unicode Windows paths.
        encoded = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise TemplateMatcherError(f"OpenCV could not read template: {path}")
        image = self._normalize_image(image)

        with self._lock:
            self._cache[path] = (mtime_ns, image)
        return str(path), image

    def _normalize_image(self, image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            normalized = image
        elif image.ndim == 3 and image.shape[2] == 4:
            normalized = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        elif image.ndim == 3 and image.shape[2] == 3:
            normalized = image
        else:
            raise TemplateMatcherError(f"Unsupported image shape: {image.shape!r}")

        if self.grayscale and normalized.ndim == 3:
            normalized = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
        elif not self.grayscale and normalized.ndim == 2:
            normalized = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)

        return np.ascontiguousarray(normalized)

    @staticmethod
    def _resize(template: np.ndarray, scale: float) -> np.ndarray:
        if scale == 1.0:
            return template
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
        resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=interpolation)
        if resized.size == 0:
            raise TemplateMatcherError(f"Template became empty at scale={scale}")
        return resized

    def find_best(
        self,
        image: np.ndarray,
        template: str | Path | np.ndarray,
        threshold: float | None = None,
        roi: tuple[int, int, int, int] | None = None,
        scales: Iterable[float] | None = None,
    ) -> TemplateMatch | None:
        threshold = self.default_threshold if threshold is None else float(threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")

        template_name, template_image = self._read_template(template)
        source, offset = ScreenshotCapture.crop(image, roi)
        source = self._normalize_image(source)
        offset_x, offset_y = offset

        best: TemplateMatch | None = None
        for scale in tuple(scales or self.default_scales):
            scale = float(scale)
            if scale <= 0:
                continue

            candidate = self._resize(template_image, scale)
            th, tw = candidate.shape[:2]
            sh, sw = source.shape[:2]
            if tw > sw or th > sh:
                continue

            result = cv2.matchTemplate(source, candidate, self.method)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if self.method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
                raw_score = float(min_val)
                confidence = 1.0 - raw_score if self.method == cv2.TM_SQDIFF_NORMED else 1.0 / (1.0 + raw_score)
                loc = min_loc
            else:
                confidence = float(max_val)
                loc = max_loc

            if confidence < threshold:
                continue

            x1 = int(loc[0] + offset_x)
            y1 = int(loc[1] + offset_y)
            x2 = x1 + tw
            y2 = y1 + th
            match = TemplateMatch(
                template=template_name,
                confidence=confidence,
                bbox=(x1, y1, x2, y2),
                center=(x1 + tw // 2, y1 + th // 2),
                scale=scale,
            )
            if best is None or match.confidence > best.confidence:
                best = match

        return best

    def find_all(
        self,
        image: np.ndarray,
        template: str | Path | np.ndarray,
        threshold: float | None = None,
        roi: tuple[int, int, int, int] | None = None,
        scales: Iterable[float] | None = None,
        max_results: int = 20,
        nms_iou: float = 0.30,
    ) -> list[TemplateMatch]:
        if max_results <= 0:
            return []

        threshold = self.default_threshold if threshold is None else float(threshold)
        template_name, template_image = self._read_template(template)
        source, offset = ScreenshotCapture.crop(image, roi)
        source = self._normalize_image(source)
        offset_x, offset_y = offset

        matches: list[TemplateMatch] = []
        for scale in tuple(scales or self.default_scales):
            scale = float(scale)
            if scale <= 0:
                continue

            candidate = self._resize(template_image, scale)
            th, tw = candidate.shape[:2]
            sh, sw = source.shape[:2]
            if tw > sw or th > sh:
                continue

            result = cv2.matchTemplate(source, candidate, self.method)
            if self.method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
                if self.method == cv2.TM_SQDIFF_NORMED:
                    confidence_map = 1.0 - result
                else:
                    confidence_map = 1.0 / (1.0 + result)
            else:
                confidence_map = result

            ys, xs = np.where(confidence_map >= threshold)
            if len(xs) == 0:
                continue

            scores = confidence_map[ys, xs]
            order = np.argsort(scores)[::-1][: max(max_results * 20, 200)]
            for idx in order:
                x1 = int(xs[idx] + offset_x)
                y1 = int(ys[idx] + offset_y)
                x2 = x1 + tw
                y2 = y1 + th
                matches.append(
                    TemplateMatch(
                        template=template_name,
                        confidence=float(scores[idx]),
                        bbox=(x1, y1, x2, y2),
                        center=(x1 + tw // 2, y1 + th // 2),
                        scale=scale,
                    )
                )

        matches.sort(key=lambda item: item.confidence, reverse=True)
        return self._nms(matches, nms_iou, max_results)

    def match(self, *args, **kwargs) -> TemplateMatch | None:
        return self.find_best(*args, **kwargs)

    @staticmethod
    def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        intersection = iw * ih
        if intersection <= 0:
            return 0.0
        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
        union = area_a + area_b - intersection
        return intersection / union if union > 0 else 0.0

    @classmethod
    def _nms(
        cls,
        matches: list[TemplateMatch],
        iou_threshold: float,
        limit: int,
    ) -> list[TemplateMatch]:
        kept: list[TemplateMatch] = []
        for match in matches:
            if all(cls._iou(match.bbox, existing.bbox) < iou_threshold for existing in kept):
                kept.append(match)
                if len(kept) >= limit:
                    break
        return kept
