from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class SubFlow:
    name: str
    entry: list[Path]
    free: list[Path]
    spent: list[Path]
    close: list[Path]


@dataclass(frozen=True)
class TruongThanhConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    home_markers: list[Path]
    close_templates: list[Path]
    skipped_subflows: list[str]
    flows: list[SubFlow]
    threshold: float = 0.70
    max_steps: int = 60
    wait_seconds: float = 0.8


class TruongThanhRunner:
    """Trường thành runner: only pre-proven free controls; no paid/resource clicks."""

    def __init__(self, screen_provider, adb_input, vision, config: TruongThanhConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "truong_thanh", template,
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

    def _wait_first(self, templates: list[Path], attempts: int = 6):
        screen = None
        for _ in range(attempts):
            screen = self.screen_provider()
            match = self._first(screen, templates)
            if match is not None:
                return screen, match
            self.sleep(self.config.wait_seconds)
        return screen, None

    def recover_home(self) -> bool:
        logger = logging.getLogger("dc3q")
        # reverse-layer close: reward/result child layers before panels.
        for _ in range(12):
            screen = self.screen_provider()
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("TT | recovery đã về HOME")
                return True
            close = self._first(screen, self.config.close_templates)
            if close is None:
                self.sleep(self.config.wait_seconds)
                continue
            self._tap(close)
            logger.info("TT | recovery đóng layer")
        return False

    def _open_home_entry(self) -> None:
        screen = self.screen_provider()
        entry = self._first(screen, self.config.entry_templates)
        if entry is None:
            menu = self._first(screen, self.config.menu_templates)
            if menu is None:
                raise RuntimeError("Trường thành: không tìm thấy icon tại HOME")
            self._tap(menu)
            _, entry = self._wait_first(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Trường thành: menu đã mở nhưng thiếu icon Trường thành")
        self._tap(entry)
        logging.getLogger("dc3q").info("TT | mở Trường thành")

    def _finish_flow(self, flow: SubFlow, screen) -> bool:
        # spent/result state must be visually proven before any close tap.
        if self._first(screen, flow.spent) is not None:
            _, close = self._wait_first(flow.close)
            if close is None:
                raise RuntimeError(f"Trường thành {flow.name}: thấy kết quả nhưng thiếu nút đóng")
            self._tap(close)
            logging.getLogger("dc3q").info("TT | %s đóng kết quả", flow.name)
            return True
        close = self._first(screen, flow.close)
        if close is not None:
            self._tap(close)
            logging.getLogger("dc3q").info("TT | %s đóng state đã xong/không miễn phí", flow.name)
            return True
        return False

    def _run_flow(self, flow: SubFlow) -> None:
        logger = logging.getLogger("dc3q")
        screen = self.screen_provider()
        entry = self._first(screen, flow.entry)
        if entry is not None:
            self._tap(entry)
            screen, _ = self._wait_first([*flow.free, *flow.spent, *flow.close])
        for _ in range(12):
            if self._finish_flow(flow, screen):
                return
            free = self._first(screen, flow.free)
            if free is not None:
                self._tap(free)
                logger.info("TT | %s bấm miễn phí", flow.name)
                screen, spent = self._wait_first(flow.spent)
                if spent is None:
                    raise RuntimeError(f"Trường thành {flow.name}: bấm miễn phí nhưng không thấy hậu điều kiện")
                continue
            # No recognisable free/safe state. Skip, never guess-click.
            logger.info("TT | %s bỏ qua: không chứng minh được trạng thái miễn phí/an toàn", flow.name)
            return
        raise RuntimeError(f"Trường thành {flow.name}: vượt quá số bước cho phép")

    def run(self) -> bool:
        self._open_home_entry()
        for flow in self.config.flows:
            self._run_flow(flow)
        if self.recover_home():
            return True
        raise RuntimeError("Trường thành: không recover được HOME")
