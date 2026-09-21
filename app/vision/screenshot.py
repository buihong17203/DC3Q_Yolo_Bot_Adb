from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any, Protocol, runtime_checkable

import cv2
import numpy as np


class ScreenshotError(RuntimeError):
    """Raised when a screenshot cannot be captured or decoded."""


@runtime_checkable
class ScreenshotDevice(Protocol):
    serial: str

    def screenshot(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ScreenshotFrame:
    """One decoded device screenshot in OpenCV BGR format."""

    image: np.ndarray
    captured_at: float
    serial: str | None = None

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    def copy(self) -> "ScreenshotFrame":
        return ScreenshotFrame(self.image.copy(), self.captured_at, self.serial)


class ScreenshotCapture:
    """Capture PNG bytes from ADBDevice and decode them into OpenCV images."""

    def __init__(self, device: ScreenshotDevice | Any) -> None:
        self.device = device

    @staticmethod
    def decode(data: bytes | bytearray | memoryview | np.ndarray) -> np.ndarray:
        if isinstance(data, np.ndarray):
            image = data.copy()
        elif isinstance(data, (bytes, bytearray, memoryview)):
            raw = np.frombuffer(data, dtype=np.uint8)
            if raw.size == 0:
                raise ScreenshotError("Screenshot data is empty")
            image = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ScreenshotError("OpenCV could not decode screenshot bytes")
        else:
            raise ScreenshotError(f"Unsupported screenshot data type: {type(data)!r}")

        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        elif image.ndim != 3 or image.shape[2] != 3:
            raise ScreenshotError(f"Unexpected screenshot shape: {image.shape!r}")

        return np.ascontiguousarray(image)

    def capture(self) -> ScreenshotFrame:
        try:
            data = self.device.screenshot()
        except Exception as exc:  # device-specific error is wrapped here
            raise ScreenshotError(f"Unable to capture screenshot: {exc}") from exc

        image = self.decode(data)
        serial = getattr(self.device, "serial", None)
        return ScreenshotFrame(image=image, captured_at=time(), serial=serial)

    def capture_image(self) -> np.ndarray:
        return self.capture().image

    @staticmethod
    def crop(
        image: np.ndarray,
        roi: tuple[int, int, int, int] | None,
    ) -> tuple[np.ndarray, tuple[int, int]]:
        """Crop x, y, width, height. Returns (crop, (offset_x, offset_y))."""
        if roi is None:
            return image, (0, 0)

        x, y, width, height = (int(v) for v in roi)
        if width <= 0 or height <= 0:
            raise ValueError("ROI width and height must be > 0")

        image_h, image_w = image.shape[:2]
        x1 = max(0, min(x, image_w))
        y1 = max(0, min(y, image_h))
        x2 = max(x1, min(x + width, image_w))
        y2 = max(y1, min(y + height, image_h))

        if x1 == x2 or y1 == y2:
            raise ValueError(f"ROI is outside image bounds: roi={roi}, image={image_w}x{image_h}")

        return image[y1:y2, x1:x2], (x1, y1)

    @staticmethod
    def save(image: np.ndarray, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(target), image):
            raise ScreenshotError(f"Unable to save screenshot to {target}")
        return target
