from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class VoTuongConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    home_markers: list[Path]
    panel_markers: list[Path]
    close_template: Path
    reward_marker: Path
    reward_dismiss: Path
    safe_actions: list[Path]
    forbidden_actions: list[Path]
    threshold: float = 0.60
    max_steps: int = 20
    wait_seconds: float = 0.8


class VoTuongRunner:
    """Võ tướng free-only runner; no Ton Ngoc or ambiguous controls."""

    def __init__(self, screen_provider, adb_input, vision, config: VoTuongConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(screen, "vo_tuong", template, self.config.threshold if threshold is None else threshold).match

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
        logger = logging.getLogger("dc3q")
        for _ in range(12):
            screen = self.screen_provider()
            if self._match(screen, self.config.reward_marker).found:
                dismiss = self._match(screen, self.config.reward_dismiss)
                if not dismiss.found:
                    return False
                self._tap(dismiss)
                continue
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                continue
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("VT | recovery HOME")
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        opened = False
        clicked = False
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
                raise RuntimeError("Võ tướng: không tìm thấy icon tại HOME")
            if self._match(screen, self.config.reward_marker).found:
                dismiss = self._match(screen, self.config.reward_dismiss)
                if not dismiss.found:
                    raise RuntimeError("Võ tướng: thấy thưởng nhưng thiếu nút đóng an toàn")
                self._tap(dismiss)
                clicked = True
                continue
            if clicked and self._first(screen, self.config.home_markers) and self._first(screen, self.config.panel_markers) is None:
                return True
            panel = self._first(screen, self.config.panel_markers)
            if panel is not None:
                forbidden = self._first(screen, self.config.forbidden_actions)
                safe = self._first(screen, self.config.safe_actions)
                if safe is not None and forbidden is None and not clicked:
                    self._tap(safe)
                    logger.info("VT | bấm free-only")
                    continue
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    logger.info("VT | skip: không có ảnh hành động an toàn")
                    return self.recover_home()
                if forbidden is not None:
                    logger.info("VT | skip Ton Ngoc/premium")
                else:
                    logger.info("VT | skip: không có ảnh hành động an toàn")
                self._tap(close)
                clicked = True
                continue
            if self._first(screen, self.config.home_markers) is not None:
                return True
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Võ tướng: vượt quá số bước cho phép")
