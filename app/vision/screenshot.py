from __future__ import annotations

import re
import threading
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
    """
    Capture screenshot từ thiết bị ADB.

    Quy tắc temp:
    - Mỗi thiết bị chỉ dùng đúng 1 file ảnh.
    - Tên file: temp_window_<device_serial>.png
    - Mỗi lần capture mới sẽ GHI ĐÈ file cũ của chính thiết bị đó.
    - Không sinh timestamp, counter hoặc hàng nghìn ảnh mới.
    """

    def __init__(
        self,
        device: ScreenshotDevice | Any,
        *,
        temp_dir: str | Path | None = None,
        persist_temp: bool = True,
    ) -> None:
        self.device = device
        self.persist_temp = bool(persist_temp)

        # Nếu file nằm ở app/vision/screenshot.py thì parents[2]
        # chính là thư mục gốc của project.
        project_root = Path(__file__).resolve().parents[2]

        self.temp_dir = (
            Path(temp_dir).expanduser().resolve()
            if temp_dir is not None
            else project_root / "temp"
        )

        self._write_lock = threading.Lock()

        if self.persist_temp:
            self.temp_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_serial(serial: str | None) -> str:
        """
        Chuyển serial ADB thành tên file an toàn.

        Ví dụ:
            emulator-5554  -> emulator_5554
            127.0.0.1:5555 -> 127_0_0_1_5555
        """
        value = str(serial or "unknown_device").strip()
        safe = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
        return safe or "unknown_device"

    @property
    def serial(self) -> str:
        return str(getattr(self.device, "serial", "unknown_device"))

    @property
    def temp_path(self) -> Path:
        """Đường dẫn ảnh temp cố định của thiết bị hiện tại."""
        return self.temp_dir / f"temp_window_{self._safe_serial(self.serial)}.png"

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
            raise ScreenshotError(
                f"Unsupported screenshot data type: {type(data)!r}"
            )

        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        elif image.ndim != 3 or image.shape[2] != 3:
            raise ScreenshotError(
                f"Unexpected screenshot shape: {image.shape!r}"
            )

        return np.ascontiguousarray(image)

    def _write_temp_window(self, image: np.ndarray) -> Path:
        """
        Ghi đè ảnh màn hình hiện tại của thiết bị.

        Cùng một serial luôn dùng cùng một file nên số lượng ảnh
        không tăng theo số lần capture.
        """
        target = self.temp_path

        with self._write_lock:
            target.parent.mkdir(parents=True, exist_ok=True)

            if not cv2.imwrite(str(target), image):
                raise ScreenshotError(
                    f"Unable to save temporary screenshot to {target}"
                )

        return target

    def capture(self) -> ScreenshotFrame:
        try:
            data = self.device.screenshot()
        except Exception as exc:
            raise ScreenshotError(
                f"Unable to capture screenshot: {exc}"
            ) from exc

        image = self.decode(data)
        serial = getattr(self.device, "serial", None)

        # Mỗi lần chụp mới ghi đè ảnh cũ của đúng thiết bị đó.
        if self.persist_temp:
            self._write_temp_window(image)

        return ScreenshotFrame(
            image=image,
            captured_at=time(),
            serial=serial,
        )

    def capture_image(self) -> np.ndarray:
        return self.capture().image

    def remove_temp_window(self) -> bool:
        """
        Xóa ảnh temp của riêng thiết bị này nếu cần.

        Không ảnh hưởng template hoặc ảnh của thiết bị khác.
        """
        target = self.temp_path

        try:
            target.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ScreenshotError(
                f"Unable to remove temporary screenshot {target}: {exc}"
            ) from exc

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
            raise ValueError(
                f"ROI is outside image bounds: "
                f"roi={roi}, image={image_w}x{image_h}"
            )

        return image[y1:y2, x1:x2], (x1, y1)

    @staticmethod
    def save(image: np.ndarray, path: str | Path) -> Path:
        """
        Lưu ảnh theo đường dẫn do caller chỉ định.

        Giữ nguyên để tương thích code cũ.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if not cv2.imwrite(str(target), image):
            raise ScreenshotError(
                f"Unable to save screenshot to {target}"
            )

        return target
