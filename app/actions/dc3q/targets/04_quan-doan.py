from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class QuanDoanConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    panel_markers: list[Path]
    close_template: Path
    home_markers: list[Path]
    prayer_tabs: list[Path]
    prayer_open: list[Path]
    prayer_available: Path
    prayer_empty: Path
    prayer_close: Path
    threshold: float = 0.65
    state_threshold: float = 0.76
    max_steps: int = 30
    wait_seconds: float = 0.8


class QuanDoanRunner:
    """HOME -> Quân đoàn -> Cầu vận quân đoàn free attempts -> HOME."""

    def __init__(self, screen_provider, adb_input, vision, config: QuanDoanConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "quan_doan", template,
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

    def _open_prayer(self, screen):
        if self._first(screen, self.config.prayer_open) is not None:
            return screen
        tab = self._first(screen, self.config.prayer_tabs)
        if tab is None:
            raise RuntimeError("Quân đoàn: không nhận diện được Cầu vận quân đoàn")
        self._tap(tab)
        screen, opened = self._wait_for(self.config.prayer_open)
        if opened is None:
            raise RuntimeError("Quân đoàn: bấm Cầu vận nhưng tab chưa mở")
        return screen

    def recover_home(self) -> bool:
        logger = logging.getLogger("dc3q")
        for _ in range(12):
            screen = self.screen_provider()
            popup_close = self._match(screen, self.config.prayer_close)
            if popup_close.found:
                self._tap(popup_close)
                logger.info("QD | recovery đóng Cầu vận")
                continue
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                logger.info("QD | recovery đóng Quân đoàn")
                continue
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("QD | recovery đã về HOME")
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
                raise RuntimeError("Quân đoàn: không tìm thấy icon tại HOME")
            self._tap(menu)
            screen, entry = self._wait_for(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Quân đoàn: menu đã mở nhưng thiếu icon Quân đoàn")
        self._tap(entry)
        logger.info("QD | mở Quân đoàn")
        screen, panel = self._wait_for(self.config.panel_markers + self.config.prayer_tabs + self.config.prayer_open)
        if panel is None:
            raise RuntimeError("Quân đoàn: bấm icon nhưng panel chưa mở sau khi chờ")
        screen = self._open_prayer(screen)
        for _ in range(self.config.max_steps):
            available = self._match(screen, self.config.prayer_available, self.config.state_threshold)
            empty = self._match(screen, self.config.prayer_empty, self.config.state_threshold)
            if available.found and available.confidence > empty.confidence:
                self._tap(available)
                logger.info("QD | bấm 10 Cầu vận miễn phí")
                screen = self.screen_provider()
                continue
            if empty.found:
                popup_close = self._match(screen, self.config.prayer_close)
                if popup_close.found:
                    self._tap(popup_close)
                    screen = self.screen_provider()
                    close = self._match(screen, self.config.close_template)
                    if not close.found:
                        continue
                    self._tap(close)
                else:
                    close = self._match(screen, self.config.close_template)
                    if not close.found:
                        raise RuntimeError("Quân đoàn: hoàn tất nhưng thiếu nút đóng")
                    self._tap(close)
                for _ in range(5):
                    screen = self.screen_provider()
                    if self._first(screen, self.config.home_markers) and self._first(screen, self.config.panel_markers) is None:
                        return True
                    self.sleep(self.config.wait_seconds)
                raise RuntimeError("Quân đoàn: đóng xong nhưng chưa về HOME")
            if self._first(screen, self.config.panel_markers + self.config.prayer_open) is not None:
                raise RuntimeError("Quân đoàn: state trong popup không xác định hoặc không an toàn")
            raise RuntimeError("Quân đoàn: màn hình không xác định")
        raise RuntimeError("Quân đoàn: vượt quá số bước cho phép")
