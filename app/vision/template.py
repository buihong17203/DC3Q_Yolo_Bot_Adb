from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np


@dataclass(frozen=True)
class MatchResult:
    found: bool
    confidence: float
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


# Bảng tọa độ ROI mặc định cho các nút cố định trên màn hình chuẩn 960x540.
# Tự động co giãn theo độ phân giải màn hình thực tế.
DEFAULT_FIXED_ROIS: dict[str, tuple[int, int, int, int]] = {
    # Nút Nội chính (HOME anchor): góc dưới bên phải
    "screen_noi-chinh": (720, 390, 960, 540),
    # Tab Đăng nhập: phía trên giữa
    "screen_tab_dang-nhap": (100, 50, 600, 220),
    # Nút Đăng nhập: phía dưới form đăng nhập
    "screen_button_dang-nhap": (280, 250, 700, 490),
    # Input tài khoản / mật khẩu
    "screen_input_tai-khoan": (250, 120, 720, 330),
    "screen_input_mat-khau": (250, 180, 720, 390),
    # Đăng xuất: Nút Tùy chọn (ở góc dưới bảng Thông tin của tôi)
    "screen_dx_ttct_button_open_tuychon": (580, 390, 960, 540),
    # Đăng xuất: Nút Cài đặt người dùng (trong Tùy chọn)
    "screen_dx_ttct_tc_button_open_cdnd": (270, 170, 730, 470),
    # Đăng xuất: Nút Đổi tài khoản (dưới cùng Cài đặt người dùng)
    "screen_dx_ttct_tc_cdnd_button_open_dtk": (290, 330, 690, 520),
    # Đăng xuất: Nút Xác nhận đổi tài khoản
    "screen_dx_popup_dtk_button_xacnhan": (430, 260, 770, 440),
    # Menu sự kiện / góc trên bên phải
    "screen_home_menu_sukien": (770, 0, 960, 180),
}


class TemplateMatcher:
    """High-performance template matcher with RAM caching, cv2.imdecode, and ROI support."""

    _template_cache: dict[str, tuple[int, np.ndarray]] = {}

    def __init__(self):
        pass

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory grayscale template cache."""
        cls._template_cache.clear()

    @classmethod
    def get_template_gray(cls, template: str | Path | np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
        """Load template once into grayscale in RAM. Check mtime if path."""
        if isinstance(template, (str, Path)):
            path = Path(template)
            key = str(path.resolve())
            try:
                mtime = path.stat().st_mtime_ns
            except FileNotFoundError:
                raise FileNotFoundError(f"Không đọc được template: {template}")

            cached = cls._template_cache.get(key)
            if cached is not None and cached[0] == mtime:
                gray_tpl = cached[1]
            else:
                tpl = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
                if tpl is None or tpl.size == 0:
                    raise FileNotFoundError(f"Không đọc được template: {template}")
                gray_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY) if tpl.ndim == 3 else tpl
                cls._template_cache[key] = (mtime, gray_tpl)
        else:
            if hasattr(template, "data") and isinstance(template.data, np.ndarray):
                tpl = template.data
            elif hasattr(template, "convert") and not hasattr(template, "shape"):
                tpl = cv2.cvtColor(np.asarray(template.convert("RGB")), cv2.COLOR_RGB2BGR)
            else:
                tpl = np.asarray(template)
            if tpl is None or tpl.size == 0:
                raise FileNotFoundError(f"Không đọc được template: {template}")
            gray_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY) if tpl.ndim == 3 else tpl

        th, tw = gray_tpl.shape[:2]
        return gray_tpl, (tw, th)

    @staticmethod
    def _parse_roi(
        roi: tuple[int, int, int, int] | list[int] | None,
        screen_shape: tuple[int, ...],
    ) -> tuple[int, int, int, int] | None:
        """Parse and clamp ROI (x1, y1, x2, y2) or (x, y, w, h) to valid bounds."""
        if roi is None:
            return None
        sh, sw = screen_shape[:2]
        r0, r1, r2, r3 = [int(v) for v in roi]
        # Nếu r2 > r0 và r3 > r1 -> định dạng [x1, y1, x2, y2]
        if r2 > r0 and r3 > r1:
            x1 = max(0, min(sw - 1, r0))
            y1 = max(0, min(sh - 1, r1))
            x2 = max(x1 + 1, min(sw, r2))
            y2 = max(y1 + 1, min(sh, r3))
            return (x1, y1, x2 - x1, y2 - y1)
        # Định dạng [x, y, w, h]
        x1 = max(0, min(sw - 1, r0))
        y1 = max(0, min(sh - 1, r1))
        w = max(1, min(sw - x1, r2))
        h = max(1, min(sh - y1, r3))
        return (x1, y1, w, h)

    @staticmethod
    def _find_default_fixed_roi(
        template: str | Path | object,
        screen_shape: tuple[int, ...],
    ) -> tuple[int, int, int, int] | None:
        """Check if template matches a known fixed control and scale ROI to current screen."""
        name = Path(str(template)).stem if isinstance(template, (str, Path)) else ""
        if not name:
            return None
        sh, sw = screen_shape[:2]
        for key, base_roi in DEFAULT_FIXED_ROIS.items():
            if key in name:
                # Scale from 960x540 base
                bx1, by1, bx2, by2 = base_roi
                sx1 = max(0, int(bx1 * sw / 960))
                sy1 = max(0, int(by1 * sh / 540))
                sx2 = min(sw, int(bx2 * sw / 960))
                sy2 = min(sh, int(by2 * sh / 540))
                return (sx1, sy1, sx2 - sx1, sy2 - sy1)
        return None

    def match(
        self,
        screen,
        template: str | Path | np.ndarray,
        threshold: float = 0.85,
        roi: tuple[int, int, int, int] | list[int] | None = None,
    ) -> MatchResult:
        """Match template against screenshot with RAM caching, fast cv2.imdecode, and ROI support."""
        # 1. Unpack ImageFrame
        if hasattr(screen, "data") and not isinstance(screen, np.ndarray):
            screen = screen.data

        # 2. Fast decode screenshot bytes in RAM using cv2.imdecode.
        # ImageFrame/PIL/numpy follow the project's RGB contract; raw PNG bytes
        # decode as BGR and are converted before matching.
        if isinstance(screen, (bytes, bytearray)):
            arr = np.frombuffer(screen, dtype=np.uint8)
            screen = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if screen is None:
                raise ValueError("Không decode được screenshot bytes bằng cv2.imdecode")
            screen = cv2.cvtColor(screen, cv2.COLOR_BGR2RGB)
        elif hasattr(screen, "convert") and hasattr(screen, "size") and not hasattr(screen, "shape"):
            screen = np.asarray(screen.convert("RGB"))
        elif hasattr(screen, "__array__") and not isinstance(screen, np.ndarray):
            screen = np.asarray(screen)

        if screen is None or not hasattr(screen, "shape"):
            raise ValueError("screen không hợp lệ: cần numpy array, ImageFrame hoặc bytes")
        if screen.size == 0:
            raise ValueError("screen rỗng")

        # 3. Convert screen to Grayscale
        gray_scr = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY) if screen.ndim == 3 else screen
        sh, sw = gray_scr.shape[:2]

        # 4. Get Grayscale template from RAM Cache
        gray_tpl, (tw, th) = self.get_template_gray(template)

        # Full-screen references resize fallback
        if th > sh or tw > sw:
            if th >= sh * 0.9 and tw >= sw * 0.9:
                gray_tpl = cv2.resize(gray_tpl, (sw, sh), interpolation=cv2.INTER_AREA)
                th, tw = gray_tpl.shape[:2]
            else:
                return MatchResult(False, 0.0, 0, 0, tw, th)

        # 5. Check ROI (either passed explicitly or auto-detected for fixed controls)
        clamped_roi = self._parse_roi(roi, gray_scr.shape)
        if clamped_roi is None:
            clamped_roi = self._find_default_fixed_roi(template, gray_scr.shape)

        if clamped_roi is not None:
            rx, ry, rw, rh = clamped_roi
            if rw >= tw and rh >= th:
                crop = gray_scr[ry : ry + rh, rx : rx + rw]
                result = cv2.matchTemplate(crop, gray_tpl, cv2.TM_CCOEFF_NORMED)
                _, score, _, loc = cv2.minMaxLoc(result)
                return MatchResult(score >= threshold, float(score), rx + int(loc[0]), ry + int(loc[1]), tw, th)

        # 6. So khớp toàn màn hình (Full Screen fallback)
        result = cv2.matchTemplate(gray_scr, gray_tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        return MatchResult(score >= threshold, float(score), int(loc[0]), int(loc[1]), tw, th)
