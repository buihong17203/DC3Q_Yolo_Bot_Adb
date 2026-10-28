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
    color_diff: float = 0.0


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
    """High-performance template matcher with RAM caching, cv2.imdecode, resized cache, and ROI support."""

    _template_cache: dict[str, tuple[int, np.ndarray, tuple[int, int], np.ndarray | None]] = {}
    _resized_cache: dict[tuple[str, int, int], np.ndarray] = {}

    SCALE_MODES = {
        "exact": [1.0],
        "fast": [0.95, 1.0, 1.05],
        "balanced": [0.90, 0.95, 1.0, 1.05, 1.10],
    }

    def __init__(self):
        pass

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory grayscale template cache and resized cache."""
        cls._template_cache.clear()
        cls._resized_cache.clear()

    @classmethod
    def get_resized_template(
        cls, key: str, gray_tpl: np.ndarray, target_w: int, target_h: int
    ) -> np.ndarray:
        """Cache and reuse resized template grayscale matrices in RAM."""
        cache_key = (key, int(target_w), int(target_h))
        cached = cls._resized_cache.get(cache_key)
        if cached is not None:
            return cached
        resized = cv2.resize(gray_tpl, (int(target_w), int(target_h)), interpolation=cv2.INTER_AREA)
        cls._resized_cache[cache_key] = resized
        return resized

    @classmethod
    def get_template_info(
        cls, template: str | Path | np.ndarray
    ) -> tuple[np.ndarray, tuple[int, int], np.ndarray | None]:
        """Load template once into RAM. Return (gray_tpl, (tw, th), mean_rgb)."""
        if isinstance(template, (str, Path)):
            path = Path(template)
            key = str(path.resolve())
            try:
                mtime = path.stat().st_mtime_ns
            except FileNotFoundError:
                raise FileNotFoundError(f"Không đọc được template: {template}")

            cached = cls._template_cache.get(key)
            if cached is not None and cached[0] == mtime:
                return cached[1], cached[2], cached[3]

            tpl = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            if tpl is None or tpl.size == 0:
                raise FileNotFoundError(f"Không đọc được template: {template}")
            if tpl.ndim == 3:
                gray_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
                rgb_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2RGB)
                mean_rgb = np.mean(rgb_tpl, axis=(0, 1)).astype(np.float32)
            else:
                gray_tpl = tpl
                mean_rgb = None
            th, tw = gray_tpl.shape[:2]
            dims = (tw, th)
            cls._template_cache[key] = (mtime, gray_tpl, dims, mean_rgb)
            # Invalidate stale resized cache for this key
            cls._resized_cache = {k: v for k, v in cls._resized_cache.items() if k[0] != key}
            return gray_tpl, dims, mean_rgb
        else:
            if hasattr(template, "data") and isinstance(template.data, np.ndarray):
                tpl = template.data
            elif hasattr(template, "convert") and not hasattr(template, "shape"):
                tpl = cv2.cvtColor(np.asarray(template.convert("RGB")), cv2.COLOR_RGB2BGR)
            else:
                tpl = np.asarray(template)
            if tpl is None or tpl.size == 0:
                raise FileNotFoundError(f"Không đọc được template: {template}")
            if tpl.ndim == 3:
                gray_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
                rgb_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2RGB) if tpl.shape[2] == 3 else tpl
                mean_rgb = np.mean(rgb_tpl, axis=(0, 1)).astype(np.float32)
            else:
                gray_tpl = tpl
                mean_rgb = None
            th, tw = gray_tpl.shape[:2]
            return gray_tpl, (tw, th), mean_rgb

    @classmethod
    def get_template_gray(cls, template: str | Path | np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
        """Load template once into grayscale in RAM. Check mtime if path."""
        gray_tpl, dims, _ = cls.get_template_info(template)
        return gray_tpl, dims

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
        max_color_dist: float | None = None,
        scales: list[float] | None = None,
    ) -> MatchResult:
        """Match template against screenshot with RAM caching, cached grayscale, cached resize, ROI, and color verification."""
        # 1. Unpack ImageFrame and check for cached grayscale
        raw_rgb: np.ndarray | None = None
        gray_scr: np.ndarray | None = None

        if hasattr(screen, "data") and isinstance(screen.data, np.ndarray):
            raw_rgb = screen.data if screen.data.ndim == 3 else None
            if hasattr(screen, "gray") and isinstance(screen.gray, np.ndarray):
                gray_scr = screen.gray
            else:
                screen = screen.data
        elif isinstance(screen, (bytes, bytearray)):
            arr = np.frombuffer(screen, dtype=np.uint8)
            decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if decoded is None:
                raise ValueError("Không decode được screenshot bytes bằng cv2.imdecode")
            raw_rgb = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
            screen = raw_rgb
        elif hasattr(screen, "convert") and hasattr(screen, "size") and not hasattr(screen, "shape"):
            raw_rgb = np.asarray(screen.convert("RGB"))
            screen = raw_rgb
        elif hasattr(screen, "__array__") and not isinstance(screen, np.ndarray):
            screen = np.asarray(screen)
            if screen.ndim == 3:
                raw_rgb = screen

        if screen is None or not hasattr(screen, "shape"):
            raise ValueError("screen không hợp lệ: cần numpy array, ImageFrame hoặc bytes")
        if screen.size == 0:
            raise ValueError("screen rỗng")

        # 2. Convert to Grayscale only if not already cached
        if gray_scr is None:
            gray_scr = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY) if screen.ndim == 3 else screen
        sh, sw = gray_scr.shape[:2]

        # 3. Get Template info (grayscale + dimensions + mean RGB color) from RAM Cache
        gray_tpl, (tw, th), mean_rgb = self.get_template_info(template)
        tpl_key = str(template) if isinstance(template, (str, Path)) else str(id(template))

        # Full-screen references resize fallback (cached in RAM)
        if th > sh or tw > sw:
            if th >= sh * 0.9 and tw >= sw * 0.9:
                gray_tpl = self.get_resized_template(tpl_key, gray_tpl, sw, sh)
                th, tw = gray_tpl.shape[:2]
            else:
                return MatchResult(False, 0.0, 0, 0, tw, th)

        # Helper to compute color diff and finalize MatchResult
        def finalize(score: float, match_x: int, match_y: int, match_w: int = tw, match_h: int = th) -> MatchResult:
            color_diff = 0.0
            found = score >= threshold
            if found and raw_rgb is not None and mean_rgb is not None:
                crop_rgb = raw_rgb[match_y : match_y + match_h, match_x : match_x + match_w]
                if crop_rgb.size > 0:
                    crop_mean = np.mean(crop_rgb, axis=(0, 1))
                    color_diff = float(np.linalg.norm(crop_mean - mean_rgb))
                    if max_color_dist is not None and color_diff > max_color_dist:
                        found = False
            return MatchResult(found, float(score), match_x, match_y, match_w, match_h, color_diff)

        # 4. Check ROI (either passed explicitly or auto-detected for fixed controls)
        clamped_roi = self._parse_roi(roi, gray_scr.shape)
        if clamped_roi is None:
            clamped_roi = self._find_default_fixed_roi(template, gray_scr.shape)

        # 5. Matching (support scale modes: exact 1.0 or fast cached multi-scale)
        scale_list = scales if (scales and len(scales) > 0) else [1.0]

        best_score = -1.0
        best_loc = (0, 0)
        best_w, best_h = tw, th

        for s in scale_list:
            if s == 1.0:
                cur_tpl = gray_tpl
                cw, ch = tw, th
            else:
                cw = max(10, int(tw * s))
                ch = max(10, int(th * s))
                cur_tpl = self.get_resized_template(tpl_key, gray_tpl, cw, ch)

            if clamped_roi is not None:
                rx, ry, rw, rh = clamped_roi
                if rw >= cw and rh >= ch:
                    crop = gray_scr[ry : ry + rh, rx : rx + rw]
                    res = cv2.matchTemplate(crop, cur_tpl, cv2.TM_CCOEFF_NORMED)
                    _, score, _, loc = cv2.minMaxLoc(res)
                    if score > best_score:
                        best_score = score
                        best_loc = (rx + int(loc[0]), ry + int(loc[1]))
                        best_w, best_h = cw, ch
            else:
                if sw >= cw and sh >= ch:
                    res = cv2.matchTemplate(gray_scr, cur_tpl, cv2.TM_CCOEFF_NORMED)
                    _, score, _, loc = cv2.minMaxLoc(res)
                    if score > best_score:
                        best_score = score
                        best_loc = (int(loc[0]), int(loc[1]))
                        best_w, best_h = cw, ch

        return finalize(best_score, best_loc[0], best_loc[1], best_w, best_h)
