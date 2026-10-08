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
    kho_markers: list[Path]
    point_button: Path
    point_markers: list[Path]
    thien_van_banner: Path
    thien_van_markers: list[Path]
    thien_van_paid: Path
    nhan_duc_banner: Path
    nhan_duc_markers: list[Path]
    nhan_duc_free: Path
    nhan_duc_paid: Path
    chiem_tinh_banner: Path
    chiem_tinh_markers: list[Path]
    chiem_tinh_plus: list[Path]
    exchange_popup: list[Path]
    exchange_slider_max: Path
    exchange_confirm_point: tuple[int, int]
    exchange_slider_start: tuple[int, int]
    exchange_slider_end: tuple[int, int]
    exchange_quantity_plus_point: tuple[int, int]
    exchange_reward: list[Path]
    exchange_reward_dismiss_point: tuple[int, int]
    close_template: Path
    reward_marker: Path
    reward_dismiss: Path
    threshold: float = 0.70
    action_threshold: float = 0.80
    state_margin: float = 0.05
    close_threshold: float = 0.54
    max_steps: int = 40
    wait_seconds: float = 0.8


class VoTuongRunner:
    """Thiên Vận FREE -> Nhân Đức FREE -> exchange prayer charms -> HOME."""
    runtime_task = "VO_TUONG"

    def __init__(self, screen_provider, adb_input, vision, config: VoTuongConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep

    def _match(self, screen, template: Path, threshold: float | None = None):
        value = self.config.threshold if threshold is None else threshold
        return self.vision.find_template(screen, "vo_tuong", template, value).match

    def _first(self, screen, templates: list[Path], threshold: float | None = None):
        for template in templates:
            match = self._match(screen, template, threshold)
            if match.found:
                return match
        return None

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def _wait_first(self, templates: list[Path], attempts: int = 12,
                    threshold: float | None = None):
        last = None
        for _ in range(attempts):
            last = self.screen_provider()
            match = self._first(last, templates, threshold)
            if match is not None:
                return last, match
            self.sleep(self.config.wait_seconds)
        return last, None

    def _has_free_text(self, screen) -> bool:
        import unicodedata
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(self._screen_array(screen))
        text = " ".join(str(row[1]) for row in (result or []))
        plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        logging.getLogger("dc3q").info("VT | OCR FREE=%r", text)
        return "mien" in plain and "phi" in plain

    def _ocr_plain(self, screen, label: str) -> str:
        import unicodedata
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(self._screen_array(screen))
        text = " ".join(str(row[1]) for row in (result or []))
        plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        logging.getLogger("dc3q").info("VT | OCR %s=%r", label, text)
        return plain

    def _has_exchange_popup_text(self, screen) -> bool:
        plain = self._ocr_plain(screen, "popup đổi")
        return "phu cau nguyen" in plain and "doi" in plain

    def _has_insufficient_exchange_text(self, screen) -> bool:
        plain = self._ocr_plain(screen, "thiếu Chiêu Hiền Lệnh")
        return "chieu hien lenh" in plain and ("khong du" in plain or "khongdu" in plain)

    def _wait_exchange_popup(self, attempts: int = 4):
        last = None
        for _ in range(attempts):
            last = self.screen_provider()
            marker = self._first(last, self.config.exchange_popup)
            if marker is not None or self._has_exchange_popup_text(last):
                return last, marker or True
            if self._has_insufficient_exchange_text(last):
                return last, False
            self.sleep(self.config.wait_seconds)
        return last, None

    @staticmethod
    def _screen_array(screen):
        import cv2
        import numpy as np
        if isinstance(screen, np.ndarray):
            return screen
        if isinstance(screen, (bytes, bytearray)):
            return cv2.imdecode(np.frombuffer(screen, dtype=np.uint8), cv2.IMREAD_COLOR)
        if hasattr(screen, "convert"):
            return cv2.cvtColor(np.array(screen.convert("RGB")), cv2.COLOR_RGB2BGR)
        return cv2.imread(str(screen))

    def _thien_van_free(self):
        screen = self.screen_provider()
        control = self._match(screen, self.config.thien_van_paid, 0.0)
        if control.confidence >= self.config.action_threshold and self._has_free_text(screen):
            return screen, control
        return screen, None

    def _nhan_duc_free(self):
        screen = self.screen_provider()
        free = self._match(screen, self.config.nhan_duc_free, 0.0)
        paid = self._match(screen, self.config.nhan_duc_paid, 0.0)
        logging.getLogger("dc3q").info(
            "VT | Nhân Đức FREE=%.3f | 25_tướng_hồn=%.3f",
            free.confidence, paid.confidence,
        )
        if (free.confidence >= self.config.action_threshold
                and free.confidence >= paid.confidence + self.config.state_margin):
            return screen, free
        return screen, None

    def _leave_paid_draw(self, screen, paid_template: Path, name: str):
        paid = self._match(screen, paid_template)
        if not paid.found:
            raise RuntimeError(f"Võ tướng: {name} không chứng minh được FREE/trả phí")
        back = self._match(screen, self.config.reward_dismiss)
        if not back.found:
            raise RuntimeError(f"Võ tướng: {name} trả phí nhưng thiếu Trở về")
        self._tap(back)
        screen, point = self._wait_first(self.config.point_markers)
        if point is None:
            raise RuntimeError(f"Võ tướng: {name} Trở về nhưng chưa thấy Điểm tướng")
        logging.getLogger("dc3q").info("VT | %s đã trả phí; không bấm", name)
        return screen

    def _draw_or_return(self, name: str, markers: list[Path], paid: Path, free_gate):
        screen, state = self._wait_first(markers)
        if state is None:
            raise RuntimeError(f"Võ tướng: {name} thiếu trạng thái")
        screen, free = free_gate()
        if free is None:
            return self._leave_paid_draw(screen, paid, name)
        self._tap(free)
        logging.getLogger("dc3q").info("VT | %s bấm Rút 1 lần MIỄN PHÍ", name)
        screen, back = self._wait_first([self.config.reward_dismiss], attempts=24)
        if back is None:
            raise RuntimeError(f"Võ tướng: {name} FREE thiếu Trở về kết quả")
        self._tap(back)
        screen, point = self._wait_first(self.config.point_markers)
        if point is None:
            raise RuntimeError(f"Võ tướng: {name} Trở về nhưng chưa thấy Điểm tướng")
        return screen

    def _run_exchange(self):
        logger = logging.getLogger("dc3q")
        screen, state = self._wait_first(self.config.chiem_tinh_markers)
        if state is None:
            raise RuntimeError("Võ tướng: chưa mở Chiêm Tinh Ước Nguyện")
        plus = self._first(screen, self.config.chiem_tinh_plus)
        if plus is None:
            raise RuntimeError("Võ tướng: Chiêm Tinh thiếu nút +")
        popup = None
        for attempt in range(2):
            self._tap(plus)
            screen, popup = self._wait_exchange_popup(attempts=4)
            if popup is False:
                logger.info("VT | thiếu Chiêu Hiền Lệnh; bỏ đổi Phù cầu nguyện")
                return screen
            if popup is not None:
                break
            if self._has_insufficient_exchange_text(screen):
                logger.info("VT | thiếu Chiêu Hiền Lệnh; bỏ đổi Phù cầu nguyện")
                return screen
            plus = self._first(screen, self.config.chiem_tinh_plus)
            if plus is None:
                raise RuntimeError("Võ tướng: tap + đổi màn nhưng popup không được chứng minh")
            logging.getLogger("dc3q").warning(
                "VT | nút + chưa chuyển trạng thái | lần=%d/2", attempt + 1,
            )
        if popup is None:
            raise RuntimeError("Võ tướng: nút + chưa mở popup Phù cầu nguyện đổi sau 2 lần")

        # Coordinate gestures are authorized only while the popup marker is fresh.
        if (self._first(screen, self.config.exchange_popup) is None
                and not self._has_exchange_popup_text(screen)):
            raise RuntimeError("Võ tướng: popup đổi không còn trước khi kéo")
        self.input.swipe(*self.config.exchange_slider_start, *self.config.exchange_slider_end, 700)
        self.sleep(self.config.wait_seconds)
        screen = self.screen_provider()
        if (self._first(screen, self.config.exchange_popup) is None
                and not self._has_exchange_popup_text(screen)):
            raise RuntimeError("Võ tướng: popup đổi mất sau khi kéo")
        if not self._match(screen, self.config.exchange_slider_max).found:
            for attempt in range(2):
                screen = self.screen_provider()
                if (self._first(screen, self.config.exchange_popup) is None
                        and not self._has_exchange_popup_text(screen)):
                    raise RuntimeError("Võ tướng: popup đổi mất trước khi bấm + số lượng")
                self.input.tap(*self.config.exchange_quantity_plus_point)
                self.sleep(self.config.wait_seconds)
                logger.info("VT | kéo chưa đạt; bấm + số lượng | lần=%d/2", attempt + 1)
            screen = self.screen_provider()
        if (self._first(screen, self.config.exchange_popup) is None
                and not self._has_exchange_popup_text(screen)):
            raise RuntimeError("Võ tướng: popup đổi mất trước khi bấm giá")
        self.input.tap(*self.config.exchange_confirm_point)
        logger.info("VT | popup proven; bấm xác nhận đổi")

        screen, reward = self._wait_first(self.config.exchange_reward, attempts=20)
        if reward is None:
            # Popup disappearing is still a valid completed exchange.
            screen = self.screen_provider()
            if self._first(screen, self.config.exchange_popup) is not None:
                raise RuntimeError("Võ tướng: bấm đổi nhưng popup vẫn còn")
            return screen
        self.input.tap(*self.config.exchange_reward_dismiss_point)
        self.sleep(self.config.wait_seconds)
        screen = self.screen_provider()
        if self._first(screen, self.config.exchange_reward) is not None:
            raise RuntimeError("Võ tướng: màn thưởng Phù cầu nguyện chưa đóng")
        return screen

    def _close_to_home(self):
        for _ in range(4):
            screen = self.screen_provider()
            if self._first(screen, self.config.home_markers) is not None:
                return True
            close = self._match(screen, self.config.close_template, self.config.close_threshold)
            if not close.found:
                return False
            self._tap(close)
        return self._first(self.screen_provider(), self.config.home_markers) is not None

    def recover_home(self) -> bool:
        return self._close_to_home()

    def _run_optional_exchange(self) -> bool:
        logger = logging.getLogger("dc3q")
        try:
            screen = self.screen_provider()
            chiem = self._match(screen, self.config.chiem_tinh_banner)
            if not chiem.found:
                logger.info("VT | Chiêm Tinh không khả dụng; bỏ qua")
                return False
            self._tap(chiem)
            self._run_exchange()
            return True
        except Exception as exc:
            logger.warning("VT | Chiêm Tinh bỏ qua | lý_do=%s", exc)
            return False

    def run(self) -> bool:
        screen = self.screen_provider()
        entry = self._first(screen, self.config.entry_templates)
        if entry is None:
            menu = self._first(screen, self.config.menu_templates)
            if menu is None:
                raise RuntimeError("Võ tướng: không tìm thấy menu mở rộng tại HOME")
            self._tap(menu)
            screen, entry = self._wait_first(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Võ tướng: không tìm thấy icon Võ Tướng")
        self._tap(entry)
        screen, kho = self._wait_first(self.config.kho_markers)
        if kho is None:
            raise RuntimeError("Võ tướng: chưa thấy Kho tướng")
        point = self._match(screen, self.config.point_button)
        if not point.found:
            raise RuntimeError("Võ tướng: thiếu nút Điểm tướng")
        self._tap(point)
        screen, point_state = self._wait_first(self.config.point_markers)
        if point_state is None:
            raise RuntimeError("Võ tướng: chưa mở Điểm tướng")

        thien = self._match(screen, self.config.thien_van_banner)
        if not thien.found:
            raise RuntimeError("Võ tướng: thiếu Thiên Vận Kỳ Tướng")
        self._tap(thien)
        self._draw_or_return("Thiên Vận", self.config.thien_van_markers,
                             self.config.thien_van_paid, self._thien_van_free)

        screen = self.screen_provider()
        nhan = self._match(screen, self.config.nhan_duc_banner)
        if not nhan.found:
            raise RuntimeError("Võ tướng: thiếu Nhân Đức Tụ Tướng")
        self._tap(nhan)
        self._draw_or_return("Nhân Đức", self.config.nhan_duc_markers,
                             self.config.nhan_duc_paid, self._nhan_duc_free)

        self._run_optional_exchange()
        if not self._close_to_home():
            raise RuntimeError("Võ tướng: hoàn tất nhưng chưa về HOME")
        logging.getLogger("dc3q").info("VT | hoàn tất toàn bộ luồng, đã về HOME")
        return True
