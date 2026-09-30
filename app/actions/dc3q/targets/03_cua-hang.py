from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


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
    sidebar_swipes: int = 3
    slider_start_ratio: float = 0.18
    slider_end_ratio: float = 0.80
    threshold: float = 0.65
    state_threshold: float = 0.76
    max_steps: int = 30
    wait_seconds: float = 0.8


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

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "cua_hang", template,
            self.config.threshold if threshold is None else threshold,
        ).match

    def _first(self, screen, templates: list[Path]):
        for template in templates:
            match = self._match(screen, template)
            if match.found:
                return match
        return None

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

    def _open_limited_store(self, screen):
        opened = self._best(screen, self.config.limited_open)
        closed = self._best(screen, self.config.limited_tabs)
        gift_open = self._best(screen, self.config.gift_tab_open)
        if (opened and opened.confidence >= self.config.threshold
                and opened.confidence >= closed.confidence + 0.05
                and opened.confidence >= gift_open.confidence + 0.05):
            return screen
        if closed is None or closed.confidence < self.config.threshold:
            raise RuntimeError("Cửa hàng: không nhận diện được tab Cửa hàng thời hạn")
        self._tap(closed)
        for _ in range(8):
            screen = self.screen_provider()
            opened = self._best(screen, self.config.limited_open)
            closed = self._best(screen, self.config.limited_tabs)
            gift_open = self._best(screen, self.config.gift_tab_open)
            gift_closed = self._first(screen, self.config.gift_tab_closed)
            if (opened and opened.confidence >= self.config.threshold
                    and opened.confidence >= closed.confidence + 0.05
                    and opened.confidence >= gift_open.confidence + 0.05
                    and gift_closed is not None):
                return screen
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Cửa hàng: bấm Cửa hàng thời hạn nhưng chưa thấy tab mở và Cửa hàng gợi ý đóng")

    def _limited_offer_state(self, screen):
        """Classify only the first free-gift card; ignore paid cards to its right."""
        free = self._match(screen, self.config.limited_unclaimed, 0.0)
        claimed = self._match(screen, self.config.limited_claimed, 0.0)
        # ponytail: fixed 960px viewport; move this bound to config if viewport support expands.
        first_card_right = 360
        candidates = [
            ("free", free),
            ("claimed", claimed),
        ]
        candidates = [
            (state, match) for state, match in candidates
            if match.confidence >= self.config.state_threshold
            and match.x + match.width // 2 <= first_card_right
        ]
        return max(candidates, key=lambda item: item[1].confidence, default=("unknown", None))

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
                for _ in range(8):
                    screen = self.screen_provider()
                    opened = self._best(screen, open_templates)
                    closed = self._best(screen, closed_templates)
                    if opened.confidence > closed.confidence:
                        break
                    self.sleep(self.config.wait_seconds)
                else:
                    raise RuntimeError(f"Cửa hàng thời hạn: tab {name} chưa mở")
            elif not opened or opened.confidence < self.config.threshold:
                raise RuntimeError(f"Cửa hàng thời hạn: không thấy tab {name}")

            # The tab can be selected while its catalog still says "Đang tải số liệu...".
            for _ in range(12):
                offer_state, offer = self._limited_offer_state(screen)
                if offer_state != "unknown":
                    break
                self.sleep(self.config.wait_seconds)
                screen = self.screen_provider()
            else:
                raise RuntimeError(f"Cửa hàng thời hạn: tab {name} tải quá lâu, chưa thấy Miễn phí hoặc Đã mua")
            if offer_state == "free":
                self._tap(offer)
                logger.info("CH | nhận gói miễn phí Cửa hàng thời hạn %s", name)
                # One claim tap only; wait through stale FREE/loading/reward frames.
                for _ in range(12):
                    screen = self.screen_provider()
                    settled_state, _ = self._limited_offer_state(screen)
                    if settled_state == "claimed":
                        break
                    if self._dismiss_reward(
                        screen, self.config.limited_reward_marker, self.config.limited_reward_dismiss
                    ):
                        continue
                    self.sleep(self.config.wait_seconds)
                else:
                    raise RuntimeError(f"Cửa hàng thời hạn: đã bấm tab {name} nhưng chưa thấy Đã mua")
            elif offer_state == "claimed":
                logger.info("CH | Cửa hàng thời hạn %s đã nhận", name)
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
            item_match = self._match(screen, item, self.config.state_threshold)
            price_match = self._match(screen, price, self.config.state_threshold)
            bought_match = self._match(screen, bought, self.config.state_threshold)
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

    def _find_mystic_product_state(self, screen, item: Path, price: Path, bought: Path):
        """Mystic item starts below the fold: swipe first, then require item+state."""
        for _ in range(4):
            self.input.swipe(650, 455, 650, 215, 450)
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
            item_match = self._match(screen, item, self.config.state_threshold)
            price_match = self._match(screen, price, self.config.state_threshold)
            bought_match = self._match(screen, bought, self.config.state_threshold)
            if item_match.found and price_match.found:
                return screen, "available"
            if item_match.found and bought_match.found:
                return screen, "bought"
        return screen, "unknown"

    def _run_mystic(self, screen) -> None:
        logger = logging.getLogger("dc3q")
        screen = self._open_sidebar_tab(
            screen, self.config.mystic_tab_closed, self.config.mystic_tab_open, "Tiệm thần bí"
        )
        screen = self.screen_provider()
        screen, product_state = self._find_mystic_product_state(
            screen, self.config.mystic_item, self.config.mystic_price,
            self.config.mystic_bought,
        )
        if product_state == "bought":
            logger.info("CH | Tiệm thần bí: 3 Chiêu Hiền Lệnh đã mua")
            return
        if product_state != "available":
            raise RuntimeError("Tiệm thần bí: đã vuốt lưới nhưng không thấy đủ 3 Chiêu Hiền Lệnh và giá 180")
        price = self._match(screen, self.config.mystic_price, self.config.state_threshold)
        self._tap(price)
        screen, buy = self._wait_for([self.config.mystic_buy])
        if buy is None:
            raise RuntimeError("Tiệm thần bí: bấm giá 180 nhưng popup Mua chưa mở")
        self._tap(buy)
        # One buy tap only; wait through loading or a delayed reward overlay.
        for _ in range(12):
            screen = self.screen_provider()
            item = self._match(screen, self.config.mystic_item, self.config.state_threshold)
            bought = self._match(screen, self.config.mystic_bought, self.config.state_threshold)
            if item.found and bought.found:
                logger.info("CH | mua 3 Chiêu Hiền Lệnh giá 180 Chiến hồn")
                return
            if self._dismiss_reward(screen, self.config.mystic_reward, self.config.mystic_dismiss):
                continue
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Tiệm thần bí: giao dịch xong nhưng chưa thấy trạng thái Đã mua")

    def _open_optional_prestige(self, screen):
        """Reveal Shop Danh Vọng with one long sidebar swipe; skip if absent."""
        logger = logging.getLogger("dc3q")
        self.input.swipe(105, 470, 105, 120, 700)
        self.sleep(self.config.wait_seconds)
        screen = self.screen_provider()
        opened = self._best(screen, self.config.prestige_tab_open)
        closed = self._best(screen, self.config.prestige_tab_closed)
        if opened and opened.confidence >= self.config.threshold and opened.confidence > closed.confidence:
            return screen, True
        if closed and closed.confidence >= self.config.threshold:
            self._tap(closed)
            for _ in range(8):
                screen = self.screen_provider()
                opened = self._best(screen, self.config.prestige_tab_open)
                closed = self._best(screen, self.config.prestige_tab_closed)
                if opened.confidence >= self.config.threshold and opened.confidence > closed.confidence:
                    return screen, True
                self.sleep(self.config.wait_seconds)
            raise RuntimeError("Cửa hàng: thấy Shop Danh Vọng nhưng bấm xong tab chưa mở")
        logger.info("CH | bỏ qua Shop Danh Vọng: không thấy sau một lần vuốt dài")
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
        price = self._match(screen, self.config.prestige_unit_price, self.config.state_threshold)
        self._tap(price)
        screen, popup = self._wait_for([self.config.prestige_popup])
        if popup is None:
            raise RuntimeError("Shop Danh Vọng: popup Mua chưa mở")
        screen = self.screen_provider()
        slider = self._first(screen, self.config.prestige_slider_states)
        if slider is None:
            raise RuntimeError("Shop Danh Vọng: không nhận diện được thanh số lượng")
        y = slider.y + slider.height // 2
        x1 = slider.x + int(slider.width * self.config.slider_start_ratio)
        x2 = slider.x + int(slider.width * self.config.slider_end_ratio)
        self.input.swipe(x1, y, x2, y, 500)
        self.sleep(self.config.wait_seconds)
        screen, maximum = self._wait_for([self.config.prestige_slider_max])
        if maximum is None:
            raise RuntimeError("Shop Danh Vọng: kéo nhưng chưa xác minh mức tối đa 5/5")
        screen = self.screen_provider()
        total = self._match(screen, self.config.prestige_total_price, self.config.state_threshold)
        if not total.found:
            raise RuntimeError("Shop Danh Vọng: thiếu CTA tổng giá chính xác 2500")
        self._tap(total)
        for _ in range(12):
            screen = self.screen_provider()
            bought = self._match(screen, self.config.prestige_bought, self.config.state_threshold)
            item = self._match(screen, self.config.prestige_item, self.config.state_threshold)
            if bought.found and item.found:
                logger.info("CH | mua 5 lượt x5 Quẻ lành tổng 2500 Danh Vọng")
                return
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Shop Danh Vọng: mua xong nhưng chưa thấy Quẻ lành ở trạng thái Đã mua")

    def _claim_daily_gift(self, screen):
        logger = logging.getLogger("dc3q")
        clicked = False
        # Panel/tab can match before the gift card finishes rendering.
        for _ in range(12):
            claimed = self._match(screen, self.config.daily_claimed, self.config.state_threshold)
            if claimed.found:
                logger.info("CH | Quà hằng ngày đã mua")
                return screen, True
            unclaimed = self._match(screen, self.config.daily_unclaimed, self.config.state_threshold)
            if unclaimed.found and not clicked:
                self._tap(unclaimed)
                clicked = True
                logger.info("CH | nhận Quà hằng ngày miễn phí")
            elif self._reward(screen):
                pass
            screen = self.screen_provider()
            self.sleep(self.config.wait_seconds)
        if clicked:
            raise RuntimeError("Cửa hàng: đã bấm Quà hằng ngày nhưng chưa thấy Đã mua")
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
        screen = self.screen_provider()
        entry = self._first(screen, self.config.entry_templates)
        if entry is None:
            menu = self._first(screen, self.config.menu_templates)
            if menu is None:
                raise RuntimeError("Cửa hàng: không tìm thấy icon tại HOME")
            self._tap(menu)
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
        screen = self.screen_provider()
        self._run_mystic(screen)
        screen = self.screen_provider()
        self._run_prestige(screen)
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
