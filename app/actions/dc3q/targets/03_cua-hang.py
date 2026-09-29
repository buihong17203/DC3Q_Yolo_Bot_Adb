from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class CuaHangConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    panel_markers: list[Path]
    close_template: Path
    home_markers: list[Path]
    gift_tab_closed: list[Path]
    gift_tab_open: list[Path]
    daily_unclaimed: Path
    daily_claimed: Path
    reward_marker: Path
    reward_dismiss: Path
    threshold: float = 0.65
    state_threshold: float = 0.76
    max_steps: int = 30
    wait_seconds: float = 0.8


class CuaHangRunner:
    """HOME -> Cửa hàng -> Cửa hàng gợi ý daily gift -> HOME. Free-only."""

    def __init__(self, screen_provider, adb_input, vision, config: CuaHangConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "cua_hang", template,
            self.config.threshold if threshold is None else threshold,
        ).match

    def _first(self, screen, templates: list[Path]):
        for template in templates:
            match = self._match(screen, template)
            if match.found:
                return match
        return None

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def _wait_for(self, templates: list[Path], attempts: int = 8):
        last = None
        for _ in range(attempts):
            last = self.screen_provider()
            match = self._first(last, templates)
            if match is not None:
                return last, match
            self.sleep(self.config.wait_seconds)
        return last, None

    def _reward(self, screen) -> bool:
        if not self._match(screen, self.config.reward_marker).found:
            return False
        dismiss = self._match(screen, self.config.reward_dismiss)
        if not dismiss.found:
            raise RuntimeError("Cửa hàng: thấy thưởng nhưng thiếu vùng đóng an toàn")
        self._tap(dismiss)
        return True

    def _open_gift_tab(self, screen):
        if self._first(screen, self.config.gift_tab_open) is not None:
            return screen
        tab = self._first(screen, self.config.gift_tab_closed)
        if tab is None:
            raise RuntimeError("Cửa hàng: không nhận diện được tab Cửa hàng gợi ý")
        self._tap(tab)
        screen, opened = self._wait_for(self.config.gift_tab_open)
        if opened is None:
            raise RuntimeError("Cửa hàng: bấm Cửa hàng gợi ý nhưng tab chưa mở")
        return screen

    def recover_home(self) -> bool:
        logger = logging.getLogger("dc3q")
        for _ in range(12):
            screen = self.screen_provider()
            if self._reward(screen):
                logger.info("CH | recovery đóng thưởng")
                continue
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                logger.info("CH | recovery đóng Cửa hàng")
                continue
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("CH | recovery đã về HOME")
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        screen = self.screen_provider()
        entry = self._first(screen, self.config.entry_templates)
        if entry is None:
            menu = self._first(screen, self.config.menu_templates)
            if menu is None:
                raise RuntimeError("Cửa hàng: không tìm thấy icon tại HOME")
            self._tap(menu)
            screen, entry = self._wait_for(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Cửa hàng: menu đã mở nhưng thiếu icon Cửa hàng")
        self._tap(entry)
        logger.info("CH | mở Cửa hàng")
        screen, panel = self._wait_for(self.config.panel_markers + self.config.gift_tab_open + self.config.gift_tab_closed)
        if panel is None:
            raise RuntimeError("Cửa hàng: bấm icon nhưng panel chưa mở sau khi chờ")
        screen = self._open_gift_tab(screen)
        for _ in range(self.config.max_steps):
            if self._reward(screen):
                screen = self.screen_provider()
                continue
            unclaimed = self._match(screen, self.config.daily_unclaimed, self.config.state_threshold)
            claimed = self._match(screen, self.config.daily_claimed, self.config.state_threshold)
            if unclaimed.found and unclaimed.confidence > claimed.confidence:
                self._tap(unclaimed)
                logger.info("CH | nhận Quà hằng ngày miễn phí")
                screen = self.screen_provider()
                continue
            if claimed.found:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    raise RuntimeError("Cửa hàng: hoàn tất nhưng thiếu nút đóng")
                self._tap(close)
                for _ in range(5):
                    screen = self.screen_provider()
                    if self._first(screen, self.config.home_markers) and self._first(screen, self.config.panel_markers) is None:
                        return True
                    self.sleep(self.config.wait_seconds)
                raise RuntimeError("Cửa hàng: đóng xong nhưng chưa về HOME")
            if self._first(screen, self.config.panel_markers + self.config.gift_tab_open) is not None:
                raise RuntimeError("Cửa hàng: state trong popup không xác định hoặc không an toàn")
            raise RuntimeError("Cửa hàng: màn hình không xác định")
        raise RuntimeError("Cửa hàng: vượt quá số bước cho phép")
