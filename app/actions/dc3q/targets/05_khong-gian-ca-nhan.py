from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class KhongGianCaNhanConfig:
    entry_templates: list[Path]
    info_markers: list[Path]
    personal_markers: list[Path]
    close_template: Path
    home_markers: list[Path]
    like_before: Path
    like_after: Path
    like_all: Path
    share_before: Path
    share_panel: Path
    share_button: Path
    share_after: list[Path]
    threshold: float = 0.65
    state_threshold: float = 0.80
    max_steps: int = 24
    wait_seconds: float = 0.8
    state_wait_attempts: int = 24


class KhongGianCaNhanRunner:
    runtime_task = "KHONG_GIAN_CA_NHAN"

    def __init__(self, screen_provider, adb_input, vision, config: KhongGianCaNhanConfig,
                 sleep: Callable[[float], None] = default_sleep,
                 home_entry: Callable[[object], tuple[int, int] | None] | None = None):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep
        self.home_entry = home_entry

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "khong_gian_ca_nhan", template,
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
            if self._first(screen, self.home_templates()) is not None:
                return True
            if self._first(screen, self.config.personal_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                continue
            self.sleep(self.config.wait_seconds)
        return False

    def home_templates(self) -> list[Path]:
        return self.config.home_markers

    def _like_once(self, screen):
        before = self._match(screen, self.config.like_before, self.config.state_threshold)
        after = self._match(screen, self.config.like_after, self.config.state_threshold)
        if after.found and after.confidence >= before.confidence:
            return screen
        if not before.found or before.confidence <= after.confidence:
            raise RuntimeError("Không gian cá nhân: không xác định được trạng thái like")
        self._tap(before)
        return self._prove([self.config.like_after], "Không gian cá nhân: thiếu hậu điều kiện đã like")

    def _share_once(self, screen):
        before = self._match(screen, self.config.share_before, self.config.state_threshold)
        if not before.found:
            return screen
        self._tap(before)
        panel = self._prove([self.config.share_panel], "Không gian cá nhân: thiếu hậu điều kiện mở bảng chia sẻ")
        button = self._match(panel, self.config.share_button, self.config.state_threshold)
        if not button.found:
            raise RuntimeError("Không gian cá nhân: thiếu nút chia sẻ an toàn")
        self._tap(button)
        return self._prove(self.config.share_after, "Không gian cá nhân: thiếu hậu điều kiện sau chia sẻ")

    def _like_all(self, screen):
        for attempt in range(self.config.state_wait_attempts):
            button = self._match(screen, self.config.like_all, self.config.state_threshold)
            if button.found:
                break
            if attempt + 1 < self.config.state_wait_attempts:
                self.sleep(self.config.wait_seconds)
                screen = self.screen_provider()
        else:
            raise RuntimeError("Không gian cá nhân: hết thời gian chờ nút Like toàn bộ")
        self._tap(button)
        return self._prove(
            [self.config.like_after],
            "Không gian cá nhân: Like toàn bộ chưa tạo trạng thái đã like",
        )

    def run(self) -> bool:
        screen = self.screen_provider()
        if self._first(screen, self.config.personal_markers) is None:
            if self._first(screen, self.config.info_markers) is None:
                point = self.home_entry(screen) if self.home_entry else None
                if point is None:
                    raise RuntimeError("Không gian cá nhân: HOME chưa chứng minh được nút mở hồ sơ")
                self.input.tap(*point)
                self.sleep(self.config.wait_seconds)
                screen = self._prove(
                    self.config.info_markers,
                    "Không gian cá nhân: bấm avatar nhưng chưa thấy Thông tin của tôi",
                )
            screen = self._share_once(screen)
            entry = self._first(screen, self.config.entry_templates)
            if entry is None:
                raise RuntimeError("Không gian cá nhân: không tìm thấy nút mở")
            self._tap(entry)
            screen = self._prove(self.config.personal_markers, "Không gian cá nhân: bấm mở nhưng chưa thấy panel")
        screen = self._like_all(screen)
        close = self._match(screen, self.config.close_template)
        if close.found:
            self._tap(close)
        if not self.recover_home():
            raise RuntimeError("Không gian cá nhân: không recover_home được")
        return True
