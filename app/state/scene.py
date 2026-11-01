from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import sleep
from typing import Callable

from app.vision import VisionDetector
from app.vision.template import MatchResult
from app.actions.dc3q.stars import classify_login_ui

LOGGER = logging.getLogger("dc3q")


class GameScene(str, Enum):
    DESKTOP = "desktop"           # App is not foreground
    LOADING = "loading"           # Loading/splash bar
    LOGIN_SCREEN = "login_screen" # Login credentials screen
    POPUP = "popup"               # Known modal/event/profile update popup
    HOME = "home"                 # Main home/city screen (Noi chinh)
    SUB_SCREEN = "sub_screen"     # Inside a sub-target panel/window
    OUT_GAME = "out_game"         # Exit game confirmation dialog
    UNKNOWN = "unknown"           # Unidentified frame


@dataclass(frozen=True)
class SceneResult:
    scene: GameScene
    detail: str = ""
    confidence: float = 0.0
    action_point: tuple[int, int] | None = None


class SceneClassifier:
    """Universal scene classifier and safe home recovery engine for DC3Q."""

    def __init__(
        self,
        vision: VisionDetector | None = None,
        login_templates: list[Path] | None = None,
        logged_in_templates: list[Path] | None = None,
        home_events: list[tuple[Path, Path, float]] | None = None,
        out_game_title: Path | None = None,
        out_game_confirm: Path | None = None,
        sub_screen_close_templates: list[Path] | None = None,
        threshold: float = 0.75,
        logged_in_threshold: float = 0.55,
        enable_ocr: bool = False,
    ):
        self.vision = vision or VisionDetector()
        self.login_templates = login_templates or []
        self.logged_in_templates = logged_in_templates or []
        self.home_events = home_events or []
        self.out_game_title = out_game_title
        self.out_game_confirm = out_game_confirm
        self.sub_screen_close_templates = sub_screen_close_templates or []
        self.threshold = threshold
        self.logged_in_threshold = logged_in_threshold
        self.enable_ocr = enable_ocr

    def classify(self, screen, input_device=None) -> SceneResult:
        """Classify current screen with priority:
        1. Fast in-memory template matching: Event Popups -> OutGame -> Home -> Login -> SubScreen (<5ms)
        2. Fallback tier (only if visual templates return unknown): Desktop -> Native UI Popup -> Loading/SubScreen OCR -> Unknown
        """
        # =========================================================================
        # TIER 1: FAST IN-MEMORY OPENCV TEMPLATE MATCHING (<5ms, zero ADB/OCR overhead)
        # =========================================================================
        # 1. Random Event / Modal Popups via Template Matching
        for state_tpl, close_tpl, thresh in self.home_events:
            r_state = self.vision.find_template(screen, "event_state", state_tpl, thresh).match
            if getattr(r_state, "found", False) is True:
                r_close = self.vision.find_template(screen, "event_close", close_tpl, thresh).match
                point = (r_close.x + r_close.width // 2, r_close.y + r_close.height // 2) if getattr(r_close, "found", False) is True else None
                return SceneResult(
                    GameScene.POPUP,
                    f"Sự kiện: {state_tpl.stem}",
                    r_state.confidence,
                    action_point=point,
                )

        # 2. Out Game (Exit confirmation popup)
        if self.out_game_title is not None and self.out_game_confirm is not None:
            r_out = self.vision.find_template(screen, "out_game_title", self.out_game_title, self.threshold).match
            if getattr(r_out, "found", False) is True:
                return SceneResult(GameScene.OUT_GAME, "Hộp thoại Thoát Game", r_out.confidence)

        # 3. HOME screen (Nội chính)
        for tpl in self.logged_in_templates:
            r_home = self.vision.find_template(screen, "home", tpl, self.logged_in_threshold).match
            if getattr(r_home, "found", False) is True:
                return SceneResult(GameScene.HOME, "Màn hình chính HOME (Nội chính)", r_home.confidence)

        # 4. LOGIN screen
        for tpl in self.login_templates:
            r_login = self.vision.find_template(screen, "login", tpl, self.threshold).match
            if getattr(r_login, "found", False) is True:
                return SceneResult(GameScene.LOGIN_SCREEN, "Màn hình Đăng nhập", r_login.confidence)

        # 5. Sub-screen with close button
        for tpl in self.sub_screen_close_templates:
            r_close = self.vision.find_template(screen, "sub_close", tpl, self.threshold).match
            if getattr(r_close, "found", False) is True:
                point = (r_close.x + r_close.width // 2, r_close.y + r_close.height // 2)
                return SceneResult(
                    GameScene.SUB_SCREEN,
                    f"Màn hình con ({tpl.stem})",
                    r_close.confidence,
                    action_point=point,
                )

        # =========================================================================
        # TIER 2: SLOW FALLBACK (Only executed if visual templates did not match)
        # =========================================================================
        # 6. Desktop check
        if input_device is not None:
            try:
                foreground = input_device.shell("dumpsys", "window", "windows")
                if isinstance(foreground, str) and "com.daichien.mobile" not in foreground:
                    return SceneResult(GameScene.DESKTOP, "Ứng dụng không ở foreground", 1.0)
            except Exception:
                pass

        # 7. Native UI popup check (UI XML)
        if input_device is not None:
            try:
                unexpected, point = classify_login_ui(input_device.ui_xml())
                if unexpected == "profile_update_close" and point is not None:
                    return SceneResult(
                        GameScene.POPUP,
                        "Cập nhật thông tin cá nhân",
                        1.0,
                        action_point=point,
                    )
                if unexpected in {"operator_required", "profile_update_blocked"}:
                    return SceneResult(
                        GameScene.POPUP,
                        f"Yêu cầu can thiệp ({unexpected})",
                        1.0,
                    )
            except Exception:
                pass

        # 8. Loading / Splash screen detection via fast header OCR (only if enabled)
        if self.enable_ocr:
            header_text = self._ocr_header_or_screen(screen)
            if header_text:
                if any(marker in header_text for marker in ("dang tai", "v1.4.", "tam quoc", "clash of kingdoms")):
                    if "noi chinh" not in header_text and "quan su" not in header_text:
                        return SceneResult(GameScene.LOADING, f"Màn hình nạp dữ liệu ({header_text[:30]})", 0.85)

                # 9. Sub-screen via OCR header if title recognized
                for sub_name in ("truong thanh", "quan su", "cua hang", "quan doan", "vo tuong", "nhiem vu", "xa giao", "tam quoc lenh", "hoat dong", "tuong tinh dai"):
                    if sub_name in header_text:
                        return SceneResult(GameScene.SUB_SCREEN, f"Màn hình {sub_name}", 0.80)

        return SceneResult(GameScene.UNKNOWN, "Màn hình chưa xác định", 0.0)

    def ensure_home(
        self,
        screen_provider: Callable[[], object],
        input_device,
        max_steps: int = 6,
    ) -> bool:
        """Universal recovery to HOME from any scene."""
        for step in range(1, max_steps + 1):
            screen = screen_provider()
            res = self.classify(screen, input_device)
            LOGGER.info("SCENE_RECOVERY | Bước %d/%d | Trạng thái: %s (%s)", step, max_steps, res.scene.value, res.detail)

            if res.scene == GameScene.HOME:
                LOGGER.info("SCENE_RECOVERY | Đã ở màn hình HOME an toàn")
                return True

            if res.scene == GameScene.POPUP and res.action_point is not None:
                LOGGER.info("SCENE_RECOVERY | Đóng popup tại %s", res.action_point)
                input_device.tap(*res.action_point)
                sleep(1.0)
                continue

            if res.scene == GameScene.SUB_SCREEN:
                if res.action_point is not None:
                    LOGGER.info("SCENE_RECOVERY | Đóng màn hình con tại %s", res.action_point)
                    input_device.tap(*res.action_point)
                else:
                    LOGGER.info("SCENE_RECOVERY | Bấm KEYCODE_BACK để lùi khỏi màn hình con")
                    input_device.keyevent("KEYCODE_BACK")
                sleep(1.0)
                continue

            if res.scene == GameScene.OUT_GAME:
                LOGGER.info("SCENE_RECOVERY | Hủy popup Thoát game bằng KEYCODE_BACK")
                input_device.keyevent("KEYCODE_BACK")
                sleep(1.0)
                continue

            if res.scene == GameScene.LOADING:
                LOGGER.info("SCENE_RECOVERY | Game đang tải dữ liệu; chờ 2 giây...")
                sleep(2.0)
                continue

            if res.scene == GameScene.DESKTOP:
                LOGGER.info("SCENE_RECOVERY | Game không ở foreground; mở lại game...")
                input_device.shell("monkey", "-p", "com.daichien.mobile", "1")
                sleep(3.0)
                continue

            # Fallback for UNKNOWN / stubborn popup
            LOGGER.info("SCENE_RECOVERY | Màn hình %s; thử bấm KEYCODE_BACK để đóng", res.scene.value)
            input_device.keyevent("KEYCODE_BACK")
            sleep(1.0)

        # Final check
        final_screen = screen_provider()
        final_res = self.classify(final_screen, input_device)
        return final_res.scene == GameScene.HOME

    @staticmethod
    def _ocr_header_or_screen(screen) -> str:
        """Fast OCR on header band (y: 0 -> 180) and bottom bar."""
        import unicodedata
        import numpy as np
        try:
            from rapidocr_onnxruntime import RapidOCR
            image = screen.data if hasattr(screen, "data") else (
                np.asarray(screen.convert("RGB")) if hasattr(screen, "convert") else np.asarray(screen)
            )
            # Crop header (y: 0 -> 200) for fast execution
            h = image.shape[0]
            header = image[:min(h, 200), :]
            result, _ = RapidOCR()(header)
            text = " ".join(str(row[1]) for row in (result or []))
            return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        except Exception:
            return ""
