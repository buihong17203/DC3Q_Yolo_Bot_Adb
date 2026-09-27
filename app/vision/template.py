from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class MatchResult:
    found: bool
    confidence: float
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

class TemplateMatcher:
    def match(self, screen, template: str | Path, threshold: float = 0.85) -> MatchResult:
        """Match a template against a screenshot.

        Accepts ImageFrame, PIL.Image, numpy arrays, bytes, or a template path.
        Screenshots are normalized to a NumPy RGB/BGR-compatible array before
        OpenCV processing.
        """
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("Cần cài opencv-python và numpy để template matching") from exc

        # Unwrap ImageFrame-like objects first.
        if hasattr(screen, "data") and not isinstance(screen, np.ndarray):
            screen = screen.data

        # PIL.Image -> NumPy RGB array.
        if hasattr(screen, "convert") and hasattr(screen, "size") and not hasattr(screen, "shape"):
            screen = np.asarray(screen.convert("RGB"))
        elif isinstance(screen, (bytes, bytearray)):
            try:
                from PIL import Image
                import io
                screen = np.asarray(Image.open(io.BytesIO(screen)).convert("RGB"))
            except ImportError as exc:
                raise RuntimeError("Cần cài Pillow để đọc screenshot bytes") from exc
        elif hasattr(screen, "__array__"):
            screen = np.asarray(screen)

        if screen is None or not hasattr(screen, "shape"):
            raise ValueError("screen không hợp lệ: cần PIL.Image, numpy array, ImageFrame hoặc bytes")
        if screen.size == 0:
            raise ValueError("screen rỗng")

        if isinstance(template, (str, Path)):
            tpl = cv2.imread(str(template), cv2.IMREAD_COLOR)
        else:
            if hasattr(template, "convert") and hasattr(template, "size") and not hasattr(template, "shape"):
                template = np.asarray(template.convert("RGB"))
            tpl = np.asarray(template)

        if tpl is None or tpl.size == 0:
            raise FileNotFoundError(f"Không đọc được template: {template}")

        # Screenshot from PIL is RGB; OpenCV template loaded from disk is BGR.
        # Convert only the screenshot so both become grayscale consistently.
        if len(screen.shape) == 3:
            scr = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
        else:
            scr = screen
        gray_scr = cv2.cvtColor(scr, cv2.COLOR_BGR2GRAY) if len(scr.shape) == 3 else scr
        gray_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY) if len(tpl.shape) == 3 else tpl

        sh, sw = gray_scr.shape[:2]
        th, tw = gray_tpl.shape[:2]
        if th > sh or tw > sw:
            # Full-screen references may come from an older emulator viewport.
            # Scale only near-full-screen images; never distort control crops.
            if th >= sh * 0.9 and tw >= sw * 0.9:
                gray_tpl = cv2.resize(gray_tpl, (sw, sh), interpolation=cv2.INTER_AREA)
                th, tw = gray_tpl.shape[:2]
            else:
                return MatchResult(False, 0.0, 0, 0, tw, th)

        result = cv2.matchTemplate(gray_scr, gray_tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        return MatchResult(score >= threshold, float(score), int(loc[0]), int(loc[1]), tw, th)
