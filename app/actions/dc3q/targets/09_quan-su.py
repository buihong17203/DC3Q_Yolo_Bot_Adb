from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


def _is_military_ocr(text: str) -> bool:
    import unicodedata
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = plain.split()
    return any(word.startswith("quan") for word in words) and "su" in words


@dataclass(frozen=True)
class QuanSuConfig:
    military_point: tuple[int, int]
    military_close_point: tuple[int, int]
    tranh_ba_entry: list[Path]
    home_markers: list[Path]
    main_markers: list[Path]
    detail_markers: list[Path]
    reward_tab: Path
    reward_button: Path
    unfinished_markers: list[Path]
    close_template: Path
    threshold: float = 0.60
    max_steps: int = 20
    wait_seconds: float = 0.8


class QuanSuRunner:
    """Quân sự → Tranh Bá → nhận thưởng đã kết thúc → HOME."""
    runtime_task = "TRANH_BA"

    def __init__(self, screen_provider, adb_input, vision, config: QuanSuConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        value = self.config.threshold if threshold is None else threshold
        return self.vision.find_template(screen, "tranh_ba", template, value).match

    def _first(self, screen, templates: list[Path]):
        for template in templates:
            match = self._match(screen, template)
            if match.found:
                return match
        return None

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def _tap_tranh_ba(self, match) -> None:
        # Icon chiếm 48 px đầu; tránh vùng chữ ở đáy crop.
        self.input.tap(match.x + match.width // 2, match.y + 24)
        self.sleep(self.config.wait_seconds)

    @staticmethod
    def _screen_array(screen):
        import cv2
        import numpy as np
        if isinstance(screen, np.ndarray):
            return screen
        if isinstance(screen, (bytes, bytearray)):
            return cv2.imdecode(np.frombuffer(screen, dtype=np.uint8), cv2.IMREAD_COLOR)
        if hasattr(screen, "convert"):
            return cv2.cvtColor(np.array(screen.convert("RGB")), cv2.COLOR_RGB2BGR)
        return cv2.imread(str(screen))

    def _has_military_text(self, screen) -> bool:
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(self._screen_array(screen)[430:540, 0:220])
        text = " ".join(str(row[1]) for row in (result or []))
        logging.getLogger("dc3q").info("TRANH_BA | OCR góc Quân sự=%r", text)
        return _is_military_ocr(text)

    def recover_home(self, initial_screen=None) -> bool:
        for _ in range(self.config.max_steps):
            screen = initial_screen if initial_screen is not None else self.screen_provider()
            initial_screen = None
            if self._first(screen, self.config.detail_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                continue
            if self._first(screen, self.config.main_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                continue
            if self._first(screen, self.config.home_markers) is not None:
                entry = self._first(screen, self.config.tranh_ba_entry)
                if entry is not None:
                    self.input.tap(*self.config.military_close_point)
                    self.sleep(self.config.wait_seconds)
                    continue
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        phase = "OPEN_HOME_MENU"
        for _ in range(self.config.max_steps):
            screen = self.screen_provider()

            if phase == "OPEN_HOME_MENU":
                if self._first(screen, self.config.home_markers) is None:
                    raise RuntimeError("Tranh Bá: chưa chứng minh HOME")
                if not self._has_military_text(screen):
                    raise RuntimeError("Tranh Bá: OCR không chứng minh được nút Quân sự")
                self.input.tap(*self.config.military_point)
                self.sleep(self.config.wait_seconds)
                phase = "OPEN_MENU"
                continue

            if phase == "OPEN_MENU":
                if self._first(screen, self.config.home_markers) is None:
                    raise RuntimeError("Tranh Bá: mất HOME sau khi mở Quân sự")
                entry = self._first(screen, self.config.tranh_ba_entry)
                if entry is None:
                    raise RuntimeError("Tranh Bá: chưa chứng minh icon Tranh Bá sau khi mở Quân sự")
                self._tap_tranh_ba(entry)
                phase = "OPEN_REWARD"
                continue

            if phase == "OPEN_TRANH_BA":
                entry = self._first(screen, self.config.tranh_ba_entry)
                if entry is None:
                    raise RuntimeError("Tranh Bá: menu Quân sự thiếu icon Tranh Bá")
                self._tap_tranh_ba(entry)
                phase = "OPEN_REWARD"
                continue

            if phase == "OPEN_REWARD":
                if self._first(screen, self.config.main_markers) is None:
                    raise RuntimeError("Tranh Bá: chưa mở popup Tranh Bá")
                reward_tab = self._match(screen, self.config.reward_tab)
                if not reward_tab.found:
                    raise RuntimeError("Tranh Bá: thiếu nút Thưởng")
                self._tap(reward_tab)
                phase = "CHECK_REWARD"
                continue

            if phase == "CHECK_REWARD":
                if self._first(screen, self.config.detail_markers) is None:
                    raise RuntimeError("Tranh Bá: chưa mở Chi tiết thưởng")
                if self._first(screen, self.config.unfinished_markers) is not None:
                    logger.info("TRANH_BA | Chưa kết thúc: hôm nay đã nhận; không bấm")
                    if not self.recover_home(screen):
                        raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                    logger.info("TRANH_BA | hoàn tất, đã về HOME")
                    return True
                reward = self._match(screen, self.config.reward_button)
                if not reward.found:
                    raise RuntimeError("Tranh Bá: Chi tiết thưởng thiếu trạng thái")
                self._tap(reward)
                logger.info("TRANH_BA | bấm Nhận thưởng")
                phase = "VERIFY_CLAIMED"
                continue

            if phase == "VERIFY_CLAIMED":
                if self._first(screen, self.config.unfinished_markers) is None:
                    raise RuntimeError("Tranh Bá: nhận thưởng thiếu hậu điều kiện Chưa kết thúc")
                logger.info("TRANH_BA | nhận thưởng thành công")
                if not self.recover_home(screen):
                    raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                logger.info("TRANH_BA | hoàn tất, đã về HOME")
                return True

        raise RuntimeError("Tranh Bá: vượt quá số bước cho phép")
