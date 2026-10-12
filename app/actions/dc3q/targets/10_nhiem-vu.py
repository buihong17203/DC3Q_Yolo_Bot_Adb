from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable
import unicodedata


@dataclass(frozen=True)
class NhiemVuConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    home_markers: list[Path]
    panel_markers: list[Path]
    close_point: tuple[int, int]
    blocked_popup_close_point: tuple[int, int]
    claim_button: Path
    available_markers: list[Path]
    claimed_markers: list[Path]
    unavailable_markers: list[Path]
    threshold: float = 0.60
    state_threshold: float = 0.76
    max_steps: int = 24
    wait_seconds: float = 0.8


class NhiemVuRunner:
    """Nhận rương Nhiệm vụ ngày; không bao giờ bấm Đến/bỏ qua nhiệm vụ."""
    runtime_task = "NHIEM_VU"

    def __init__(self, screen_provider, adb_input, vision, config: NhiemVuConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "nhiem_vu", template,
            self.config.threshold if threshold is None else threshold,
        ).match

    def _first(self, screen, templates: list[Path], threshold: float | None = None):
        for template in templates:
            match = self._match(screen, template, threshold)
            if match.found:
                return match
        return None

    @staticmethod
    def _plain(text: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(char)
        ).lower().replace(" ", "")

    def _ocr_rows(self, screen):
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np

        data = screen.data if hasattr(screen, "data") else screen
        image = np.asarray(data.convert("RGB")) if hasattr(data, "convert") else np.asarray(data)
        result, _ = RapidOCR()(image)
        return result or []

    def _ocr_text(self, screen) -> str:
        return " ".join(self._plain(str(row[1])) for row in self._ocr_rows(screen))

    def _ocr_center(self, screen, keyword: str, *, x_max: int = 9999):
        key = self._plain(keyword)
        for row in self._ocr_rows(screen):
            if key not in self._plain(str(row[1])):
                continue
            points = row[0]
            x = int(sum(point[0] for point in points) / len(points))
            y = int(sum(point[1] for point in points) / len(points))
            if x <= x_max:
                return x, y
        return None

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def _is_home(self, screen) -> bool:
        return self._first(screen, self.config.home_markers) is not None

    def _entry(self, screen):
        entry = self._first(screen, self.config.entry_templates)
        if entry is not None:
            return entry
        point = self._ocr_center(screen, "nhiemvu", x_max=100)
        if point is None:
            return None
        x, y = point
        return type("OcrMatch", (), {"x": x - 1, "y": y - 1, "width": 2, "height": 2})()

    def _is_blocking_popup(self, screen) -> bool:
        text = self._ocr_text(screen)
        return "nhannhiemvu" in text and "den" in text

    def _is_panel(self, screen) -> bool:
        text = self._ocr_text(screen)
        return "soinoihomnay" in text and "hangngay" in text

    def _available_chest(self, screen):
        return self._first(screen, self.config.available_markers, self.config.state_threshold)

    def _claim_button(self, screen):
        claim = self._match(screen, self.config.claim_button, self.config.state_threshold)
        return claim if claim.found else None

    def recover_home(self) -> bool:
        for _ in range(12):
            screen = self.screen_provider()
            if self._is_home(screen) and not self._is_panel(screen) and not self._is_blocking_popup(screen):
                return True
            if self._is_blocking_popup(screen):
                self.input.tap(*self.config.blocked_popup_close_point)
                self.sleep(self.config.wait_seconds)
                continue
            if self._is_panel(screen):
                self.input.tap(*self.config.close_point)
                self.sleep(self.config.wait_seconds)
                continue
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        opened = False
        awaiting_claim = False
        claims = 0

        for _ in range(self.config.max_steps):
            screen = self.screen_provider()
            if not opened:
                if not self._is_home(screen):
                    raise RuntimeError("Nhiệm vụ: điểm bắt đầu không phải HOME")
                entry = self._entry(screen)
                if entry is None:
                    raise RuntimeError("Nhiệm vụ: HOME thiếu control Nhiệm vụ")
                self._tap(entry)
                opened = True
                continue

            if self._is_blocking_popup(screen):
                logger.info("NV | popup nhiệm vụ chặn bảng Hằng ngày; đóng X, không bấm Đến")
                self.input.tap(*self.config.blocked_popup_close_point)
                self.sleep(self.config.wait_seconds)
                continue

            if self._is_home(screen) and not self._is_panel(screen):
                return True

            if not self._is_panel(screen):
                self.sleep(self.config.wait_seconds)
                continue

            claim = self._claim_button(screen)
            if awaiting_claim and claim is not None:
                self._tap(claim)
                awaiting_claim = False
                claims += 1
                logger.info("NV | nhận rương Hằng ngày | tổng=%d", claims)
                continue

            chest = self._available_chest(screen)
            if chest is not None:
                self._tap(chest)
                awaiting_claim = True
                continue

            if awaiting_claim:
                self.sleep(self.config.wait_seconds)
                continue

            logger.info("NV | hết rương có thể nhận; đóng bảng")
            self.input.tap(*self.config.close_point)
            self.sleep(self.config.wait_seconds)

        raise RuntimeError("Nhiệm vụ: vượt quá số bước cho phép")
