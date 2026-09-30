from __future__ import annotations
from dataclasses import dataclass
import logging
from pathlib import Path
import time

from app.adb.input import AdbInput
from app.vision import VisionDetector
from app.state.login import LoginScreenState

LOGGER = logging.getLogger("dc3q")


def reflected_point(anchor: tuple[int, int], size: tuple[int, int],
                    offset: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Reflect an anchor through screen center, then apply calibrated offset."""
    x, y = anchor
    width, height = size
    dx, dy = offset
    return width - x + dx, height - y + dy


def select_logout_state(found: dict[str, bool]) -> str:
    """Resume forward from the deepest positively recognized logout layer."""
    for state in ("login", "confirm", "switch", "settings", "options", "home"):
        if found.get(state):
            return state
    return "unknown"


@dataclass(frozen=True)
class LogoutTemplates:
    open_tuychon: Path
    open_cdnd: Path
    open_dtk: Path
    confirm_dtk: Path
    home_anchor_template: Path
    home_anchor_roi: tuple[int, int, int, int] = (840, 490, 980, 575)
    avatar_mirror_offset: tuple[int, int] = (-8, 21)


class AccountLogoutAction:
    """Forward-only, restart-safe switch-account state machine."""
    def __init__(self, adb_input: AdbInput, templates: LogoutTemplates | None = None,
                 vision: VisionDetector | None = None):
        self.input = adb_input
        self.templates = templates
        self.vision = vision or VisionDetector()

    def _match(self, screen, template, threshold: float):
        return self.vision.find_template(screen, "logout_control", template, threshold).match

    def _find_and_tap(self, screen, template: str | Path, threshold: float = 0.75) -> bool:
        r = self._match(screen, template, threshold)
        if not r.found:
            return False
        self.input.tap(r.x + r.width // 2, r.y + r.height // 2)
        return True

    def _avatar_from_noi_chinh(self, screen, templates: LogoutTemplates,
                               threshold: float) -> tuple[int, int] | None:
        """Find Nội chính, reflect it through screen center, derive avatar."""
        import cv2
        import numpy as np

        anchor = cv2.imdecode(
            np.fromfile(str(templates.home_anchor_template), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if anchor is None:
            raise FileNotFoundError(templates.home_anchor_template)
        x1, y1, x2, y2 = templates.home_anchor_roi
        data = screen.data if hasattr(screen, "data") else screen
        if hasattr(data, "convert"):
            data = np.asarray(data.convert("RGB"))
        else:
            data = np.asarray(data)
        height, width = data.shape[:2]
        ref_width, ref_height = 1000, 575
        scaled = cv2.resize(anchor, (max(1, round(anchor.shape[1] * width / ref_width)),
                                     max(1, round(anchor.shape[0] * height / ref_height))),
                            interpolation=cv2.INTER_AREA)
        sx1 = max(0, round(x1 * width / ref_width))
        sy1 = max(0, round(y1 * height / ref_height))
        sx2 = min(width, round(x2 * width / ref_width))
        sy2 = min(height, round(y2 * height / ref_height))
        # Template can sit on the right/bottom border. Keep the full scaled
        # crop inside the search ROI instead of clipping its last columns.
        sx2 = min(width, max(sx2, sx1 + scaled.shape[1]))
        sy2 = min(height, max(sy2, sy1 + scaled.shape[0]))
        search = data[sy1:sy2, sx1:sx2]
        if search.ndim == 3:
            search = cv2.cvtColor(search, cv2.COLOR_RGB2GRAY)
        if scaled.ndim == 3:
            scaled = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        if search.shape[0] < scaled.shape[0] or search.shape[1] < scaled.shape[1]:
            LOGGER.info(
                "VISION | ảnh_hiện_tại=<ADB frame mới nhất> vs mẫu=%s | mục_đích=logout_home_anchor | "
                "độ_khớp=0.000 | nhận_diện=KHÔNG | kết_luận=ROI NHỎ HƠN MẪU",
                templates.home_anchor_template.resolve(),
            )
            return None
        result = cv2.matchTemplate(search, scaled, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        # Small edge HUD crops vary slightly with animation/compression. The
        # configured threshold remains strict elsewhere; this anchor has a
        # narrow ROI and only authorizes opening the profile.
        anchor_threshold = max(0.0, threshold - 0.02)
        LOGGER.info(
            "VISION | ảnh_hiện_tại=<ADB frame mới nhất> vs mẫu=%s | mục_đích=logout_home_anchor | "
            "độ_khớp=%.3f | ngưỡng=%.3f | nhận_diện=%s | kết_luận=%s | vị_trí=(%d,%d,%d,%d)",
            templates.home_anchor_template.resolve(), score, anchor_threshold,
            "CÓ" if score >= anchor_threshold else "KHÔNG",
            "ĐẠT NGƯỠNG" if score >= anchor_threshold else "KHÔNG ĐẠT NGƯỠNG",
            sx1 + location[0], sy1 + location[1], scaled.shape[1], scaled.shape[0],
        )
        if score < anchor_threshold:
            return None
        anchor_center = (
            sx1 + location[0] + scaled.shape[1] // 2,
            sy1 + location[1] + scaled.shape[0] // 2,
        )
        point = reflected_point(anchor_center, (width, height), templates.avatar_mirror_offset)
        return max(0, min(width - 1, point[0])), max(0, min(height - 1, point[1]))

    def logout(self, screen_provider, *, templates: LogoutTemplates | None = None,
               threshold: float = 0.75, max_attempts: int = 5,
               login_detector=None, login_templates=(), login_threshold: float = 0.80) -> bool:
        tpls = templates or self.templates
        if tpls is None:
            raise RuntimeError("AccountLogoutAction cần cấu hình templates")

        unknown_hits = 0
        for _ in range(max_attempts * 6):
            screen = screen_provider()
            at_login = False
            if login_detector is not None:
                at_login = login_detector.detect(
                    screen,
                    login_templates=login_templates,
                    logged_in_templates=[],
                    threshold=login_threshold,
                ).state == LoginScreenState.LOGIN_SCREEN

            matches = {
                "login": at_login,
                "confirm": self._match(screen, tpls.confirm_dtk, threshold).found,
                "switch": self._match(screen, tpls.open_dtk, threshold).found,
                "settings": self._match(screen, tpls.open_cdnd, threshold).found,
                "options": self._match(screen, tpls.open_tuychon, threshold).found,
            }
            avatar = self._avatar_from_noi_chinh(screen, tpls, threshold)
            matches["home"] = avatar is not None
            state = select_logout_state(matches)
            LOGGER.info("DECISION | logout | trạng_thái=%s | nhận_diện=%s", state, matches)

            if state == "login":
                return True
            if state == "confirm":
                self._find_and_tap(screen, tpls.confirm_dtk, threshold)
            elif state == "switch":
                self._find_and_tap(screen, tpls.open_dtk, threshold)
            elif state == "settings":
                self._find_and_tap(screen, tpls.open_cdnd, threshold)
            elif state == "options":
                self._find_and_tap(screen, tpls.open_tuychon, threshold)
            elif state == "home" and avatar is not None:
                self.input.tap(*avatar)
            else:
                # Game can show loading/transition frames for several seconds
                # after Confirm. Keep polling to the controller's full bounded
                # budget; never mistake a temporary UNKNOWN frame for failure.
                unknown_hits += 1
                if unknown_hits >= max_attempts * 6:
                    raise RuntimeError("Không nhận diện được HOME hoặc lớp đăng xuất hiện tại")
                time.sleep(0.8)
                continue

            unknown_hits = 0
            time.sleep(0.8)

        raise RuntimeError("Đăng xuất quá số bước cho phép; chưa về màn hình đăng nhập")
