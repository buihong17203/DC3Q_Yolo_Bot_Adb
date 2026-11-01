from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from app.vision.template import TemplateMatcher


TESSERACT = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _pixels(screen) -> np.ndarray:
    value = screen.data if hasattr(screen, "data") else screen
    if hasattr(value, "convert"):
        return np.asarray(value.convert("RGB"))
    return np.asarray(value)


def read_balance_near_icon(
    screen,
    icon: str | Path,
    number_offset: tuple[int, int, int, int],
    *,
    search_roi: tuple[int, int, int, int] | None = None,
    threshold: float = 0.75,
) -> int:
    """Locate a supplied HUD icon, then OCR only its adjacent digit ROI."""
    pixels = _pixels(screen)
    ox = oy = 0
    source = screen
    if search_roi is not None:
        x1, y1, x2, y2 = search_roi
        source = pixels[y1:y2, x1:x2]
        ox, oy = x1, y1
    match = TemplateMatcher().match(source, icon, threshold)
    if not match.found:
        raise RuntimeError(f"Không thấy icon số dư: {Path(icon).name} ({match.confidence:.3f})")
    dx1, dy1, dx2, dy2 = number_offset
    x1, y1 = ox + match.x + dx1, oy + match.y + dy1
    x2, y2 = ox + match.x + dx2, oy + match.y + dy2
    roi = pixels[max(0, y1):min(pixels.shape[0], y2), max(0, x1):min(pixels.shape[1], x2)]
    if roi.size == 0:
        raise RuntimeError("ROI số dư rỗng")
    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY) if roi.ndim == 3 else roi
    enlarged = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    values: list[str] = []
    try:
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(roi)
        for entry in result or []:
            text = "".join(re.findall(r"\d+", entry[1]))
            if text and float(entry[2]) >= 0.80:
                values.extend([text, text])
    except Exception:
        pass
    for image in (enlarged, binary, cv2.bitwise_not(binary)):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            path = Path(handle.name)
        try:
            cv2.imencode(".png", image)[1].tofile(str(path))
            result = subprocess.run(
                [TESSERACT, str(path), "stdout", "--psm", "7", "-c", "tessedit_char_whitelist=0123456789"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            values.append("".join(re.findall(r"\d+", result.stdout)))
        finally:
            path.unlink(missing_ok=True)
    candidates = [value for value in values if value]
    if not candidates:
        raise RuntimeError(f"Không đọc được số cạnh icon {Path(icon).name}")
    value = max(set(candidates), key=lambda item: (candidates.count(item), len(item)))
    return int(value)
