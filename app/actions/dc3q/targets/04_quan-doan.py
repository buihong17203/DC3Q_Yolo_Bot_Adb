from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from types import SimpleNamespace
from typing import Callable


@dataclass(frozen=True)
class QuanDoanConfig:
    entry_templates: list[Path]
    home_anchor: Path
    menu_templates: list[Path]
    entrance_templates: list[Path]
    panel_markers: list[Path]
    close_template: Path
    home_markers: list[Path]
    registration_available: Path
    registration_done: Path
    prayer_entry: Path
    prayer_available: Path
    prayer_empty: Path
    prayer_close: Path
    threshold: float = 0.65
    state_threshold: float = 0.76
    max_steps: int = 30
    wait_seconds: float = 0.8
    entrance_wait_attempts: int = 24
    registration_wait_attempts: int = 24
    home_control_threshold: float = 0.30


class QuanDoanRunner:
    """HOME -> Quân đoàn -> Báo danh -> Cầu vận đến 0 -> HOME."""
    runtime_task = "QUAN_DOAN"

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

    def _first(self, screen, templates: list[Path], threshold: float | None = None):
        for template in templates:
            match = self._match(screen, template, threshold)
            if match.found:
                return match
        return None

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    @staticmethod
    def _pixels(screen):
        import numpy as np
        value = screen.data if hasattr(screen, "data") else screen
        if hasattr(value, "convert"):
            return np.asarray(value.convert("RGB"))
        return np.asarray(value)

    def _screen_size(self, screen) -> tuple[int, int]:
        pixels = self._pixels(screen)
        return int(pixels.shape[1]), int(pixels.shape[0])

    def _match_roi(self, screen, template: Path, roi, threshold: float | None = None):
        x1, y1, x2, y2 = roi
        cropped = self._pixels(screen)[y1:y2, x1:x2]
        local = self._match(cropped, template, threshold)
        return SimpleNamespace(
            found=local.found, confidence=local.confidence,
            x=local.x + x1, y=local.y + y1,
            width=local.width, height=local.height,
        )

    def _wait_for(self, templates: list[Path], attempts: int = 8):
        last = None
        for _ in range(attempts):
            last = self.screen_provider()
            match = self._first(last, templates)
            if match is not None:
                return last, match
            self.sleep(self.config.wait_seconds)
        return last, None

    def _register(self, screen):
        logger = logging.getLogger("dc3q")
        for attempt in range(self.config.registration_wait_attempts):
            available = self._match(
                screen, self.config.registration_available, self.config.state_threshold,
            )
            done = self._match(
                screen, self.config.registration_done, self.config.state_threshold,
            )
            if done.found and done.confidence >= available.confidence:
                logger.info("QD | đã Báo danh quân đoàn")
                return "already_registered"
            if available.found:
                break
            if attempt + 1 < self.config.registration_wait_attempts:
                self.sleep(self.config.wait_seconds)
                screen = self.screen_provider()
        else:
            raise RuntimeError("Quân đoàn: hết thời gian chờ trạng thái Báo danh")
        self._tap(available)
        for _ in range(8):
            verify = self.screen_provider()
            verified = self._match(
                verify, self.config.registration_done, self.config.state_threshold,
            )
            if verified.found:
                logger.info("QD | Báo danh quân đoàn thành công")
                return "registered"
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Quân đoàn: bấm Báo danh nhưng chưa chuyển sang Đã báo danh")

    def _open_prayer(self, screen):
        entry = self._match(screen, self.config.prayer_entry)
        if not entry.found:
            raise RuntimeError("Quân đoàn: thiếu nút mở Cầu vận quân đoàn")
        self._tap(entry)
        screen, opened = self._wait_for([
            self.config.prayer_available, self.config.prayer_empty,
        ])
        if opened is None:
            raise RuntimeError("Quân đoàn: bấm Cầu vận nhưng tab chưa mở")
        return screen

    def _run_prayer(self, screen) -> str:
        logger = logging.getLogger("dc3q")
        for _ in range(self.config.max_steps):
            available = self._match(
                screen, self.config.prayer_available, self.config.state_threshold,
            )
            empty = self._match(
                screen, self.config.prayer_empty, self.config.state_threshold,
            )
            if empty.found and empty.confidence >= available.confidence:
                logger.info("QD | Cầu vận đã về 0")
                return "empty"
            if not available.found:
                raise RuntimeError("Quân đoàn: trạng thái Cầu vận không xác định")
            self._tap(available)
            logger.info("QD | bấm Cầu vận khi còn lượt (10/5)")
            screen = self.screen_provider()
        raise RuntimeError("Quân đoàn: Cầu vận chưa về 0 trong giới hạn")

    def recover_home(self) -> bool:
        logger = logging.getLogger("dc3q")
        for _ in range(12):
            screen = self.screen_provider()
            prayer_close = self._match(screen, self.config.prayer_close)
            if prayer_close.found:
                self._tap(prayer_close)
                logger.info("QD | recovery đóng Cầu vận")
                continue
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                logger.info("QD | recovery đóng Quân đoàn")
                continue
            state, _ = self._home_entry_state(screen)
            if state == "open":
                self._close_home_route()
                logger.info("QD | recovery đóng đường dẫn Quân đoàn")
                return True
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("QD | recovery đã về HOME")
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def _home_entry_state(self, screen):
        """Neo Trưởng thành: _02 ở mép phải mở; _01 gần giữa đóng."""
        anchor = self._match(screen, self.config.home_anchor, self.config.threshold)
        if not anchor.found:
            return "unknown", None
        width, height = self._screen_size(screen)
        y1 = max(0, anchor.y - 40)
        y2 = min(height, anchor.y + anchor.height + 100)
        # Trạng thái đã mở (_01) thắng tuyệt đối: _02 còn có thể khớp giả
        # với chi tiết bên phải sau animation mở.
        opened = self._match_roi(
            screen, self.config.entry_templates[0],
            (int(width * .38), y1, int(width * .62), y2),
            max(0.40, self.config.home_control_threshold),
        )
        if opened.found:
            return "open", opened
        closed = self._match_roi(
            screen, self.config.entry_templates[1],
            (int(width * .82), y1, width, y2), self.config.home_control_threshold,
        )
        if closed.found:
            return "closed", closed
        return "unknown", None

    def _open_home_entry(self, screen):
        state, control = self._home_entry_state(screen)
        if state == "open":
            return screen, control
        if state != "closed":
            raise RuntimeError("Quân đoàn: không xác định được nút đối diện Trưởng thành")
        self._tap(control)
        for _ in range(self.config.entrance_wait_attempts):
            screen = self.screen_provider()
            entrance = self._first(screen, self.config.entrance_templates)
            if entrance is not None:
                return screen, entrance
            state, opened = self._home_entry_state(screen)
            if state == "open":
                return screen, opened
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Quân đoàn: bấm nút bên phải nhưng chưa chuyển sang trạng thái mở")

    def _close_home_route(self) -> None:
        logger = logging.getLogger("dc3q")
        for _ in range(8):
            screen = self.screen_provider()
            state, control = self._home_entry_state(screen)
            if state == "closed":
                logger.info("QD | đường dẫn Quân đoàn đã đóng; ở HOME")
                return
            if state == "open":
                self._tap(control)
                continue
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Quân đoàn: không đóng được đường dẫn bằng screen_quan-doan_01")

    def _enter_real_guild(self):
        """Màn đường dẫn -> nút Vào quân đoàn -> màn Quân đoàn thật."""
        screen, entrance = self._wait_for(
            self.config.entrance_templates, self.config.entrance_wait_attempts,
        )
        if entrance is None:
            raise RuntimeError("Quân đoàn: đã mở đường dẫn nhưng thiếu nút Vào quân đoàn")
        self._tap(entrance)
        screen, panel = self._wait_for(self.config.panel_markers)
        if panel is None:
            raise RuntimeError("Quân đoàn: đã bấm Vào quân đoàn nhưng chưa vào màn Quân đoàn thật")
        return screen

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        self._open_home_entry(self.screen_provider())
        # Nút trạng thái mở chỉ là hậu điều kiện; bấm lại sẽ đóng đường dẫn.
        logger.info("QD | đã mở đường dẫn Quân đoàn; chờ nút Vào quân đoàn")
        screen = self._enter_real_guild()
        logger.info("QD | đã bấm Vào quân đoàn; vào màn Quân đoàn thật")
        self._register(screen)
        screen = self.screen_provider()
        screen = self._open_prayer(screen)
        self._run_prayer(screen)
        screen = self.screen_provider()
        prayer_close = self._match(screen, self.config.prayer_close)
        if not prayer_close.found:
            raise RuntimeError("Quân đoàn: Cầu vận về 0 nhưng thiếu nút đóng")
        self._tap(prayer_close)
        screen = self.screen_provider()
        close = self._match(screen, self.config.close_template)
        if not close.found:
            raise RuntimeError("Quân đoàn: hoàn tất nhưng thiếu nút đóng")
        self._tap(close)
        self._close_home_route()
        return True
