from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ImageFrame:
    data: object
    path: Path | None = None
    width: int = 0
    height: int = 0

def load_image(source: str | Path | bytes) -> ImageFrame:
    try:
        from PIL import Image
        import io
        if isinstance(source, (str, Path)):
            img = Image.open(source).convert("RGB")
            path = Path(source)
        else:
            img = Image.open(io.BytesIO(source)).convert("RGB")
            path = None
        return ImageFrame(img, path, img.width, img.height)
    except ImportError as exc:
        raise RuntimeError("Cần cài Pillow để dùng vision.image") from exc
