from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np


@dataclass
class ImageFrame:
    data: np.ndarray
    path: Path | None = None
    width: int = 0
    height: int = 0

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def shape(self) -> tuple[int, ...]:
        return self.data.shape

    def copy(self) -> ImageFrame:
        return ImageFrame(self.data.copy(), self.path, self.width, self.height)

    def save(self, target: str | Path) -> None:
        p = Path(target)
        p.parent.mkdir(parents=True, exist_ok=True)
        encoded = cv2.imencode(".png", cv2.cvtColor(self.data, cv2.COLOR_RGB2BGR))[1]
        encoded.tofile(str(p))


def load_image(source: str | Path | bytes | ImageFrame | np.ndarray) -> ImageFrame:
    """Decode screenshot/image using fast cv2.imdecode(np.frombuffer) in RAM instead of PIL.Image."""
    if isinstance(source, ImageFrame):
        return source
    if isinstance(source, np.ndarray):
        img = source
        path = None
    elif isinstance(source, (str, Path)):
        path = Path(source)
        try:
            img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        except FileNotFoundError:
            img = None
    elif isinstance(source, (bytes, bytearray)):
        arr = np.frombuffer(source, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        path = None
    elif hasattr(source, "data") and isinstance(source.data, np.ndarray):
        img = source.data
        path = getattr(source, "path", None)
    elif hasattr(source, "convert"):
        # PIL.Image fallback
        img = cv2.cvtColor(np.asarray(source.convert("RGB")), cv2.COLOR_RGB2BGR)
        path = None
    elif hasattr(source, "__array__"):
        img = np.asarray(source)
        path = None
    else:
        raise ValueError(f"Không hỗ trợ source type: {type(source)}")

    if img is None or img.size == 0:
        raise RuntimeError(f"Không decode được ảnh từ source: {type(source)}")
    # Preserve the project's historical ImageFrame contract: RGB pixels.
    if isinstance(source, (str, Path, bytes, bytearray)):
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    return ImageFrame(img, path, w, h)
