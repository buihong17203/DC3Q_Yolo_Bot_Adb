from __future__ import annotations

import logging
import unicodedata
from typing import Any
import numpy as np

LOGGER = logging.getLogger("dc3q")

_SHARED_RAPID_OCR: Any = None


def get_ocr_engine() -> Any:
    """Singleton provider for RapidOCR engine to avoid re-allocating ONNX sessions."""
    global _SHARED_RAPID_OCR
    if _SHARED_RAPID_OCR is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _SHARED_RAPID_OCR = RapidOCR()
            LOGGER.info("OCR | Khởi tạo RapidOCR singleton thành công (chia sẻ bộ nhớ)")
        except Exception as exc:
            LOGGER.warning("OCR | Không thể khởi tạo RapidOCR: %s", exc)
            return None
    return _SHARED_RAPID_OCR


def to_numpy_image(image: Any) -> np.ndarray:
    """Normalize various image representations to a numpy uint8 ndarray."""
    if hasattr(image, "data") and isinstance(image.data, np.ndarray):
        return image.data
    if hasattr(image, "convert") and not hasattr(image, "shape"):
        return np.asarray(image.convert("RGB"))
    if isinstance(image, np.ndarray):
        return image
    return np.asarray(image)


def ocr_extract_text(image: Any) -> str:
    """Fast text extraction using shared RapidOCR, normalized to lowercase ASCII."""
    engine = get_ocr_engine()
    if engine is None:
        return ""
    img = to_numpy_image(image)
    if img.size == 0:
        return ""
    try:
        result, _ = engine(img)
        text = " ".join(str(row[1]) for row in (result or []))
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    except Exception as exc:
        LOGGER.debug("OCR | Lỗi khi trích xuất chữ: %s", exc)
        return ""


def ocr_raw_results(image: Any) -> list[Any]:
    """Return raw RapidOCR rows: list of [bbox, text, score]."""
    engine = get_ocr_engine()
    if engine is None:
        return []
    img = to_numpy_image(image)
    if img.size == 0:
        return []
    try:
        result, _ = engine(img)
        return result or []
    except Exception as exc:
        LOGGER.debug("OCR | Lỗi khi chạy raw OCR: %s", exc)
        return []
