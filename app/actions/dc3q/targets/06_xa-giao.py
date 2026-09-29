from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class XaGiaoConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    panel_markers: list[Path]
    close_template: Path
    home_markers: list[Path]
    heart_before: Path
    heart_after: Path
    quick_before: Path
    quick_after: Path
    threshold: float = 0.65
    state_threshold: float = 0.80
    max_steps: int = 24
    wait_seconds: float = 0.8


class XaGiaoRunner:
    def __init__(self, screen_provider, adb_input, vision, config: XaGiaoConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "xa_giao", template,
            self.config.threshold if threshold is None else threshold,
        ).match

    def _first(self, screen, templates: list[Path], threshold: float | None = None):
        for template in templates:
            match = self._match(screen, template, threshold)
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

    def _prove(self, templates: list[Path], message: str, attempts: int = 8):
        screen, match = self._wait_for(templates, attempts)
        if match is None:
            raise RuntimeError(message)
        return screen

    def recover_home(self) -> bool:
        for _ in range(12):
            screen = self.screen_provider()
            if self._first(screen, self.config.home_markers) is not None:
                return True
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                continue
            self.sleep(self.config.wait_seconds)
        return False

    def _open_panel(self):
        screen = self.screen_provider()
        if self._first(screen, self.config.panel_markers) is not None:
            return screen
        entry = self._first(screen, self.config.entry_templates)
        if entry is None:
            menu = self._first(screen, self.config.menu_templates)
            if menu is not None:
                self._tap(menu)
                screen, entry = self._wait_for(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Xã giao: không tìm thấy nút mở Bạn bè")
        self._tap(entry)
        return self._prove(self.config.panel_markers, "Xã giao: bấm mở nhưng chưa thấy danh sách Bạn bè")

    def _safe_toggle(self, screen, before_template: Path, after_template: Path, label: str):
        before = self._match(screen, before_template, self.config.state_threshold)
        after = self._match(screen, after_template, self.config.state_threshold)
        if after.found and after.confidence >= before.confidence:
            return screen
        if not before.found or before.confidence <= after.confidence:
            raise RuntimeError(f"Xã giao: không xác định được trạng thái {label}")
        self._tap(before)
        return self._prove([after_template], f"Xã giao: thiếu hậu điều kiện {label}")

    def run(self) -> bool:
        screen = self._open_panel()
        screen = self._safe_toggle(screen, self.config.heart_before, self.config.heart_after, "tặng tim")
        screen = self._safe_toggle(screen, self.config.quick_before, self.config.quick_after, "tặng nhanh")
        close = self._match(screen, self.config.close_template)
        if close.found:
            self._tap(close)
        if not self.recover_home():
            raise RuntimeError("Xã giao: không recover_home được")
        return True
