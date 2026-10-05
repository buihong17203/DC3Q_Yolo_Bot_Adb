from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


def _last_ocr_number(texts) -> int | None:
    import re
    values = [int(value) for text in texts for value in re.findall(r"\d+", str(text))]
    return values[-1] if values else None


@dataclass(frozen=True)
class SubFlow:
    name: str
    entry: list[Path]
    free: list[Path]
    spent: list[Path]
    close: list[Path]
    free_threshold: float = 0.90
    hub_entry: list[Path] | None = None
    repeat_free: bool = False
    close_threshold: float = 0.70
    bonus_continue: list[Path] | None = None
    bonus_tap_point: tuple[int, int] = (480, 360)


@dataclass(frozen=True)
class TruongThanhConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    home_markers: list[Path]
    close_templates: list[Path]
    bonus_continue_templates: list[Path]
    bonus_continue_point: tuple[int, int]
    a4_return_templates: list[Path]
    hub_markers: list[Path]
    a1_entry: Path
    a1_view: Path
    a1_plus_slot: Path
    a1_execute: list[Path]
    a1_running: list[Path]
    a1_card_centers: list[tuple[int, int]]
    a1_close_point: tuple[int, int]
    a1_reward: Path
    a1_execution_count_roi: tuple[int, int, int, int]
    a1_locked_slot: Path
    a1_assist: Path
    a1_assist_count_roi: tuple[int, int, int, int]
    a1_assist_popup: Path
    a1_assist_confirm: Path
    a1_board_swipe: tuple[int, int, int, int, int]
    a1_max_board_swipes: int
    a1_back_point: tuple[int, int]
    a2_entry: Path
    a2_open: list[Path]
    a2_main: list[Path]
    a2_free: Path
    a2_paid: Path
    a2_rewards: list[Path]
    a2_popup_close: Path
    a2_tab_closed: list[Path]
    a2_tab_open: list[Path]
    a2_reward_close: Path
    a2_chest_glowing: Path
    a2_chest_popup: Path
    a2_chest_popup_close: Path
    a2_chest_popup_close_point: tuple[int, int]
    a2_reset_2000: Path
    a3_right_anchor: Path
    a3_markers: list[Path]
    a3_phong_hau_open: list[Path]
    a3_tab_closed: list[Path]
    a3_tab_open: list[Path]
    a3_close_point: tuple[int, int]
    a3_raise_flag: list[Path]
    a3_result: list[Path]
    a3_result_dismiss_point: tuple[int, int]
    a4_hub_entry: list[Path]
    a4_entry: list[Path]
    a4_free: list[Path]
    a4_bonus_continue: list[Path]
    a4_reward: list[Path]
    a4_return: list[Path]
    a4_paid: list[Path]
    a4_close_point: tuple[int, int]
    a4_recall: list[Path]
    a5_normal_free: list[Path]
    a5_gold_free: list[Path]
    a5_normal_select: Path
    a5_quick: Path
    a5_initial_close: Path
    a5_normal_quantity_roi: tuple[int, int, int, int]
    a5_normal_free_roi: tuple[int, int, int, int]
    a5_gold_quantity_roi: tuple[int, int, int, int]
    a5_gold_free_roi: tuple[int, int, int, int]
    a5_reward_dismiss_point: tuple[int, int]
    a5_max_adjustments: int
    a7_free_label_roi: tuple[int, int, int, int]
    state_threshold: float
    state_margin: float
    skipped_subflows: list[str]
    flows: list[SubFlow]
    threshold: float = 0.70
    max_steps: int = 60
    wait_seconds: float = 0.8


class TruongThanhRunner:
    """Trường thành runner: only pre-proven free controls; no paid/resource clicks."""
    runtime_task = "TT_A1_BAO_VAT"

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

    def _first(self, screen, templates: list[Path], threshold: float | None = None):
        for template in templates:
            match = self._match(screen, template, threshold)
            if match.found:
                return match
        return None

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def _wait_first(self, templates: list[Path], attempts: int = 6,
                    threshold: float | None = None):
        screen = None
        for _ in range(attempts):
            screen = self.screen_provider()
            match = self._first(screen, templates, threshold)
            if match is not None:
                return screen, match
            self.sleep(self.config.wait_seconds)
        return screen, None

    def recover_home(self) -> bool:
        logger = logging.getLogger("dc3q")
        # reverse-layer close: reward/result child layers before panels.
        a4_return_tapped = False
        for _ in range(12):
            recover_anr = getattr(getattr(self, "input", None), "recover_anr_wait", None)
            if recover_anr is not None and recover_anr():
                self.sleep(self.config.wait_seconds)
                logger.info("TT | recovery xử lý ANR bằng Đợi")
                continue
            screen = self.screen_provider()
            bonus_templates = getattr(self.config, "bonus_continue_templates", [])
            if bonus_templates and self._first(screen, bonus_templates, 0.90) is not None:
                self.input.tap(*self.config.bonus_continue_point)
                self.sleep(self.config.wait_seconds)
                logger.info("TT | recovery đóng thưởng Vệ Tướng nguyên con")
                continue
            a4_return = getattr(self.config, "a4_return_templates", [])
            if not a4_return_tapped and a4_return:
                return_control = self._first(screen, a4_return, 0.95)
                if return_control is not None:
                    self._tap(return_control)
                    a4_return_tapped = True
                    logger.info("TT | recovery A4 bấm Trở về")
                    continue
            if self._first(screen, self.config.hub_markers) is not None:
                toggle = self._first(screen, self.config.entry_templates)
                if toggle is None:
                    return False
                self._tap(toggle)
                logger.info("TT | recovery đóng hub Trường thành")
                continue
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("TT | recovery đã về HOME")
                return True
            chest_popup = getattr(self.config, "a2_chest_popup", None)
            chest_close = getattr(self.config, "a2_chest_popup_close", None)
            if (chest_popup is not None and chest_close is not None
                    and self._match(screen, chest_popup).found):
                close = self._match(screen, chest_close)
                if not close.found:
                    return False
                self._tap(close)
                logger.info("TT | recovery đóng Rương chiến lợi phẩm từ full-screen")
                continue
            # A1 Chính vụ has no dedicated X template, but a verified Xem/
            # Nhận thưởng control proves this exact board. Close its known X.
            a1_view = getattr(self.config, "a1_view", None)
            a1_reward = getattr(self.config, "a1_reward", None)
            if ((a1_view is not None and self._match(screen, a1_view).found)
                    or (a1_reward is not None and self._match(screen, a1_reward).found)):
                self.input.tap(*self.config.a1_close_point)
                self.sleep(self.config.wait_seconds)
                logger.info("TT | recovery đóng bảng Chính vụ A1")
                continue
            close = self._first(screen, self.config.close_templates)
            if close is None:
                self.sleep(self.config.wait_seconds)
                continue
            self._tap(close)
            logger.info("TT | recovery đóng layer")
        return False

    def _a1_plus_count(self, screen) -> int:
        import cv2
        import numpy as np
        data = screen.data if hasattr(screen, "data") else screen
        data = np.asarray(data.convert("RGB")) if hasattr(data, "convert") and not hasattr(data, "shape") else np.asarray(data)
        template = cv2.imread(str(self.config.a1_plus_slot), cv2.IMREAD_COLOR)
        source = cv2.cvtColor(data, cv2.COLOR_RGB2GRAY) if data.ndim == 3 else data
        target = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        scores = cv2.matchTemplate(source, target, cv2.TM_CCOEFF_NORMED)
        # Live selected-card animation lowers the remaining empty-slot score to
        # ~0.89; locked-slot collision measured 0.62 on the same frame.
        count, _, _, _ = cv2.connectedComponentsWithStats((scores >= 0.85).astype("uint8"))
        return max(0, count - 1)

    def _a1_claim_rewards(self, screen):
        """Claim all visible rewards, then sweep the mission board boundedly."""
        logger = logging.getLogger("dc3q")
        for swipe_index in range(self.config.a1_max_board_swipes + 1):
            for _ in range(12):
                reward = self._match(screen, self.config.a1_reward)
                if reward is None or not reward.found:
                    break
                self._tap(reward)
                logger.info("TT | A1 nhận thưởng Chính vụ")
                screen = self.screen_provider()
            else:
                raise RuntimeError("Trường thành A1: vượt giới hạn nhận thưởng trong một viewport")
            if swipe_index == self.config.a1_max_board_swipes:
                break
            self.input.swipe(*self.config.a1_board_swipe)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
        return screen

    def _a1_board_verified(self, screen) -> bool:
        if self._match(screen, self.config.a1_view, 0.95).found:
            return True
        if self._match(screen, self.config.a1_reward).found:
            return True
        return self._first(screen, self.config.a1_running) is not None

    def _a1_open_next_mission(self, screen):
        if not self._a1_board_verified(screen):
            logging.getLogger("dc3q").error(
                "TT | A1 từ chối thao tác: chưa xác nhận đúng bảng Chính vụ"
            )
            return None
        remaining = self._read_roi_number(screen, self.config.a1_execution_count_roi)
        if remaining is None or remaining <= 0:
            logging.getLogger("dc3q").info(
                "TT | A1 dừng: số lần được thực hiện=%s", remaining,
            )
            return None
        for swipe_index in range(self.config.a1_max_board_swipes + 1):
            # Xem and Tăng tốc share button chrome. Live collision measured
            # Xem-template=0.759 on Tăng tốc; only a near-exact Xem may tap.
            view = self._match(screen, self.config.a1_view, 0.95)
            if view.found:
                self._tap(view)
                for _ in range(3):
                    detail = self.screen_provider()
                    if self._match(detail, self.config.a1_plus_slot).found:
                        logging.getLogger("dc3q").info(
                            "TT | A1 mở Chính vụ | lượt_trước=%d | vuốt=%d",
                            remaining, swipe_index,
                        )
                        return detail, remaining
                    self.sleep(self.config.wait_seconds)
                logging.getLogger("dc3q").error(
                    "TT | A1 bấm Xem nhưng vẫn ở bảng Chính vụ; đóng A1 an toàn"
                )
                return None
            if swipe_index == self.config.a1_max_board_swipes:
                break
            self.input.swipe(*self.config.a1_board_swipe)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
            if not self._a1_board_verified(screen):
                logging.getLogger("dc3q").error(
                    "TT | A1 dừng vuốt: frame mới không còn là bảng Chính vụ"
                )
                return None
        logging.getLogger("dc3q").info(
            "TT | A1 còn %d lượt nhưng không còn nút Xem sau %d lần vuốt",
            remaining, self.config.a1_max_board_swipes,
        )
        return None

    def _a1_request_assistance(self, screen):
        remaining = self._read_roi_number(screen, self.config.a1_assist_count_roi)
        if remaining is None or remaining <= 0:
            logging.getLogger("dc3q").info(
                "TT | A1 không cầu viện: số lần còn=%s", remaining,
            )
            return None
        assist = self._match(screen, self.config.a1_assist)
        if not assist.found:
            return None
        self._tap(assist)
        popup_screen = self.screen_provider()
        popup = self._match(popup_screen, self.config.a1_assist_popup)
        confirm = self._match(popup_screen, self.config.a1_assist_confirm)
        if not popup.found or not confirm.found:
            raise RuntimeError("Trường thành A1: Cầu viện nhưng thiếu popup/Xác nhận")
        self._tap(confirm)
        after_screen = self.screen_provider()
        after = self._read_roi_number(after_screen, self.config.a1_assist_count_roi)
        if after is None or after >= remaining:
            raise RuntimeError("Trường thành A1: xác nhận Cầu viện nhưng số lần còn không giảm")
        logging.getLogger("dc3q").info(
            "TT | A1 cầu viện thành công | lượt=%d→%d", remaining, after,
        )
        return after_screen

    def _a1_fill_and_execute(self, screen) -> bool:
        logger = logging.getLogger("dc3q")
        before = self._a1_plus_count(screen)
        # 1 = chưa thử trong detail hiện tại; sau một tap luôn chuyển 0.
        # Thẻ đã chọn/không hợp lệ không làm slot giảm và không được tap lại.
        candidates = {point: 1 for point in self.config.a1_card_centers}
        for point in self.config.a1_card_centers:
            if before == 0:
                break
            if not candidates[point]:
                continue
            self.input.tap(*point)
            candidates[point] = 0
            self.sleep(self.config.wait_seconds)
            verify = self.screen_provider()
            after = self._a1_plus_count(verify)
            if after < before:
                logger.info("TT | A1 chọn tướng | slot_trống=%d", after)
                screen, before = verify, after
        if before:
            assisted = self._a1_request_assistance(screen)
            if assisted is None:
                logger.info("TT | A1 SKIP_MISSION: thiếu tướng, hết/không rõ lượt cầu viện")
                return False
            screen = assisted
            before = self._a1_plus_count(screen)
        if before:
            logger.info("TT | A1 SKIP_MISSION: cầu viện xong vẫn thiếu slot")
            return False
        execute = self._first(screen, self.config.a1_execute)
        if execute is None:
            raise RuntimeError("Trường thành A1: đội đủ nhưng thiếu nút Chấp hành")
        self._tap(execute)
        _, running = self._wait_first(self.config.a1_running, attempts=12)
        if running is None:
            raise RuntimeError("Trường thành A1: chưa thấy Đang chấp hành")
        logger.info("TT | A1 xác nhận Đang chấp hành")
        return True

    def _run_a1(self) -> None:
        self._open_home_entry()
        screen = self.screen_provider()
        entry = self._match(screen, self.config.a1_entry)
        if not entry.found:
            logging.getLogger("dc3q").info("TT | A1 NOT_AVAILABLE")
            return
        self._tap(entry)
        screen, state = self._wait_first(
            [self.config.a1_reward, self.config.a1_view, *self.config.a1_running], attempts=12,
        )
        if state is None:
            raise RuntimeError("Trường thành A1: mở Bảo vật nhưng thiếu trạng thái Chính vụ")
        screen = self._a1_claim_rewards(screen)
        started = 0
        skipped = 0
        for _ in range(12):
            opened = self._a1_open_next_mission(screen)
            if opened is None:
                break
            screen, remaining_before = opened
            if not self._a1_fill_and_execute(screen):
                self.input.tap(*self.config.a1_back_point)
                self.sleep(self.config.wait_seconds)
                screen, board = self._wait_first(
                    [self.config.a1_reward, self.config.a1_view, *self.config.a1_running], attempts=8,
                )
                if board is None:
                    raise RuntimeError("Trường thành A1: bỏ nhiệm vụ nhưng chưa về bảng Chính vụ")
                skipped += 1
                if skipped > self.config.a1_max_board_swipes:
                    logging.getLogger("dc3q").info("TT | A1 hết danh sách nhiệm vụ phù hợp")
                    break
                continue
            started += 1
            # Live behavior: Chấp hành returns to the board automatically.
            # Never tap the old detail back coordinate here.
            screen, board = self._wait_first(
                [self.config.a1_reward, self.config.a1_view, *self.config.a1_running], attempts=8,
            )
            if board is None:
                raise RuntimeError("Trường thành A1: quay lại nhưng chưa thấy bảng Chính vụ")
            remaining_after = None
            for count_attempt in range(8):
                remaining_after = self._read_roi_number(screen, self.config.a1_execution_count_roi)
                if remaining_after == remaining_before - 1:
                    break
                if count_attempt < 7:
                    self.sleep(self.config.wait_seconds)
                    screen = self.screen_provider()
            if remaining_after == remaining_before - 1:
                logging.getLogger("dc3q").info(
                    "TT | A1 số lần được thực hiện | %d→%d",
                    remaining_before, remaining_after,
                )
            else:
                # The running marker and automatic return already prove dispatch.
                # Live OCR can remain stale/wrong (observed 6 while pixels show 7);
                # never replay or reject a proven dispatch because of that counter.
                logging.getLogger("dc3q").warning(
                    "TT | A1 bộ đếm chưa ổn định sau Chấp hành | OCR=%s→%s; "
                    "giữ hậu điều kiện Đang chấp hành",
                    remaining_before, remaining_after,
                )
            screen = self._a1_claim_rewards(screen)
        else:
            raise RuntimeError("Trường thành A1: vượt giới hạn 12 nhiệm vụ")
        logging.getLogger("dc3q").info("TT | A1 đã khởi chạy %d Chính vụ", started)
        self.input.tap(*self.config.a1_close_point)
        self.sleep(self.config.wait_seconds)
        _, hub = self._wait_first(self.config.hub_markers, attempts=8)
        if hub is None:
            raise RuntimeError("Trường thành A1: đóng Chính vụ nhưng chưa về hub")

    def _a2_state(self, screen):
        return (
            self._match(screen, self.config.a2_free, 0.0),
            self._match(screen, self.config.a2_paid, 0.0),
        )

    def _wait_a2_after_free(self, initial_screen=None):
        """Settle one free probe without ever touching the paid probe state."""
        logger = logging.getLogger("dc3q")
        screen = initial_screen
        for _ in range(24):
            if screen is None:
                screen = self.screen_provider()
            reset = self._match(screen, self.config.a2_reset_2000)
            if reset.found:
                self._tap(reset)
                logger.info("TT | A2 nhận 2000 và reset vùng thăm dò")
                screen = None
                continue
            if self._first(screen, self.config.a2_rewards) is not None:
                # Live popup X scores 0.652; the reward marker already proves
                # this exact layer, so keep the lower floor local to its X.
                close = self._match(screen, self.config.a2_reward_close, 0.60)
                if not close.found:
                    raise RuntimeError("Trường thành A2: có thưởng nhưng thiếu nút đóng")
                self._tap(close)
                logger.info("TT | A2 đóng popup thưởng thăm dò")
                screen = None
                continue
            chest_popup = self._match(screen, self.config.a2_chest_popup)
            if chest_popup.found:
                close = self._match(screen, self.config.a2_chest_popup_close)
                if not close.found:
                    raise RuntimeError("Trường thành A2: thấy Rương chiến lợi phẩm nhưng thiếu nút Đóng")
                self._tap(close)
                logger.info("TT | A2 đóng Rương chiến lợi phẩm từ full-screen")
                screen = None
                continue
            chest = self._match(screen, self.config.a2_chest_glowing)
            if chest.found:
                self._tap(chest)
                logger.info("TT | A2 mở rương thăm dò phát sáng")
                screen = None
                continue
            free, paid = self._a2_state(screen)
            if (free.confidence >= self.config.state_threshold
                    or paid.confidence >= self.config.state_threshold):
                return screen
            self.sleep(self.config.wait_seconds)
            screen = None
        raise RuntimeError("Trường thành A2: Thăm dò không có hậu điều kiện")

    def _a2_claim_free(self, screen) -> None:
        logger = logging.getLogger("dc3q")
        for _ in range(10):
            # Rương/reset/popup always outrank another probe, including on
            # the initial exploration frame where FREE may also be visible.
            screen = self._wait_a2_after_free(screen)
            free, paid = self._a2_state(screen)
            if paid.confidence >= self.config.state_threshold and paid.confidence >= free.confidence + self.config.state_margin:
                logger.info("TT | A2 dừng: lượt tiếp theo dùng 1 cuốn thư")
                return
            if free.confidence < self.config.state_threshold or free.confidence < paid.confidence + self.config.state_margin:
                logger.info("TT | A2 dừng fail-closed: trạng thái miễn phí không rõ")
                return
            self._tap(free)
            logger.info("TT | A2 bấm Thăm dò miễn phí")
            screen = self._wait_a2_after_free()
        raise RuntimeError("Trường thành A2: vượt giới hạn lượt miễn phí")

    def _run_a2(self) -> None:
        self._open_home_entry()
        screen = self.screen_provider()
        entry = self._match(screen, self.config.a2_entry)
        if not entry.found:
            logging.getLogger("dc3q").info("TT | A2 NOT_AVAILABLE")
            return
        self._tap(entry)
        screen, main = self._wait_first(self.config.a2_tab_closed + self.config.a2_tab_open, attempts=12)
        if main is None:
            raise RuntimeError("Trường thành A2: mở Tướng ấn nhưng thiếu trạng thái")
        opened = max(
            (self._match(screen, template, 0.0) for template in self.config.a2_tab_open),
            key=lambda match: match.confidence,
        )
        tab = max(
            (self._match(screen, template, 0.0) for template in self.config.a2_tab_closed),
            key=lambda match: match.confidence,
        )
        if tab.confidence >= self.config.threshold and tab.confidence >= opened.confidence + self.config.state_margin:
            self._tap(tab)
            screen, opened = self._wait_first(self.config.a2_tab_open, attempts=12)
            if opened is None:
                raise RuntimeError("Trường thành A2: bấm Tướng Tinh Đài nhưng tab chưa mở")
        elif opened.confidence < self.config.threshold or opened.confidence < tab.confidence + self.config.state_margin:
            raise RuntimeError("Trường thành A2: trạng thái tab Tướng Tinh Đài không rõ")
        open_control = self._first(screen, self.config.a2_open)
        if open_control is None:
            raise RuntimeError("Trường thành A2: thiếu nút Thăm dò lãnh địa")
        self._tap(open_control)
        screen, state = self._wait_first([self.config.a2_free, self.config.a2_paid], attempts=12)
        if state is None:
            raise RuntimeError("Trường thành A2: mở Thăm dò nhưng thiếu trạng thái")
        self._a2_claim_free(screen)

    @staticmethod
    def _screen_array(screen):
        import numpy as np
        data = screen.data if hasattr(screen, "data") else screen
        return np.asarray(data.convert("RGB")) if hasattr(data, "convert") and not hasattr(data, "shape") else np.asarray(data)

    def _a5_text(self, screen) -> str:
        from rapidocr_onnxruntime import RapidOCR
        result, _ = RapidOCR()(self._screen_array(screen))
        return " ".join(str(row[1]) for row in (result or []))

    def _a5_motion_target(self, before, after):
        import cv2
        import numpy as np
        a = self._screen_array(before)[100:390, 80:880]
        b = self._screen_array(after)[100:390, 80:880]
        diff = cv2.cvtColor(cv2.absdiff(a, b), cv2.COLOR_RGB2GRAY)
        diff = cv2.GaussianBlur(diff, (9, 9), 0)
        mask = (diff > 25).astype("uint8") * 255
        count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
        candidates = [(stats[i, cv2.CC_STAT_AREA], centers[i]) for i in range(1, count)
                      if 80 <= stats[i, cv2.CC_STAT_AREA] <= 12000]
        if not candidates:
            return None
        _, (x, y) = max(candidates, key=lambda item: item[0])
        return int(x + 80), int(y + 100)

    def _a5_tap_moving_horse(self, before, after) -> bool:
        import unicodedata
        text = unicodedata.normalize("NFKD", self._a5_text(after)).encode("ascii", "ignore").decode().lower()
        if "thu cuoi dang chay" not in text:
            return False
        point = self._a5_motion_target(before, after)
        if point is None:
            return False
        self.input.tap(*point)
        self.sleep(self.config.wait_seconds)
        return True

    def _tap_a3_entry(self, screen) -> None:
        left = self._match(screen, self.config.a2_entry)
        right = self._match(screen, self.config.a3_right_anchor)
        if not left.found or not right.found:
            raise RuntimeError("Trường thành A3: thiếu anchor Tướng ấn/Vệ Tướng")
        x = (left.x + left.width + right.x) // 2
        y = (left.y + left.height // 2 + right.y + right.height // 2) // 2
        self.input.tap(x, y)
        self.sleep(self.config.wait_seconds)

    def _a3_raise_flag(self, screen) -> None:
        control = self._first(screen, self.config.a3_raise_flag)
        if control is None:
            logging.getLogger("dc3q").info("TT | A3 Giương cờ không khả dụng/đã dùng")
            return
        self._tap(control)
        _, result = self._wait_first(self.config.a3_result, attempts=12)
        if result is None:
            raise RuntimeError("Trường thành A3: Giương cờ thiếu hậu điều kiện")
        logging.getLogger("dc3q").info("TT | A3 Giương cờ thành công")
        self.input.tap(*self.config.a3_result_dismiss_point)
        self.sleep(self.config.wait_seconds)
        _, opened = self._wait_first(self.config.a3_tab_open, attempts=12)
        if opened is None:
            raise RuntimeError("Trường thành A3: đóng popup nhưng chưa về tab Chiến Kỳ")

    def _open_a3_chien_ky(self, screen):
        """Open Chiến Kỳ from proven Phong Hậu; never trust tab chrome alone."""
        phong_hau = self._first(screen, self.config.a3_phong_hau_open)
        closed = self._first(screen, self.config.a3_tab_closed)
        flag = self._first(screen, self.config.a3_raise_flag)
        if flag is not None:
            return screen
        if phong_hau is not None:
            if closed is None:
                raise RuntimeError("Trường thành A3: đang ở Phong Hậu nhưng thiếu tab Chiến Kỳ")
            self._tap(closed)
            screen, state = self._wait_first(
                [*self.config.a3_raise_flag, *self.config.a3_tab_open], attempts=12,
            )
            if state is None:
                raise RuntimeError("Trường thành A3: bấm Chiến Kỳ nhưng tab chưa mở")
            return screen
        opened = max(
            (self._match(screen, template, 0.0) for template in self.config.a3_tab_open),
            key=lambda match: match.confidence,
        )
        if (closed is not None and closed.confidence >= self.config.threshold
                and closed.confidence >= opened.confidence + self.config.state_margin):
            self._tap(closed)
            screen, state = self._wait_first(
                [*self.config.a3_raise_flag, *self.config.a3_tab_open], attempts=12,
            )
            if state is None:
                raise RuntimeError("Trường thành A3: bấm Chiến Kỳ nhưng tab chưa mở")
            return screen
        raise RuntimeError("Trường thành A3: chưa chứng minh được tab Chiến Kỳ/Giương cờ")

    def _run_a3(self) -> None:
        self._open_home_entry()
        self._tap_a3_entry(self.screen_provider())
        screen, marker = self._wait_first(
            self.config.a3_tab_closed + self.config.a3_tab_open, attempts=12,
        )
        if marker is None:
            raise RuntimeError("Trường thành A3: không mở được Chúa Công")
        screen = self._open_a3_chien_ky(screen)
        self._a3_raise_flag(screen)
        self.input.tap(*self.config.a3_close_point)
        self.sleep(self.config.wait_seconds)

    def _read_roi_number(self, screen, roi) -> int | None:
        from rapidocr_onnxruntime import RapidOCR
        x1, y1, x2, y2 = roi
        result, _ = RapidOCR()(self._screen_array(screen)[y1:y2, x1:x2])
        texts = [row[1] for row in (result or [])]
        value = _last_ocr_number(texts)
        logging.getLogger("dc3q").info(
            "TT | OCR số trong ROI=%s | text=%s | số=%s", roi, texts, value,
        )
        return value

    def _run_a4(self) -> None:
        """Run the single free Thiên Cơ Các draw, then unwind to HOME."""
        logger = logging.getLogger("dc3q")
        self._open_home_entry()
        screen = self.screen_provider()
        hub_entry = self._first(screen, self.config.a4_hub_entry)
        if hub_entry is None:
            logger.info("TT | A4 NOT_AVAILABLE: thiếu Vệ Tướng")
            return
        self._tap(hub_entry)
        screen, entry = self._wait_first(self.config.a4_entry, attempts=12)
        if entry is None:
            raise RuntimeError("Trường thành A4: vào Vệ Tướng nhưng thiếu Thiên Cơ Các")
        self._tap(entry)
        screen, state = self._wait_first(
            [*self.config.a4_free, *self.config.a4_paid], attempts=12,
        )
        if state is None:
            raise RuntimeError("Trường thành A4: mở Thiên Cơ Các nhưng thiếu trạng thái")
        free = self._first(screen, self.config.a4_free, 0.95)
        if free is not None:
            self._tap(free)
            logger.info("TT | A4 bấm Diễn quẻ 1 lần miễn phí")
            screen, result = self._wait_first(
                [*self.config.a4_bonus_continue, *self.config.a4_reward], attempts=12,
            )
            if result is None:
                raise RuntimeError("Trường thành A4: FREE thiếu popup kết quả")
            if self._first(screen, self.config.a4_bonus_continue) is not None:
                self.input.tap(480, 360)
                self.sleep(self.config.wait_seconds)
                logger.info("TT | A4 ấn màn hình để tiếp tục")
                screen, result = self._wait_first(self.config.a4_return, attempts=12)
                if result is None:
                    raise RuntimeError("Trường thành A4: đóng thưởng nhưng thiếu Trở về")
            back = self._first(screen, self.config.a4_return)
            if back is None:
                raise RuntimeError("Trường thành A4: thiếu nút Trở về")
            self._tap(back)
            logger.info("TT | A4 bấm Trở về")
            screen, paid = self._wait_first(self.config.a4_paid, attempts=12)
            if paid is None:
                raise RuntimeError("Trường thành A4: chưa chứng minh trạng thái 1 khóa")
        elif self._first(screen, self.config.a4_paid) is None:
            raise RuntimeError("Trường thành A4: trạng thái FREE/1 khóa không rõ")
        logger.info("TT | A4 đã xong: Diễn quẻ 1 lần chuyển thành 1 khóa")
        self.input.tap(*self.config.a4_close_point)
        self.sleep(self.config.wait_seconds)
        screen, recall = self._wait_first(self.config.a4_recall, attempts=12)
        if recall is None:
            raise RuntimeError("Trường thành A4: đóng Thiên Cơ Các nhưng thiếu Hồi thành")
        self._tap(recall)
        logger.info("TT | A4 bấm Hồi thành")
        _, home = self._wait_first(self.config.home_markers, attempts=12)
        if home is None:
            raise RuntimeError("Trường thành A4: Hồi thành nhưng chưa về HOME")

    def _a5_fast_claim(self, screen) -> None:
        logger = logging.getLogger("dc3q")
        branches = (
            ("Ngựa thường", self.config.a5_normal_free, self.config.a5_normal_select,
             self.config.a5_normal_quantity_roi, self.config.a5_normal_free_roi),
            ("Ngựa vàng", self.config.a5_gold_free, None,
             self.config.a5_gold_quantity_roi, self.config.a5_gold_free_roi),
        )
        for name, free_templates, minus_template, quantity_roi, free_roi in branches:
            free_control = self._first(screen, free_templates, 0.95)
            if free_control is None:
                logger.info("TT | A5 %s không có control lượt miễn phí", name)
                continue
            free_count = self._read_roi_number(screen, free_roi)
            quantity = self._read_roi_number(screen, quantity_roi)
            if free_count is None or free_count <= 0:
                logger.info("TT | A5 %s hết/không chứng minh được lượt miễn phí", name)
                continue
            if quantity is None or quantity < free_count:
                raise RuntimeError(f"Trường thành A5: {name} số dây nhỏ hơn lượt miễn")
            for _ in range(self.config.a5_max_adjustments):
                if quantity <= free_count:
                    break
                # Dấu trừ nằm 87px trái tâm bộ đếm trong popup 960x540 đã xác minh live.
                x1, y1, x2, y2 = quantity_roi
                self.input.tap((x1 + x2) // 2 - 87, (y1 + y2) // 2)
                self.sleep(self.config.wait_seconds)
                screen = self.screen_provider()
                quantity = self._read_roi_number(screen, quantity_roi)
                if quantity is None:
                    raise RuntimeError(f"Trường thành A5: {name} không đọc được số dây sau giảm")
            if quantity != free_count:
                raise RuntimeError(f"Trường thành A5: {name} không cân bằng dây/lượt miễn")
            # Ngựa thường cần chọn thẻ trước; Ngựa vàng không có asset selected riêng.
            if name == "Ngựa thường":
                select = self._match(screen, self.config.a5_normal_select)
                if select.found:
                    self._tap(select)
                    screen = self.screen_provider()
                    free_control = self._first(screen, free_templates, 0.95)
            if free_control is None:
                raise RuntimeError(f"Trường thành A5: {name} mất nút quay miễn phí")
            self._tap(free_control)
            self.input.tap(*self.config.a5_reward_dismiss_point)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
            after = self._read_roi_number(screen, free_roi)
            if after is None or after != 0:
                raise RuntimeError(f"Trường thành A5: {name} chưa dùng hết lượt miễn phí")
            logger.info("TT | A5 %s dùng hết %d lượt miễn phí", name, free_count)

    def _a5_free_count(self, screen) -> int | None:
        import re
        import unicodedata
        text = unicodedata.normalize("NFKD", self._a5_text(screen)).encode("ascii", "ignore").decode().lower()
        match = re.search(r"lu.?t\s*mien\D*(\d+)", text)
        return int(match.group(1)) if match else None

    def _a7_has_free_label(self, screen) -> bool:
        import unicodedata
        from rapidocr_onnxruntime import RapidOCR
        x1, y1, x2, y2 = self.config.a7_free_label_roi
        result, _ = RapidOCR()(self._screen_array(screen)[y1:y2, x1:x2])
        text = " ".join(str(row[1]) for row in (result or []))
        plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        logging.getLogger("dc3q").info("TT | A7 OCR nhãn FREE=%r", text)
        return "mien" in plain and "phi" in plain

    def _run_a5(self, flow: SubFlow) -> None:
        logger = logging.getLogger("dc3q")
        self._open_home_entry()
        screen = self.screen_provider()
        hub_entry = self._first(screen, flow.hub_entry or [])
        if hub_entry is None:
            logger.info("TT | A5 NOT_AVAILABLE")
            return
        self._tap(hub_entry)
        screen, entry = self._wait_first(flow.entry, attempts=12)
        if entry is None:
            raise RuntimeError("Trường thành A5: thiếu Tướng Mã Quán miễn phí")
        self._tap(entry)
        screen, close = self._wait_first([self.config.a5_initial_close], attempts=12)
        if close is None:
            raise RuntimeError("Trường thành A5: thiếu nút đóng Vạn Mã Bôn Đằng")
        self._tap(close)
        screen, quick = self._wait_first([self.config.a5_quick], attempts=12)
        if quick is None:
            raise RuntimeError("Trường thành A5: thiếu nút Bắt ngựa nhanh")
        self._tap(quick)
        screen, state = self._wait_first(
            [*self.config.a5_normal_free, *self.config.a5_gold_free], attempts=12,
            threshold=0.95,
        )
        if state is None:
            logger.info("TT | A5 không còn lượt miễn phí; không bấm")
            return
        self._a5_fast_claim(screen)

    def _flow_by_name(self, name: str) -> SubFlow:
        for flow in self.config.flows:
            if flow.name == name:
                return flow
        raise RuntimeError(f"Trường thành: thiếu cấu hình {name}")

    def _run_a6(self) -> None:
        """Thần Binh: tap only proven free states 3,2,1; stop on paid ticket state."""
        logger = logging.getLogger("dc3q")
        flow = self._flow_by_name("A6_than-binh")
        self._open_home_entry()
        screen = self.screen_provider()
        hub_entry = self._first(screen, flow.hub_entry or [])
        if hub_entry is None:
            logger.info("TT | A6 NOT_AVAILABLE")
            return
        self._tap(hub_entry)
        screen, state = self._wait_first([*flow.entry, *flow.free, *flow.spent, *flow.close], attempts=12)
        if state is None:
            raise RuntimeError("Trường thành A6: vào Thần Binh nhưng thiếu trạng thái")
        entry = self._first(screen, flow.entry)
        if entry is not None:
            self._tap(entry)
            screen, state = self._wait_first([*flow.free, *flow.spent, *flow.close], attempts=12)
            if state is None:
                raise RuntimeError("Trường thành A6: mở Tầm Binh Mịch Bảo nhưng thiếu trạng thái")
        free_states = flow.free[:3]
        if len(free_states) != 3:
            raise RuntimeError("Trường thành A6: cần đúng 3 trạng thái FREE")
        for index, template in zip((3, 2, 1), free_states):
            free = self._match(screen, template, flow.free_threshold)
            if not free.found:
                break
            self._tap(free)
            logger.info("TT | A6 bấm FREE trạng thái %d", index)
            screen, state = self._wait_first([*flow.free, *flow.spent, *flow.close], attempts=12)
            if state is None:
                raise RuntimeError("Trường thành A6: FREE thiếu hậu điều kiện")
        if self._first(screen, flow.spent) is None:
            screen, _ = self._wait_first([*flow.spent, *flow.close], attempts=6)
        if self._first(screen, flow.spent) is None:
            logger.info("TT | A6 dừng fail-closed: chưa chứng minh trạng thái 1 vé")
            return
        logger.info("TT | A6 dừng: lượt tiếp theo dùng 1 vé")
        if not self._finish_flow(flow, screen):
            raise RuntimeError("Trường thành A6: trạng thái 1 vé nhưng thiếu Trở về/đóng")

    def _run_a7(self) -> None:
        """Chiến Hồn: one free draw only; paid Rút 1 lần means done."""
        logger = logging.getLogger("dc3q")
        flow = self._flow_by_name("A7_chien-hon")
        self._open_home_entry()
        screen = self.screen_provider()
        hub_entry = self._first(screen, flow.hub_entry or [])
        if hub_entry is None:
            logger.info("TT | A7 NOT_AVAILABLE")
            return
        self._tap(hub_entry)
        screen, state = self._wait_first([*flow.entry, *flow.free, *flow.spent, *flow.close], attempts=12)
        if state is None:
            raise RuntimeError("Trường thành A7: vào Chiến Hồn nhưng thiếu trạng thái")
        entry = self._first(screen, flow.entry)
        if entry is not None:
            self._tap(entry)
            screen, state = self._wait_first([*flow.free, *flow.spent], attempts=12)
            if state is None:
                raise RuntimeError("Trường thành A7: mở Nhận Chiến Hồn nhưng thiếu trạng thái")
        free = self._first(screen, flow.free, flow.free_threshold)
        if free is not None and self._a7_has_free_label(screen):
            self._tap(free)
            logger.info("TT | A7 bấm Rút 1 lần miễn phí")
            screen, paid = self._wait_first(flow.spent, attempts=12)
            if paid is None:
                raise RuntimeError("Trường thành A7: FREE thiếu trạng thái trả thưởng/đã hết miễn phí")
        else:
            if self._first(screen, flow.spent) is None:
                logger.info("TT | A7 bỏ qua: không chứng minh được Rút 1 lần MIỄN PHÍ")
                return
            logger.info("TT | A7 đã xong: Rút 1 lần không miễn phí")
        if not self._finish_flow(flow, screen):
            raise RuntimeError("Trường thành A7: đã xong nhưng thiếu X/đóng")

    def _open_home_entry(self) -> None:
        screen = self.screen_provider()
        entry = self._first(screen, self.config.entry_templates)
        if entry is None and self.config.menu_templates:
            menu = self._first(screen, self.config.menu_templates)
            if menu is not None:
                self._tap(menu)
                _, entry = self._wait_first(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Trường thành: menu đã mở nhưng thiếu icon Trường thành")
        self._tap(entry)
        logging.getLogger("dc3q").info("TT | mở Trường thành")

    def _resolve_bonus_continue(self, flow: SubFlow, screen, matched) -> tuple[object, object]:
        if not flow.bonus_continue or self._first(screen, flow.bonus_continue) is None:
            return screen, matched
        self.input.tap(*flow.bonus_tap_point)
        self.sleep(self.config.wait_seconds)
        logging.getLogger("dc3q").info("TT | %s trúng Vệ Tướng nguyên con; bấm tiếp tục", flow.name)
        screen, matched = self._wait_first([*flow.spent, *flow.close], attempts=12)
        if matched is None:
            raise RuntimeError(f"Trường thành {flow.name}: tiếp tục thưởng đặc biệt thiếu hậu điều kiện")
        return screen, matched

    def _finish_flow(self, flow: SubFlow, screen) -> bool:
        # spent/result state must be visually proven before any close tap.
        if self._first(screen, flow.spent) is not None:
            _, close = self._wait_first(flow.close, threshold=flow.close_threshold)
            if close is None:
                raise RuntimeError(f"Trường thành {flow.name}: thấy kết quả nhưng thiếu nút đóng")
            self._tap(close)
            logging.getLogger("dc3q").info("TT | %s đóng kết quả", flow.name)
            return True
        close = self._first(screen, flow.close, flow.close_threshold)
        if close is not None:
            self._tap(close)
            logging.getLogger("dc3q").info("TT | %s đóng state đã xong/không miễn phí", flow.name)
            return True
        return False

    def _run_flow(self, flow: SubFlow) -> None:
        logger = logging.getLogger("dc3q")
        screen = self.screen_provider()
        if flow.hub_entry:
            hub_entry = self._first(screen, flow.hub_entry)
            if hub_entry is None:
                logger.info("TT | %s NOT_AVAILABLE", flow.name)
                return
            self._tap(hub_entry)
            screen, state = self._wait_first([*flow.entry, *flow.free, *flow.spent, *flow.close], attempts=12)
            if state is None:
                raise RuntimeError(f"Trường thành {flow.name}: mở khu nhưng thiếu trạng thái")
        entry = self._first(screen, flow.entry)
        if entry is not None:
            self._tap(entry)
            screen, _ = self._wait_first([*flow.free, *flow.spent, *flow.close])
        for _ in range(12):
            if flow.repeat_free:
                free = self._first(screen, flow.free, flow.free_threshold)
                if free is not None:
                    self._tap(free)
                    logger.info("TT | %s bấm lượt miễn phí", flow.name)
                    screen, spent = self._wait_first(flow.spent, attempts=12)
                    if spent is None:
                        raise RuntimeError(f"Trường thành {flow.name}: lượt miễn phí thiếu hậu điều kiện")
                    # Popup thưởng A6 tự chứa nút "Tiếp tục lượt miễn" kế tiếp.
                    # Vòng sau chỉ bấm khi marker miễn phí vẫn hiện rõ.
                    continue
            if self._first(screen, flow.spent) is not None:
                if self._finish_flow(flow, screen):
                    return
            free = self._first(screen, flow.free, flow.free_threshold)
            if free is not None:
                self._tap(free)
                logger.info("TT | %s bấm miễn phí", flow.name)
                screen, spent = self._wait_first([*flow.spent, *(flow.bonus_continue or [])])
                if spent is None:
                    raise RuntimeError(f"Trường thành {flow.name}: bấm miễn phí nhưng không thấy hậu điều kiện")
                screen, spent = self._resolve_bonus_continue(flow, screen, spent)
                # Luồng không lặp (A4/A7): một FREE duy nhất, xử lý thưởng rồi đóng.
                # Không quay lại dò FREE vì frame/animation cũ có thể còn khớp nút.
                if not flow.repeat_free:
                    if not self._finish_flow(flow, screen):
                        raise RuntimeError(f"Trường thành {flow.name}: đã dùng FREE nhưng thiếu Trở về/đóng")
                    return
                continue
            if self._finish_flow(flow, screen):
                return
            # No recognisable free/safe state. Skip, never guess-click.
            logger.info("TT | %s bỏ qua: không chứng minh được trạng thái miễn phí/an toàn", flow.name)
            return
        raise RuntimeError(f"Trường thành {flow.name}: vượt quá số bước cho phép")

    def run(self) -> bool:
        self.soft_errors = []
        try:
            self._run_a1()
        except Exception as exc:
            self.soft_errors.append(str(exc))
            logging.getLogger("dc3q").error("TT | A1 lỗi: %s", exc)
        if not self.recover_home():
            raise RuntimeError("Trường thành A1: không recover được HOME")
        skipped = set(getattr(self.config, "skipped_subflows", []))
        if "A2_tuong-an" not in skipped:
            try:
                self._run_a2()
            except Exception as exc:
                self.soft_errors.append(str(exc))
                logging.getLogger("dc3q").error("TT | A2 lỗi: %s", exc)
            if not self.recover_home():
                raise RuntimeError("Trường thành A2: không recover được HOME")
        if "A3_chua-cong" not in skipped:
            try:
                self._run_a3()
            except Exception as exc:
                self.soft_errors.append(str(exc))
                logging.getLogger("dc3q").error("TT | A3 lỗi: %s", exc)
            if not self.recover_home():
                raise RuntimeError("Trường thành A3: không recover được HOME")
        for flow in self.config.flows:
            if flow.name in skipped:
                logging.getLogger("dc3q").info("TT | %s tạm tắt", flow.name)
                continue
            try:
                self._open_home_entry()
                if flow.name == "A5_trai-ngua":
                    self._run_a5(flow)
                elif flow.name == "A6_than-binh":
                    self._run_a6()
                elif flow.name == "A7_chien-hon":
                    self._run_a7()
                else:
                    self._run_flow(flow)
            except Exception as exc:
                self.soft_errors.append(str(exc))
                logging.getLogger("dc3q").error(
                    "TT | %s lỗi; recover HOME rồi tiếp tục: %s", flow.name, exc,
                )
            if not self.recover_home():
                raise RuntimeError(f"Trường thành {flow.name}: không recover được HOME")
        return True


class TruongThanhRuntimeStep:
    """Expose one Trường Thành child as one resumable runtime task."""

    def __init__(self, runner: TruongThanhRunner, runtime_task: str, method: str):
        self.runner = runner
        self.runtime_task = runtime_task
        self.method = method
        self.soft_errors: list[str] = []

    def run(self) -> bool:
        self.soft_errors = []
        getattr(self.runner, self.method)()
        if not self.runner.recover_home():
            raise RuntimeError(f"{self.runtime_task}: không recover được HOME")
        return True

    def recover_home(self) -> bool:
        return self.runner.recover_home()
