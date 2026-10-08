from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class QuanSuConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    home_markers: list[Path]
    panel_markers: list[Path]
    close_template: Path
    reward_button: Path
    claimed_markers: list[Path]
    unfinished_markers: list[Path]
    threshold: float = 0.60
    max_steps: int = 16
    wait_seconds: float = 0.8


class QuanSuRunner:
    """Tranh Bá reward-only runner; never starts unfinished battles."""
    runtime_task = "TRANH_BA"

    def __init__(self, screen_provider, adb_input, vision, config: QuanSuConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(screen, "quan_su", template, self.config.threshold if threshold is None else threshold).match

    def _first(self, screen, templates: list[Path]):
        for template in templates:
            match = self._match(screen, template)
            if match.found:
                return match
        return None

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def recover_home(self) -> bool:
        for _ in range(12):
            screen = self.screen_provider()
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                continue
            if self._first(screen, self.config.home_markers) is not None:
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        opened = False
        acted = False
        for _ in range(self.config.max_steps):
            screen = self.screen_provider()
            if not opened:
                entry = self._first(screen, self.config.entry_templates)
                if entry is not None:
                    self._tap(entry)
                    opened = True
                    continue
                menu = self._first(screen, self.config.menu_templates)
                if menu is not None:
                    self._tap(menu)
                    continue
                raise RuntimeError("Quân sự: không tìm thấy icon tại HOME")
            if acted and self._first(screen, self.config.home_markers) and self._first(screen, self.config.panel_markers) is None:
                return True
            if self._first(screen, self.config.panel_markers) is not None:
                if self._first(screen, self.config.unfinished_markers) is not None:
                    logger.info("QS | skip: Tranh Bá chưa kết thúc")
                    close = self._match(screen, self.config.close_template)
                    if not close.found:
                        return self.recover_home()
                    self._tap(close)
                    acted = True
                    continue
                reward = self._match(screen, self.config.reward_button)
                if reward.found and self._first(screen, self.config.claimed_markers) is None:
                    self._tap(reward)
                    logger.info("QS | nhận thưởng đã kết thúc")
                    continue
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return self.recover_home()
                self._tap(close)
                acted = True
                continue
            if self._first(screen, self.config.home_markers) is not None:
                return True
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Quân sự: vượt quá số bước cho phép")
