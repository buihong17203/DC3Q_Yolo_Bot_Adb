from __future__ import annotations

from dataclasses import dataclass
import cv2
import logging
import numpy as np
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable

from app.vision.template import MatchResult


@dataclass(frozen=True)
class CuaHangConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    panel_markers: list[Path]
    close_template: Path
    home_markers: list[Path]
    gift_tab_closed: list[Path]
    gift_tab_open: list[Path]
    daily_unclaimed: Path
    daily_claimed: Path
    reward_marker: Path
    reward_dismiss: Path
    limited_tabs: list[Path]
    limited_open: list[Path]
    limited_tabs_closed: list[list[Path]]
    limited_tabs_open: list[list[Path]]
    limited_unclaimed: Path
    limited_claimed: Path
    limited_reward_marker: Path
    limited_reward_dismiss: Path
    mystic_tab_closed: list[Path]
    mystic_tab_open: list[Path]
    mystic_item: Path
    mystic_price: Path
    mystic_buy: Path
    mystic_confirm: Path
    mystic_bought: Path
    mystic_reward: Path
    mystic_dismiss: Path
    prestige_tab_closed: list[Path]
    prestige_tab_open: list[Path]
    prestige_item: Path
    prestige_unit_price: Path
    prestige_popup: Path
    prestige_slider_states: list[Path]
    prestige_slider_max: Path
    prestige_total_price: Path
    prestige_bought: Path
    sidebar_swipes: int = 10
    slider_start_ratio: float = 0.18
    slider_end_ratio: float = 0.80
    threshold: float = 0.65
    state_threshold: float = 0.76
    paid_threshold: float = 0.90
    max_steps: int = 30
    wait_seconds: float = 0.8
    limited_wait_seconds: float = 2.5


class CuaHangRunner:
    """HOME -> Cửa hàng -> các giao dịch được allowlist -> HOME."""
    runtime_task = "CUA_HANG"

    def __init__(self, screen_provider, adb_input, vision, config: CuaHangConfig,
                 sleep: Callable[[float], None] = default_sleep):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep
        self.soft_errors: list[str] = []

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "cua_hang", template,
            self.config.threshold if threshold is None else threshold,
        ).match

    def _match_popup(self, screen, template: Path, threshold: float | None = None):
        """Match only inside the centered purchase popup, never the product grid."""
        pixels = np.asarray(screen.data if hasattr(screen, "data") else screen)
        x1, y1, x2, y2 = 250, 100, 710, 470
        match = self.vision.find_template(
            pixels[y1:y2, x1:x2], "cua_hang_popup", template,
            self.config.threshold if threshold is None else threshold,
        ).match
        return MatchResult(
            match.found, match.confidence, match.x + x1, match.y + y1,
            match.width, match.height,
        )

    def _match_below_card(self, screen, card, template: Path):
        """Match a CTA only in the strip directly below its proven product card."""
        pixels = np.asarray(screen.data if hasattr(screen, "data") else screen)
        x1 = max(0, card.x - 5)
        y1 = max(0, card.y + card.height - 10)
        x2 = min(pixels.shape[1], card.x + card.width + 5)
        y2 = min(pixels.shape[0], y1 + 90)
        match = self.vision.find_template(
            pixels[y1:y2, x1:x2], "cua_hang_card_cta", template,
            self.config.paid_threshold,
        ).match
        return MatchResult(
            match.found, match.confidence, match.x + x1, match.y + y1,
            match.width, match.height,
        )

    def _match_roi(self, screen, template: Path, roi: tuple[int, int, int, int]):
        """Match one state inside its exact product CTA area."""
        pixels = np.asarray(screen.data if hasattr(screen, "data") else screen)
        x1, y1, x2, y2 = roi
        match = self.vision.find_template(
            pixels[y1:y2, x1:x2], "cua_hang_state", template, 0.0,
        ).match
        return MatchResult(
            match.found, match.confidence, match.x + x1, match.y + y1,
            match.width, match.height,
        )

    def _competing_state(self, screen, available: Path, bought: Path,
                         roi: tuple[int, int, int, int]):
        """Accept only the stronger CTA state; shared button chrome may match both."""
        free = self._match_roi(screen, available, roi)
        claimed = self._match_roi(screen, bought, roi)
        margin = 0.08
        logger = logging.getLogger("dc3q")
        if (free.confidence >= self.config.state_threshold
                and free.confidence >= claimed.confidence + margin):
            logger.info(
                "DECISION | Miễn phí=%.3f vs Đã mua=%.3f | chọn=MIỄN PHÍ | hành_động=LẤY",
                free.confidence, claimed.confidence,
            )
            return "free", free
        if (claimed.confidence >= self.config.state_threshold
                and claimed.confidence >= free.confidence + margin):
            logger.info(
                "DECISION | Miễn phí=%.3f vs Đã mua=%.3f | chọn=ĐÃ MUA | hành_động=KHÔNG LẤY",
                free.confidence, claimed.confidence,
            )
            return "claimed", claimed
        logger.info(
            "DECISION | Miễn phí=%.3f vs Đã mua=%.3f | chọn=KHÔNG RÕ | hành_động=DỪNG/CHỜ",
            free.confidence, claimed.confidence,
        )
        return "unknown", None

    def _first(self, screen, templates: list[Path]):
        for template in templates:
            match = self._match(screen, template)
            if match.found:
                return match
        return None

    def _first_paid(self, screen, templates: list[Path]):
        for template in templates:
            match = self._match(screen, template, self.config.paid_threshold)
            if match.found:
                return match
        return None

    def _wait_for_paid(self, templates: list[Path], attempts: int = 8):
        last = None
        for _ in range(attempts):
            last = self.screen_provider()
            match = self._first_paid(last, templates)
            if match is not None:
                return last, match
            self.sleep(self.config.wait_seconds)
        return last, None

    def _best(self, screen, templates: list[Path]):
        matches = [self._match(screen, template, 0.0) for template in templates]
        return max(matches, key=lambda match: match.confidence, default=None)

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

    def _dismiss_reward(self, screen, marker: Path, dismiss_template: Path) -> bool:
        if not self._match(screen, marker).found:
            return False
        dismiss = self._match(screen, dismiss_template)
        if not dismiss.found:
            raise RuntimeError("Cửa hàng: thấy thưởng nhưng thiếu vùng đóng an toàn")
        self._tap(dismiss)
        return True

    def _reward(self, screen) -> bool:
        return self._dismiss_reward(screen, self.config.reward_marker, self.config.reward_dismiss)

    def _limited_store_ready(self, screen) -> bool:
        opened = self._best(screen, self.config.limited_open)
        closed = self._best(screen, self.config.limited_tabs)
        gift_open = self._best(screen, self.config.gift_tab_open)
        gift_closed = self._best(screen, self.config.gift_tab_closed)
        if (opened and opened.confidence >= self.config.threshold
                and opened.confidence >= closed.confidence + 0.05
                and opened.confidence >= gift_open.confidence + 0.05):
            return True
        # Period templates can collide with offer art on Cửa hàng gợi ý. Trust
        # them only after the top-level Cửa hàng gợi ý tab is proven closed.
        if (gift_closed.confidence < self.config.threshold
                or gift_closed.confidence <= gift_open.confidence):
            return False
        for closed_states, open_states in zip(
                self.config.limited_tabs_closed, self.config.limited_tabs_open):
            period_closed = self._best(screen, closed_states)
            period_open = self._best(screen, open_states)
            if max(period_closed.confidence, period_open.confidence) >= self.config.threshold:
                return True
        return False

    def _open_limited_store(self, screen):
        if self._limited_store_ready(screen):
            return screen
        closed = self._best(screen, self.config.limited_tabs)
        if closed is None or closed.confidence < self.config.threshold:
            raise RuntimeError("Cửa hàng: không nhận diện được tab Cửa hàng thời hạn")
        self._tap(closed)
        for _ in range(16):
            screen = self.screen_provider()
            if self._limited_store_ready(screen):
                return screen
            self.sleep(self.config.limited_wait_seconds)
        raise RuntimeError("Cửa hàng: bấm Cửa hàng thời hạn nhưng chưa thấy tab mở và Cửa hàng gợi ý đóng")

    def _limited_offer_state(self, screen):
        # ponytail: ADB viewport 960x540; normalize this ROI if runtime resolution changes.
        return self._competing_state(
            screen, self.config.limited_unclaimed, self.config.limited_claimed,
            (160, 300, 330, 390),
        )

    def _run_limited_tabs(self, screen) -> None:
        logger = logging.getLogger("dc3q")
        names = ("Ngày", "Tuần", "Tháng")
        for name, closed_templates, open_templates in zip(
            names, self.config.limited_tabs_closed, self.config.limited_tabs_open
        ):
            opened = self._best(screen, open_templates)
            closed = self._best(screen, closed_templates)
            if closed and closed.confidence > opened.confidence:
                self._tap(closed)
                # Day/Week/Month catalogs load slowly after the selected tab changes.
                self.sleep(self.config.limited_wait_seconds)
                for _ in range(12):
                    screen = self.screen_provider()
                    opened = self._best(screen, open_templates)
                    closed = self._best(screen, closed_templates)
                    if opened.confidence > closed.confidence:
                        break
                    self.sleep(self.config.limited_wait_seconds)
                else:
                    raise RuntimeError(f"Cửa hàng thời hạn: tab {name} chưa mở")
            elif not opened or opened.confidence < self.config.threshold:
                raise RuntimeError(f"Cửa hàng thời hạn: không thấy tab {name}")

            # The tab can be selected while its catalog still says "Đang tải số liệu...".
            self.sleep(self.config.limited_wait_seconds)
            for _ in range(16):
                offer_state, offer = self._limited_offer_state(screen)
                if offer_state != "unknown":
                    break
                self.sleep(self.config.limited_wait_seconds)
                screen = self.screen_provider()
            else:
                raise RuntimeError(f"Cửa hàng thời hạn: tab {name} tải quá lâu, chưa thấy Miễn phí hoặc Đã mua")
            if offer_state == "free":
                self._tap(offer)
                logger.info("CH | nhận gói miễn phí Cửa hàng thời hạn %s", name)
                # Reward popup can arrive several frames after the button says "Đã mua".
                # Require three settled frames; dismiss any late popup before changing tabs.
                settled_frames = 0
                for _ in range(12):
                    screen = self.screen_provider()
                    if self._dismiss_reward(
                        screen, self.config.limited_reward_marker, self.config.limited_reward_dismiss
                    ):
                        settled_frames = 0
                        screen = self.screen_provider()
                    settled_state, _ = self._limited_offer_state(screen)
                    settled_frames = settled_frames + 1 if settled_state == "claimed" else 0
                    if settled_frames >= 3:
                        break
                    self.sleep(self.config.wait_seconds)
                else:
                    raise RuntimeError(f"Cửa hàng thời hạn: đã bấm tab {name} nhưng chưa thấy Đã mua ổn định")
            elif offer_state == "claimed":
                pass
            screen = self.screen_provider()

    def _open_sidebar_tab(self, screen, closed: list[Path], opened: list[Path], name: str):
        for attempt in range(self.config.sidebar_swipes + 1):
            open_match = self._best(screen, opened)
            closed_match = self._best(screen, closed)
            if (open_match and open_match.confidence >= self.config.threshold
                    and open_match.confidence > closed_match.confidence):
                return screen
            if closed_match and closed_match.confidence >= self.config.threshold:
                self._tap(closed_match)
                for _ in range(8):
                    screen = self.screen_provider()
                    open_match = self._best(screen, opened)
                    closed_match = self._best(screen, closed)
                    if (open_match and open_match.confidence >= self.config.threshold
                            and open_match.confidence > closed_match.confidence):
                        return screen
                    self.sleep(self.config.wait_seconds)
                raise RuntimeError(f"Cửa hàng: bấm {name} nhưng tab chưa mở")
            if attempt == self.config.sidebar_swipes:
                break
            self.input.swipe(105, 470, 105, 180, 450)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
        raise RuntimeError(f"Cửa hàng: không tìm thấy tab {name} sau khi vuốt")

    def _find_product_state(self, screen, item: Path, price: Path, bought: Path,
                            require_item_for_bought: bool = True):
        """Scroll only the product grid; return available/bought after visual proof."""
        for attempt in range(5):
            item_match = self._match(screen, item, self.config.paid_threshold)
            price_match = (self._match_below_card(screen, item_match, price)
                           if item_match.found else MatchResult(False, 0.0))
            bought_match = (self._match_below_card(screen, item_match, bought)
                            if item_match.found else MatchResult(False, 0.0))
            if item_match.found and price_match.found:
                return screen, "available"
            if bought_match.found and (item_match.found or not require_item_for_bought):
                return screen, "bought"
            if attempt == 4:
                break
            # Product grid only; never swipe the left shop sidebar here.
            self.input.swipe(650, 455, 650, 215, 450)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
        return screen, "unknown"

    def _find_mystic_product_state(self, screen, available: Path, _price: Path, bought: Path):
        """Match only exact full-card states: item+limit+CTA are one template."""
        for _ in range(8):
            self.input.swipe(650, 430, 650, 310, 700)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
            available_card = self._match(screen, available, self.config.paid_threshold)
            bought_card = self._match(screen, bought, self.config.paid_threshold)
            if available_card.found and available_card.confidence > bought_card.confidence:
                return screen, "available", available_card
            if bought_card.found and bought_card.confidence > available_card.confidence:
                return screen, "bought", bought_card
        return screen, "unknown", MatchResult(False, 0.0)

    def _tap_card_cta(self, card) -> None:
        """Tap the bottom CTA band of a positively matched full product card."""
        self.input.tap(card.x + card.width // 2, card.y + int(card.height * 0.95))
        self.sleep(self.config.wait_seconds)

    def _drag_prestige_slider_to_max(self, slider, knob_ratio: float) -> None:
        """Start exactly on the round knob, then drag it to the track end."""
        y = slider.y + slider.height // 2
        x1 = slider.x + int(slider.width * knob_ratio)
        x2 = slider.x + int(slider.width * self.config.slider_end_ratio)
        self.input.swipe(x1, y, x2, y, 700)
        self.sleep(self.config.wait_seconds)

    def _maximize_prestige_quantity(self, slider, knob_ratio: float):
        """Drag first; if not full, press + until the full-bar state appears."""
        self._drag_prestige_slider_to_max(slider, knob_ratio)
        screen, maximum = self._wait_for_paid([self.config.prestige_slider_max])
        if maximum is not None:
            return screen, maximum
        plus_x = slider.x + int(slider.width * 0.92)
        plus_y = slider.y + slider.height // 2
        for _ in range(10):
            self.input.tap(plus_x, plus_y)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
            if not self._match_popup(
                    screen, self.config.prestige_popup,
                    self.config.paid_threshold).found:
                raise RuntimeError("Shop Danh Vọng: popup Mua biến mất khi tăng số lượng")
            maximum = self._match(
                screen, self.config.prestige_slider_max,
                self.config.paid_threshold,
            )
            if maximum.found:
                return screen, maximum
        return screen, None

    def _run_mystic(self, screen) -> None:
        logger = logging.getLogger("dc3q")
        screen = self._open_sidebar_tab(
            screen, self.config.mystic_tab_closed, self.config.mystic_tab_open, "Tiệm thần bí"
        )
        screen = self.screen_provider()
        screen, product_state, product_card = self._find_mystic_product_state(
            screen, self.config.mystic_item, self.config.mystic_price,
            self.config.mystic_bought,
        )
        if product_state == "bought":
            logger.info("CH | Tiệm thần bí: 3 Chiêu Hiền Lệnh đã mua")
            return
        if product_state != "available":
            raise RuntimeError("Tiệm thần bí: không thấy đúng nguyên thẻ 3 Chiêu Hiền Lệnh giá 180")
        self._tap_card_cta(product_card)
        screen, popup = self._wait_for_paid([self.config.mystic_buy])
        if popup is None:
            raise RuntimeError("Tiệm thần bí: bấm giá 180 nhưng popup Mua chưa mở")
        # Popup marker proves context only. Confirm by its explicit 180-price CTA.
        screen = self.screen_provider()
        confirm_price = self._match_popup(
            screen, self.config.mystic_confirm, self.config.paid_threshold,
        )
        if not confirm_price.found:
            raise RuntimeError("Tiệm thần bí: popup Mua thiếu nút xác nhận giá 180")
        # User-supplied confirm image includes context above the button.
        self.input.tap(confirm_price.x + confirm_price.width // 2,
                       confirm_price.y + int(confirm_price.height * 0.80))
        self.sleep(self.config.wait_seconds)
        # One confirmation tap only; wait through loading or delayed reward.
        for _ in range(12):
            screen = self.screen_provider()
            bought = self._match(screen, self.config.mystic_bought, self.config.paid_threshold)
            if bought.found:
                logger.info("CH | mua 3 Chiêu Hiền Lệnh giá 180 Tướng Hồn")
                return
            if self._dismiss_reward(screen, self.config.mystic_reward, self.config.mystic_dismiss):
                continue
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Tiệm thần bí: giao dịch xong nhưng chưa thấy trạng thái Đã mua")

    def _open_optional_prestige(self, screen):
        """Scroll only the sidebar to its bottom; tap only a strong Prestige match."""
        logger = logging.getLogger("dc3q")
        prestige_threshold = self.config.paid_threshold
        def sidebar_pixels(frame):
            pixels = np.asarray(frame.data if hasattr(frame, "data") else frame)
            return pixels[90:525, 10:145].copy()

        previous_sidebar = sidebar_pixels(screen)
        unchanged = 0
        for _ in range(self.config.sidebar_swipes):
            self.input.swipe(105, 470, 105, 120, 700)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
            opened = self._best(screen, self.config.prestige_tab_open)
            closed = self._best(screen, self.config.prestige_tab_closed)
            if (opened and opened.confidence >= prestige_threshold
                    and opened.confidence >= closed.confidence + 0.05):
                return screen, True
            if (closed and closed.confidence >= prestige_threshold
                    and closed.confidence >= opened.confidence + 0.05):
                self._tap(closed)
                for _ in range(8):
                    screen = self.screen_provider()
                    opened = self._best(screen, self.config.prestige_tab_open)
                    closed = self._best(screen, self.config.prestige_tab_closed)
                    if (opened.confidence >= prestige_threshold
                            and opened.confidence >= closed.confidence + 0.05):
                        return screen, True
                    self.sleep(self.config.wait_seconds)
                raise RuntimeError("Cửa hàng: thấy Shop Danh Vọng nhưng bấm xong tab chưa mở")
            sidebar = sidebar_pixels(screen)
            unchanged = unchanged + 1 if cv2.absdiff(sidebar, previous_sidebar).mean() < 0.5 else 0
            previous_sidebar = sidebar.copy()
            if unchanged >= 2:
                break
        logger.info("CH | bỏ qua Shop Danh Vọng: đã vuốt sidebar hết mức nhưng không thấy")
        return screen, False

    def _run_prestige(self, screen) -> bool:
        logger = logging.getLogger("dc3q")
        screen, found = self._open_optional_prestige(screen)
        if not found:
            return False
        screen = self.screen_provider()
        screen, product_state = self._find_product_state(
            screen, self.config.prestige_item, self.config.prestige_unit_price,
            self.config.prestige_bought, require_item_for_bought=True,
        )
        if product_state == "bought":
            logger.info("CH | Shop Danh Vọng: Quẻ lành đã mua đủ")
            return
        if product_state != "available":
            raise RuntimeError("Shop Danh Vọng: đã vuốt lưới nhưng không thấy đủ Quẻ lành x5 và giá 500")
        item = self._match(screen, self.config.prestige_item, self.config.state_threshold)
        price = self._match_below_card(screen, item, self.config.prestige_unit_price)
        if not price.found:
            raise RuntimeError("Shop Danh Vọng: giá 500 không nằm dưới đúng thẻ Quẻ lành x5")
        self._tap(price)
        screen, popup = self._wait_for_paid([self.config.prestige_popup])
        if popup is None:
            raise RuntimeError("Shop Danh Vọng: popup Mua chưa mở")
        screen = self.screen_provider()
        slider = None
        knob_ratio = None
        # Knob centers from supplied states 1/5, 2/5, 3/5.
        for template, ratio in zip(
                self.config.prestige_slider_states, (0.175, 0.367, 0.541)):
            candidate = self._match(screen, template)
            if candidate.found and (
                    slider is None or candidate.confidence > slider.confidence):
                slider, knob_ratio = candidate, ratio
        if slider is None:
            raise RuntimeError("Shop Danh Vọng: không nhận diện được thanh số lượng")
        screen, maximum = self._maximize_prestige_quantity(slider, knob_ratio)
        if maximum is None:
            raise RuntimeError("Shop Danh Vọng: kéo và bấm + nhưng chưa thấy thanh số lượng đầy")
        screen = self.screen_provider()
        total = self._match_popup(screen, self.config.prestige_total_price, self.config.paid_threshold)
        if not total.found:
            raise RuntimeError("Shop Danh Vọng: thiếu CTA tổng giá chính xác 2500")
        self._tap(total)
        for _ in range(12):
            screen = self.screen_provider()
            bought = self._match(screen, self.config.prestige_bought, self.config.paid_threshold)
            item = self._match(screen, self.config.prestige_item, self.config.paid_threshold)
            if bought.found and item.found:
                logger.info("CH | mua 5 lượt x5 Quẻ lành tổng 2500 Danh Vọng")
                return
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Shop Danh Vọng: mua xong nhưng chưa thấy Quẻ lành ở trạng thái Đã mua")

    def _claim_daily_gift(self, screen):
        logger = logging.getLogger("dc3q")
        clicked = False
        claimed_frames = 0
        # Panel/tab can match before the gift card finishes rendering. A reward
        # popup may also arrive after the card already changed to "Đã mua".
        for _ in range(16):
            state, control = self._competing_state(
                screen, self.config.daily_unclaimed, self.config.daily_claimed,
                (825, 90, 962, 190),
            )
            if state == "free" and not clicked:
                self._tap(control)
                clicked = True
                logger.info("CH | nhận Quà hằng ngày miễn phí")
                claimed_frames = 0
            elif self._reward(screen):
                logger.info("CH | đóng popup thưởng Quà hằng ngày")
                claimed_frames = 0
            elif state == "claimed":
                claimed_frames += 1
                if claimed_frames >= 3:
                    return screen, True
            else:
                claimed_frames = 0
            screen = self.screen_provider()
            self.sleep(self.config.wait_seconds)
        if clicked:
            raise RuntimeError("Cửa hàng: đã bấm Quà hằng ngày nhưng chưa thấy Đã mua ổn định sau popup")
        return screen, False

    def _open_gift_tab(self, screen):
        if self._first(screen, self.config.gift_tab_open) is not None:
            return screen
        tab = self._first(screen, self.config.gift_tab_closed)
        if tab is None:
            raise RuntimeError("Cửa hàng: không nhận diện được tab Cửa hàng gợi ý")
        self._tap(tab)
        screen, opened = self._wait_for(self.config.gift_tab_open)
        if opened is None:
            raise RuntimeError("Cửa hàng: bấm Cửa hàng gợi ý nhưng tab chưa mở")
        return screen

    def recover_home(self) -> bool:
        logger = logging.getLogger("dc3q")
        for _ in range(12):
            screen = self.screen_provider()
            if self._reward(screen):
                logger.info("CH | recovery đóng thưởng")
                continue
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                logger.info("CH | recovery đóng Cửa hàng")
                continue
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("CH | recovery đã về HOME")
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        self.soft_errors = []
        screen = self.screen_provider()
        entry = self._first(screen, self.config.entry_templates)
        if entry is None:
            closed = self._match(screen, self.config.menu_templates[0])
            opened = self._match(screen, self.config.menu_templates[1])
            if opened.found and opened.confidence >= closed.confidence:
                raise RuntimeError("Cửa hàng: menu đang mở nhưng thiếu icon Cửa hàng")
            if not closed.found or closed.confidence <= opened.confidence:
                raise RuntimeError("Cửa hàng: không xác định được trạng thái menu HOME")
            self._tap(closed)
            screen, entry = self._wait_for(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Cửa hàng: menu đã mở nhưng thiếu icon Cửa hàng")
        self._tap(entry)
        logger.info("CH | mở Cửa hàng")
        screen, panel = self._wait_for(self.config.panel_markers + self.config.gift_tab_open + self.config.gift_tab_closed)
        if panel is None:
            raise RuntimeError("Cửa hàng: bấm icon nhưng panel chưa mở sau khi chờ")
        screen = self._open_gift_tab(screen)
        screen, daily_done = self._claim_daily_gift(screen)
        if not daily_done:
            raise RuntimeError("Cửa hàng: không thấy Miễn phí hoặc Đã mua ở Quà hằng ngày")
        screen = self._open_limited_store(screen)
        self._run_limited_tabs(screen)
        paid_step = "Tiệm thần bí"
        try:
            screen = self.screen_provider()
            self._run_mystic(screen)
            paid_step = "Shop Danh Vọng"
            screen = self.screen_provider()
            self._run_prestige(screen)
        except RuntimeError as exc:
            self.soft_errors.append(f"{paid_step}: {exc}")
            logger.error("CH | bỏ phần mua trả phí sau một lỗi; tiếp tục nhiệm vụ khác: %s", exc)
            if not self.recover_home():
                raise RuntimeError("Cửa hàng: lỗi mua trả phí và không thể về HOME an toàn") from exc
            return True
        screen = self.screen_provider()
        close = self._match(screen, self.config.close_template)
        if not close.found:
            raise RuntimeError("Cửa hàng: hoàn tất nhưng thiếu nút đóng")
        self._tap(close)
        for _ in range(5):
            screen = self.screen_provider()
            if self._first(screen, self.config.home_markers) and self._first(screen, self.config.panel_markers) is None:
                return True
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Cửa hàng: đóng xong nhưng chưa về HOME")
