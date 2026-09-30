from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


class TargetAction:
    """Base target action. Concrete targets must prove each UI transition."""

    def execute(self, context: dict):
        raise NotImplementedError


@dataclass(frozen=True)
class TamQuocLenhConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    panel_markers: list[Path]
    close_template: Path
    reward_marker: Path
    reward_dismiss: Path
    que_boi_tabs: list[Path]
    que_boi_open: list[Path]
    que_boi_free: Path
    que_boi_paid: Path
    diem_binh_tabs: list[Path]
    diem_binh_open: list[Path]
    diem_binh_free: Path
    diem_binh_paid: Path
    action_roi: tuple[int, int, int, int]
    home_markers: list[Path]
    action_threshold: float = 0.85
    advance_popup_marker: Path | None = None
    advance_popup_close: Path | None = None
    inactivity_marker: Path | None = None
    inactivity_return: Path | None = None
    threshold: float = 0.60
    max_steps: int = 30
    wait_seconds: float = 0.8


class TamQuocLenhRunner:
    """Bounded Tam Quốc Lệnh flow; only whitelisted free controls are tapped."""
    runtime_task = "TAM_QUOC_LENH"

    def __init__(self, screen_provider, adb_input, vision, config: TamQuocLenhConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "tam_quoc_lenh", template,
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

    def _tap_action(self, match) -> None:
        x1, y1, _, _ = self.config.action_roi
        self.input.tap(x1 + match.x + match.width // 2, y1 + match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def _action_state(self, screen, free_template: Path, paid_template: Path):
        """Classify the x1 price line inside its fixed action ROI."""
        data = screen.data if hasattr(screen, "data") else screen
        x1, y1, x2, y2 = self.config.action_roi
        if hasattr(data, "crop"):
            cropped = data.crop((x1, y1, x2, y2))
        elif hasattr(data, "shape"):
            cropped = data[y1:y2, x1:x2]
        else:
            cropped = data
        free = self._match(cropped, free_template, self.config.action_threshold)
        paid = self._match(cropped, paid_template, self.config.action_threshold)
        margin = 0.05
        if free.found and free.confidence >= paid.confidence + margin:
            return "free", free, paid
        if paid.found and paid.confidence >= free.confidence + margin:
            return "paid", free, paid
        return "unknown", free, paid

    def recover_home(self) -> bool:
        """Close only recognized TQL layers; never use Android Back/Esc."""
        logger = logging.getLogger("dc3q")
        for _ in range(12):
            screen = self.screen_provider()
            if self.config.advance_popup_marker and self.config.advance_popup_close:
                if self._match(screen, self.config.advance_popup_marker).found:
                    close = self._match(screen, self.config.advance_popup_close)
                    if not close.found:
                        return False
                    self._tap(close)
                    logger.info("TQL | recovery đóng popup Tiến giai")
                    continue
            if self.config.inactivity_marker and self.config.inactivity_return:
                if self._match(screen, self.config.inactivity_marker).found:
                    control = self._match(screen, self.config.inactivity_return)
                    if not control.found:
                        return False
                    self._tap(control)
                    logger.info("TQL | recovery bấm Về lãnh địa")
                    continue
            if self._match(screen, self.config.reward_marker).found:
                dismiss = self._match(screen, self.config.reward_dismiss)
                if not dismiss.found:
                    return False
                self._tap(dismiss)
                logger.info("TQL | recovery đóng thưởng")
                continue
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                logger.info("TQL | recovery đóng bảng")
                continue
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("TQL | recovery đã về HOME")
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        opened = False
        panel_seen = False
        que_done = False
        diem_done = False
        que_tab_opened = False
        diem_tab_opened = False
        waiting_for: str | None = None
        unknown = 0

        for _ in range(self.config.max_steps):
            screen = self.screen_provider()

            if self.config.advance_popup_marker and self.config.advance_popup_close:
                advance_popup = self._match(screen, self.config.advance_popup_marker)
                if advance_popup.found:
                    close = self._match(screen, self.config.advance_popup_close)
                    if not close.found:
                        raise RuntimeError("Tam Quốc Lệnh: thấy popup Tiến giai lệnh bài nhưng thiếu nút đóng")
                    self._tap(close)
                    logger.info("TQL | đóng popup Tiến giai lệnh bài")
                    unknown = 0
                    continue

            if self.config.inactivity_marker and self.config.inactivity_return:
                inactive = self._match(screen, self.config.inactivity_marker)
                if inactive.found:
                    return_control = self._match(screen, self.config.inactivity_return)
                    if not return_control.found:
                        raise RuntimeError("Tam Quốc Lệnh: thấy popup mất liên hệ nhưng thiếu nút Về lãnh địa")
                    self._tap(return_control)
                    logger.info("TQL | bấm Về lãnh địa sau popup mất liên hệ")
                    unknown = 0
                    continue

            # HOME marker can remain visible behind the Tam Quốc Lệnh panel.
            # Accept completion only after both actions and the panel disappears.
            if (
                panel_seen and que_done and diem_done
                and self._first(screen, self.config.home_markers)
                and self._first(screen, self.config.panel_markers) is None
            ):
                return True

            reward = self._match(screen, self.config.reward_marker)
            if reward.found:
                panel_seen = True
                dismiss = self._match(screen, self.config.reward_dismiss)
                if not dismiss.found:
                    raise RuntimeError("Tam Quốc Lệnh: thấy thưởng nhưng thiếu vùng đóng an toàn")
                self._tap(dismiss)
                completed_action = waiting_for
                if completed_action == "que":
                    que_done = True
                elif completed_action == "diem":
                    diem_done = True
                self._last_completed_action = completed_action
                waiting_for = None
                logger.info("TQL | đóng thưởng | hoàn tất=%s", completed_action or "-")
                unknown = 0
                continue

            if not opened:
                entry = self._first(screen, self.config.entry_templates)
                if entry is not None:
                    self._tap(entry)
                    logger.info("TQL | mở Tam Quốc Lệnh")
                    opened = True
                    unknown = 0
                    continue
                menu = self._first(screen, self.config.menu_templates)
                if menu is not None:
                    self._tap(menu)
                    logger.info("TQL | mở menu HOME")
                    unknown = 0
                    continue
                unknown += 1
                if unknown >= 3:
                    raise RuntimeError("Tam Quốc Lệnh: không tìm thấy icon tại HOME")
                self.sleep(self.config.wait_seconds)
                continue

            if not que_done:
                if not que_tab_opened:
                    tab = self._first(screen, self.config.que_boi_tabs)
                    if tab is not None:
                        panel_seen = True
                        self._tap(tab)
                        verify = None
                        for _ in range(8):
                            verify = self.screen_provider()
                            if self._first(verify, self.config.que_boi_open) is not None:
                                break
                            self.sleep(self.config.wait_seconds)
                        else:
                            raise RuntimeError("Tam Quốc Lệnh: bấm Quẻ bói nhưng tab chưa mở sau khi chờ")
                        que_tab_opened = True
                        logger.info("TQL | mở tab Quẻ bói")
                        continue
                    self.sleep(self.config.wait_seconds)
                    continue
                state, free, paid = self._action_state(
                    screen, self.config.que_boi_free, self.config.que_boi_paid,
                )
                logger.info(
                    "TQL | Quẻ bói state=%s | free=%.3f | paid99=%.3f",
                    state, free.confidence, paid.confidence,
                )
                if waiting_for == "que":
                    if state == "paid":
                        que_done = True
                        waiting_for = None
                        logger.info("TQL | xác nhận Quẻ bói = 99 vàng")
                    else:
                        self.sleep(self.config.wait_seconds)
                        continue
                if state == "free":
                    self._tap_action(free)
                    waiting_for = "que"
                    logger.info("TQL | bấm Quẻ bói FREE")
                    continue
                if state == "paid":
                    que_done = True
                    logger.info("TQL | Quẻ bói không còn FREE; chuyển sang Điểm binh")
                    continue

            if not diem_done:
                if not diem_tab_opened:
                    tab = self._first(screen, self.config.diem_binh_tabs)
                    if tab is not None:
                        panel_seen = True
                        self._tap(tab)
                        verify = None
                        for _ in range(8):
                            verify = self.screen_provider()
                            if self._first(verify, self.config.diem_binh_open) is not None:
                                break
                            self.sleep(self.config.wait_seconds)
                        else:
                            raise RuntimeError("Tam Quốc Lệnh: bấm Điểm binh nhưng tab chưa mở sau khi chờ")
                        diem_tab_opened = True
                        logger.info("TQL | mở tab Điểm binh")
                        continue
                    self.sleep(self.config.wait_seconds)
                    continue
                state, free, paid = self._action_state(
                    screen, self.config.diem_binh_free, self.config.diem_binh_paid,
                )
                logger.info(
                    "TQL | Điểm binh state=%s | free=%.3f | paid100=%.3f",
                    state, free.confidence, paid.confidence,
                )
                if waiting_for == "diem":
                    if state == "paid":
                        diem_done = True
                        waiting_for = None
                        logger.info("TQL | xác nhận Điểm binh = 100 vàng")
                    else:
                        self.sleep(self.config.wait_seconds)
                        continue
                if state == "free":
                    self._tap_action(free)
                    waiting_for = "diem"
                    logger.info("TQL | bấm Điểm binh FREE")
                    continue
                if state == "paid":
                    diem_done = True
                    logger.info("TQL | Điểm binh không còn FREE")
                    continue


            if que_done and diem_done:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    raise RuntimeError("Tam Quốc Lệnh: hoàn tất nhưng thiếu nút đóng")
                self._tap(close)
                logger.info("TQL | đóng bảng sau khi hoàn tất")
                continue

            if self._first(screen, self.config.panel_markers) is not None:
                panel_seen = True
                unknown += 1
                if unknown >= 3:
                    raise RuntimeError("Tam Quốc Lệnh: state trong popup không xác định")
                self.sleep(self.config.wait_seconds)
                continue

            raise RuntimeError("Tam Quốc Lệnh: màn hình không xác định")

        raise RuntimeError("Tam Quốc Lệnh: vượt quá số bước cho phép")
