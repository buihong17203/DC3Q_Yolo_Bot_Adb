from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


@dataclass(frozen=True)
class HoatDongConfig:
    entry_templates: list[Path]
    menu_templates: list[Path]
    panel_markers: list[Path]
    close_template: Path
    home_markers: list[Path]
    welfare_tabs: list[Path]
    welfare_open: list[Path]
    national_tabs: list[Path]
    national_open: list[Path]
    national_free: Path
    national_claimed: Path
    online_tabs: list[Path]
    online_open: list[Path]
    online_claimable: Path
    online_unavailable: Path
    online_claimed: Path
    attendance_tabs: list[Path]
    attendance_open: list[Path]
    attendance_makeup: Path | None
    attendance_grid: tuple[int, int, int, int]
    attendance_milestone_claimable: Path
    attendance_milestone_locked: Path
    attendance_milestone_claimed: Path
    attendance_milestone_rois: list[tuple[int, int, int, int]]
    tax_tabs: list[Path]
    tax_open: list[Path]
    tax_unavailable: Path
    tax_claimable: Path
    tax_claimed: Path
    reward_marker: Path
    reward_dismiss: Path
    threshold: float = 0.65
    state_threshold: float = 0.76
    max_steps: int = 50
    wait_seconds: float = 0.8


class HoatDongRunner:
    """HOME -> Hoạt động/Phúc lợi -> safe claims -> HOME."""
    runtime_task = "HOAT_DONG"

    TAX_WINDOWS = ((12, 14), (18, 20), (21, 23))

    def __init__(self, screen_provider, adb_input, vision, config: HoatDongConfig,
                 sleep: Callable[[float], None] = default_sleep,
                 now: Callable[[], datetime] = datetime.now,
                 attendance_day: Callable[[], int | None] | None = None,
                 save_attendance_day: Callable[[int], None] | None = None):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep
        self.now = now
        self.attendance_day = attendance_day or (lambda: None)
        self.save_attendance_day = save_attendance_day or (lambda day: None)

    @staticmethod
    def next_attendance_index(states: list[str]) -> int | None:
        """Click the first unhandled day; ignore false late marks from reward art."""
        limit = min(30, len(states))
        for index in range(limit):
            if states[index] not in {"tick", "makeup"}:
                return index
        return None

    def _match(self, screen, template: Path, threshold: float | None = None):
        return self.vision.find_template(
            screen, "hoat_dong", template,
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

    def _tab_state(self, screen, closed: list[Path], opened: list[Path]):
        """Classify from competing visual states, never expected coordinates."""
        closed_match = self._best(screen, closed)
        open_match = self._best(screen, opened)
        closed_score = closed_match.confidence if closed_match else 0.0
        open_score = open_match.confidence if open_match else 0.0
        margin = 0.05
        if open_score >= self.config.threshold and open_score >= closed_score + margin:
            return "open", open_match, closed_match
        if closed_score >= self.config.threshold and closed_score >= open_score + margin:
            return "closed", open_match, closed_match
        return "unknown", open_match, closed_match

    def _tap(self, match) -> None:
        self.input.tap(match.x + match.width // 2, match.y + match.height // 2)
        self.sleep(self.config.wait_seconds)

    def _reward(self, screen) -> bool:
        reward = self._match(screen, self.config.reward_marker)
        if not reward.found:
            return False
        dismiss = self._match(screen, self.config.reward_dismiss)
        if not dismiss.found:
            raise RuntimeError("Hoạt động: thấy thưởng nhưng thiếu vùng đóng an toàn")
        self._tap(dismiss)
        return True

    def _settle_claim(self, settled: list[Path], attempts: int = 10):
        """Wait for delayed reward, dismiss it, then prove claimed state."""
        for _ in range(attempts):
            screen = self.screen_provider()
            if self._reward(screen):
                continue
            if self._first(screen, settled) is not None:
                return screen
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Hoạt động: nhận quà nhưng chưa thấy trạng thái đã nhận")

    def _all_matches(self, screen, template: Path, threshold: float = 0.95):
        """Return every distinct exact-looking control, not only the best one."""
        import cv2
        import numpy as np
        from app.vision.template import MatchResult

        data = screen.data if hasattr(screen, "data") else screen
        if hasattr(data, "convert") and not hasattr(data, "shape"):
            data = np.asarray(data.convert("RGB"))
        else:
            data = np.asarray(data)
        tpl = cv2.imread(str(template), cv2.IMREAD_COLOR)
        if tpl is None:
            raise FileNotFoundError(f"Không đọc được template: {template}")
        source = cv2.cvtColor(data, cv2.COLOR_RGB2GRAY) if data.ndim == 3 else data
        target = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(source, target, cv2.TM_CCOEFF_NORMED)
        mask = (result >= threshold).astype("uint8")
        count, labels, _, _ = cv2.connectedComponentsWithStats(mask)
        matches = []
        height, width = target.shape[:2]
        for label in range(1, count):
            ys, xs = np.where(labels == label)
            if not len(xs):
                continue
            best = int(np.argmax(result[ys, xs]))
            score = float(result[ys[best], xs[best]])
            matches.append(MatchResult(True, score, int(xs[best]), int(ys[best]), width, height))
        return sorted(matches, key=lambda item: (item.y, item.x))

    @staticmethod
    def _online_view_changed(before, after) -> bool:
        """Compare only the reward list, excluding sidebar and popup controls."""
        import cv2
        import numpy as np

        def array(frame):
            data = frame.data if hasattr(frame, "data") else frame
            if hasattr(data, "convert") and not hasattr(data, "shape"):
                data = np.asarray(data.convert("RGB"))
            return np.asarray(data)

        left = array(before)[180:515, 500:920]
        right = array(after)[180:515, 500:920]
        return left.shape == right.shape and float(cv2.absdiff(left, right).mean()) >= 1.5

    def _slow_online_scroll(self, screen, downward: bool):
        """Move the reward list slowly, then capture a fresh stable frame."""
        if downward:
            self.input.swipe(700, 440, 700, 260, 900)
        else:
            self.input.swipe(700, 260, 700, 440, 900)
        self.sleep(max(self.config.wait_seconds, 1.0))
        after = self.screen_provider()
        return after, self._online_view_changed(screen, after)

    def _online_counts(self, screen) -> tuple[int, int, int]:
        # 0.95 excludes the visually similar Chưa đạt button (observed false score 0.887).
        return (
            len(self._all_matches(screen, self.config.online_claimable, 0.95)),
            len(self._all_matches(screen, self.config.online_unavailable, 0.95)),
            len(self._all_matches(screen, self.config.online_claimed, 0.95)),
        )

    def _claim_online(self, screen) -> None:
        """Handle the fixed four milestones using at most two list views."""
        logger = logging.getLogger("dc3q")
        claims = 0
        for view in range(2):
            while True:
                claimable = self._all_matches(screen, self.config.online_claimable, 0.95)
                if not claimable:
                    break
                self._tap(claimable[0])
                claims += 1
                logger.info("HD | Quà online: bấm Nhận thứ %d/4", claims)
                for _ in range(10):
                    screen = self.screen_provider()
                    if self._reward(screen):
                        screen = self.screen_provider()
                        break
                    self.sleep(self.config.wait_seconds)
                else:
                    raise RuntimeError("Hoạt động: Quà online bấm Nhận nhưng chưa xuất hiện thưởng")
                if claims > 4:
                    raise RuntimeError("Hoạt động: Quà online vượt quá 4 mốc cố định")
            claimable, unavailable, claimed = self._online_counts(screen)
            logger.info(
                "HD | Quà online trang=%d/2 | Nhận=%d | Chưa đạt=%d | Đã nhận=%d",
                view + 1, claimable, unavailable, claimed,
            )
            if view == 0:
                self.input.swipe(700, 440, 700, 300, 900)
                self.sleep(max(self.config.wait_seconds, 1.0))
                screen = self.screen_provider()
        if self._all_matches(screen, self.config.online_claimable, 0.95):
            raise RuntimeError("Hoạt động: Quà online vẫn còn nút Nhận sau 4 mốc")
        logger.info("HD | Quà online hoàn tất 4 mốc | đã_bấm=%d", claims)

    def _open_attendance_tab(self, screen):
        """Attendance is visible below Quà online; tap it directly, never scroll sidebar."""
        tab = self._best(screen, self.config.attendance_tabs)
        if tab is None or tab.confidence < self.config.threshold:
            raise RuntimeError("Hoạt động: không nhận diện được nút Điểm danh")
        self._tap(tab)
        for _ in range(8):
            verify = self.screen_provider()
            if self._first(verify, self.config.attendance_open) is not None:
                return verify
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Hoạt động: bấm Điểm danh nhưng nội dung chưa mở")

    def _open_online_tab(self, screen):
        """Open Quà online using its control, then prove its content state."""
        tab = self._best(screen, self.config.online_tabs)
        if tab is None or tab.confidence < self.config.threshold:
            raise RuntimeError("Hoạt động: không nhận diện được nút Quà online")
        self._tap(tab)
        for _ in range(8):
            verify = self.screen_provider()
            states = (
                self.config.online_claimable,
                self.config.online_unavailable,
                self.config.online_claimed,
            )
            if any(self._match(verify, template, self.config.state_threshold).found for template in states):
                return verify
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Hoạt động: bấm Quà online nhưng nội dung chưa mở")

    def _wait_for(self, templates: list[Path], attempts: int = 8):
        """Poll transitions; Activity panel can render after the entry tap."""
        last_screen = None
        for _ in range(attempts):
            last_screen = self.screen_provider()
            match = self._first(last_screen, templates)
            if match is not None:
                return last_screen, match
            self.sleep(self.config.wait_seconds)
        return last_screen, None

    def _open_tab(self, screen, tabs: list[Path], opened: list[Path], name: str,
                  scroll_if_missing: bool = False,
                  required_closed: list[Path] | None = None):
        tab = None
        for attempt in range(8):
            state, _, closed_match = self._tab_state(screen, tabs, opened)
            if state == "open" and not required_closed:
                return screen
            if state == "closed":
                tab = closed_match
                break
            if scroll_if_missing and attempt in {1, 3, 5}:
                # Swipe only reveals the list; the previously opened tab may be off-screen.
                logging.getLogger("dc3q").info("HD | vuốt tìm tab %s | lần=%d", name, attempt)
                self.input.swipe(170, 450, 170, 220, 400)
                self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
        if tab is None:
            raise RuntimeError(f"Hoạt động: không nhận diện được ảnh tab {name} sau khi vuốt tìm")
        self._tap(tab)
        for _ in range(8):
            verify = self.screen_provider()
            state, _, _ = self._tab_state(verify, tabs, opened)
            prior_closed = self._first(verify, required_closed or [])
            if state == "open" and (not required_closed or prior_closed is not None):
                return verify
            self.sleep(self.config.wait_seconds)
        raise RuntimeError(f"Hoạt động: bấm {name} nhưng chưa thấy tab mở và tab trước đóng")

    @staticmethod
    def _tick_pixels(cell) -> int:
        """Count the invariant dark-green tick color; ignore reward artwork."""
        import cv2
        import numpy as np

        if hasattr(cell, "convert") and not hasattr(cell, "shape"):
            cell = np.asarray(cell.convert("RGB"))
        hsv = cv2.cvtColor(cell, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, (31, 103, 121), (40, 255, 146))
        return int(cv2.countNonZero(mask))

    @staticmethod
    def _makeup_pixels(cell) -> tuple[int, int]:
        """Detect the pale makeup ribbon plus its green border; ignore reward art."""
        import cv2
        import numpy as np

        if hasattr(cell, "convert") and not hasattr(cell, "shape"):
            cell = np.asarray(cell.convert("RGB"))
        maximum = cell.max(axis=2)
        minimum = cell.min(axis=2)
        pale = ((maximum > 180) & ((maximum - minimum) < 45)).astype("uint8")
        green = cv2.inRange(cell, (0, 100, 0), (150, 255, 180))
        return int(cv2.countNonZero(pale)), int(cv2.countNonZero(green))

    def _attendance_cells(self, screen):
        data = screen.data if hasattr(screen, "data") else screen
        x1, y1, x2, y2 = self.config.attendance_grid
        width, height = x2 - x1, y2 - y1
        cells = []
        for index in range(30):
            row, col = divmod(index, 8)
            left = x1 + round(col * width / 8)
            right = x1 + round((col + 1) * width / 8)
            top = y1 + round(row * height / 4)
            bottom = y1 + round((row + 1) * height / 4)
            cells.append(
                data.crop((left, top, right, bottom))
                if hasattr(data, "crop") else data[top:bottom, left:right]
            )
        return cells

    def _attendance_states(self, screen) -> list[str]:
        states: list[str] = []
        for cell in self._attendance_cells(screen):
            makeup = (
                self._match(cell, self.config.attendance_makeup, 0.80)
                if self.config.attendance_makeup else None
            )
            if makeup and makeup.found:
                states.append("makeup")
            elif self._tick_pixels(cell) >= 180:
                states.append("tick")
            elif self._makeup_pixels(cell)[0] >= 120 and self._makeup_pixels(cell)[1] >= 200:
                states.append("makeup")
            else:
                states.append("blank")
        return states

    def _attendance_candidate(self, screen, states: list[str]) -> int | None:
        """Tick and makeup are both handled; click only after the last handled cell."""
        return self.next_attendance_index(states)

    def _attendance_reset(self, screen) -> bool:
        """A new cycle is proven when none of the 30 corrected day cells has a tick."""
        return all(self._tick_pixels(cell) < 180 for cell in self._attendance_cells(screen))

    def _saved_attendance_candidate(self, screen) -> int | None:
        saved = self.attendance_day()
        if saved is None:
            # No trustworthy persisted baseline: do not guess from artwork.
            return None
        if saved < 30:
            return saved  # zero-based index of saved day + 1
        return 0 if self._attendance_reset(screen) else None

    def _attendance_changed(self, before, after, index: int) -> bool:
        """Prove the exact tapped cell changed, independent of tick artwork."""
        import cv2
        import numpy as np

        def array(cell):
            if hasattr(cell, "convert") and not hasattr(cell, "shape"):
                return np.asarray(cell.convert("RGB"))
            return np.asarray(cell)

        left = array(self._attendance_cells(before)[index])
        right = array(self._attendance_cells(after)[index])
        return float(cv2.absdiff(left, right).mean()) >= 3.0

    def _tap_attendance(self, index: int) -> None:
        x1, y1, x2, y2 = self.config.attendance_grid
        row, col = divmod(index, 8)
        self.input.tap(
            x1 + round((col + 0.5) * (x2 - x1) / 8),
            y1 + round((row + 0.5) * (y2 - y1) / 4),
        )
        self.sleep(self.config.wait_seconds)

    def _milestone_state(self, screen, roi: tuple[int, int, int, int]):
        """Classify one 10/20/30-day reward from competing crop templates."""
        data = screen.data if hasattr(screen, "data") else screen
        x1, y1, x2, y2 = roi
        crop = data.crop(roi) if hasattr(data, "crop") else data[y1:y2, x1:x2]
        states = [
            ("claimable", self._match(crop, self.config.attendance_milestone_claimable, 0.0)),
            ("locked", self._match(crop, self.config.attendance_milestone_locked, 0.0)),
            ("claimed", self._match(crop, self.config.attendance_milestone_claimed, 0.0)),
        ]
        state, match = max(states, key=lambda pair: pair[1].confidence)
        runner_up = max(item.confidence for name, item in states if name != state)
        minimum = 0.95 if state == "claimable" else self.config.state_threshold
        if match.confidence < minimum or match.confidence < runner_up + 0.05:
            return "unknown", match, runner_up
        return state, match, runner_up

    def _claim_attendance_milestones(self, screen):
        """Claim only proven 10/20/30-day rewards, then verify each one."""
        logger = logging.getLogger("dc3q")
        for day, roi in zip((10, 20, 30), self.config.attendance_milestone_rois):
            state, match, runner_up = self._milestone_state(screen, roi)
            logger.info(
                "HD | Báo danh tích lũy %d ngày | trạng_thái=%s | điểm=%.3f | cạnh_tranh=%.3f",
                day, state, match.confidence, runner_up,
            )
            if state != "claimable":
                # Fail closed: locked, claimed, or ambiguous rewards are never tapped.
                continue
            x1, y1, _, _ = roi
            self.input.tap(x1 + match.x + match.width // 2, y1 + match.y + match.height // 2)
            self.sleep(self.config.wait_seconds)
            for _ in range(10):
                verify = self.screen_provider()
                if self._reward(verify):
                    verify = self.screen_provider()
                verified, _, _ = self._milestone_state(verify, roi)
                if verified == "claimed":
                    logger.info("HD | nhận quà Báo danh tích lũy %d ngày thành công", day)
                    screen = verify
                    break
                self.sleep(self.config.wait_seconds)
            else:
                raise RuntimeError(f"Hoạt động: nhận quà tích lũy {day} ngày nhưng chưa thấy Đã nhận")
        return screen

    def _tax_window_open(self) -> bool:
        hour = self.now().hour
        return any(start <= hour < end for start, end in self.TAX_WINDOWS)

    def _claim_tax(self, screen) -> None:
        logger = logging.getLogger("dc3q")
        # Let the newly opened tab settle before classifying its action button.
        self.sleep(max(self.config.wait_seconds, 1.5))
        screen = self.screen_provider()
        unavailable = self._match(screen, self.config.tax_unavailable, self.config.state_threshold)
        claimed = self._match(screen, self.config.tax_claimed, self.config.state_threshold)
        claimable = self._match(screen, self.config.tax_claimable, self.config.state_threshold)
        states = [("unavailable", unavailable), ("claimed", claimed), ("claimable", claimable)]
        state, winner = max(states, key=lambda pair: pair[1].confidence)
        runner_up = max(match.confidence for name, match in states if name != state)
        if not winner.found or winner.confidence < runner_up + 0.05:
            raise RuntimeError("Hoạt động: trạng thái Trưng thu thuế xung đột hoặc chưa ổn định")
        if state == "unavailable":
            logger.info("HD | Trưng thu thuế đang Chưa mở")
            return
        if state == "claimed":
            logger.info("HD | Trưng thu thuế đã trưng thu")
            return
        self._tap(claimable)
        logger.info("HD | bấm nút Trưng thu đã nhận diện")
        self.sleep(max(self.config.wait_seconds, 1.5))
        for _ in range(10):
            verify = self.screen_provider()
            if self._reward(verify):
                continue
            if self._match(verify, self.config.tax_claimed, self.config.state_threshold).found:
                logger.info("HD | xác nhận Đã trưng thu")
                return
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Hoạt động: bấm Trưng thu nhưng chưa thấy Đã trưng thu")

    def recover_home(self) -> bool:
        """Physically close only recognized Activity layers until HOME."""
        logger = logging.getLogger("dc3q")
        for _ in range(12):
            screen = self.screen_provider()
            if self._match(screen, self.config.reward_marker).found:
                dismiss = self._match(screen, self.config.reward_dismiss)
                if not dismiss.found:
                    return False
                self._tap(dismiss)
                logger.info("HD | recovery đóng thưởng")
                continue
            if self._first(screen, self.config.panel_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if not close.found:
                    return False
                self._tap(close)
                logger.info("HD | recovery đóng Hoạt động")
                continue
            if self._first(screen, self.config.home_markers) is not None:
                logger.info("HD | recovery đã về HOME")
                return True
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        screen = self.screen_provider()
        entry = self._first(screen, self.config.entry_templates)
        if entry is None:
            closed = self._match(screen, self.config.menu_templates[0])
            opened = self._match(screen, self.config.menu_templates[1])
            if opened.found and opened.confidence >= closed.confidence:
                raise RuntimeError("Hoạt động: menu đang mở nhưng thiếu icon Hoạt động")
            if not closed.found or closed.confidence <= opened.confidence:
                raise RuntimeError("Hoạt động: không xác định được trạng thái menu HOME")
            self._tap(closed)
            screen, entry = self._wait_for(self.config.entry_templates)
        if entry is None:
            raise RuntimeError("Hoạt động: menu đã mở nhưng thiếu icon Hoạt động")
        self._tap(entry)
        logger.info("HD | mở Hoạt động")

        screen, panel = self._wait_for(self.config.panel_markers)
        if panel is None:
            raise RuntimeError("Hoạt động: bấm icon nhưng panel chưa mở sau khi chờ")
        # panel_markers are the selected Phúc lợi images. Their appearance is
        # already the visual postcondition; do not re-classify/click this tab.
        logger.info("HD | xác nhận Phúc lợi đã mở")

        screen = self._open_tab(
            screen, self.config.national_tabs, self.config.national_open,
            "Lễ bao quốc vận",
        )
        for _ in range(8):
            free = self._match(screen, self.config.national_free, self.config.state_threshold)
            claimed = self._match(screen, self.config.national_claimed, self.config.state_threshold)
            if free.found or claimed.found:
                break
            self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
        else:
            raise RuntimeError("Hoạt động: Lễ bao quốc vận chưa ổn định, không xác định được trạng thái")
        if free.found and free.confidence > claimed.confidence:
            self._tap(free)
            logger.info("HD | nhận Lễ bao quốc vận miễn phí")
            screen = self._settle_claim([self.config.national_claimed])
        elif claimed.found:
            logger.info("HD | Lễ bao quốc vận không còn nút miễn phí")
        else:
            raise RuntimeError("Hoạt động: trạng thái Lễ bao quốc vận xung đột")

        screen = self._open_online_tab(screen)
        logger.info("HD | đã mở tab Quà online")
        self._claim_online(screen)
        screen = self.screen_provider()

        screen = self._open_attendance_tab(screen)
        logger.info("HD | đã mở Điểm danh trực tiếp sau Quà online")
        states = self._attendance_states(screen)
        candidate = self._saved_attendance_candidate(screen)
        logger.info(
            "HD | Điểm danh đã_lưu=%s | marked=%s | candidate=%s",
            self.attendance_day(),
            [i + 1 for i, state in enumerate(states) if state in {"tick", "makeup"}],
            None if candidate is None else candidate + 1,
        )
        if candidate is not None:
            before = screen
            self._tap_attendance(candidate)
            changed = False
            verify = before
            for _ in range(10):
                verify = self.screen_provider()
                if self._reward(verify):
                    verify = self.screen_provider()
                if self._attendance_changed(before, verify, candidate):
                    changed = True
                    break
                self.sleep(self.config.wait_seconds)
            if changed:
                self.save_attendance_day(candidate + 1)
                logger.info("HD | điểm danh ô %d thành công", candidate + 1)
            else:
                logger.info("HD | ô %d không đổi; giữ nguyên ngày điểm danh đã lưu", candidate + 1)
            screen = verify
        else:
            logger.info("HD | không có ngày điểm danh an toàn từ dữ liệu đã lưu")

        screen = self._claim_attendance_milestones(screen)

        if self._tax_window_open():
            screen = self._open_tab(
                screen, self.config.tax_tabs, self.config.tax_open,
                "Trưng thu thuế", scroll_if_missing=True,
                required_closed=self.config.attendance_tabs,
            )
            logger.info("HD | đã mở tab Trưng thu thuế")
            self._claim_tax(screen)
        else:
            logger.info("HD | bỏ qua Trưng thu thuế ngoài khung giờ")

        screen = self.screen_provider()
        close = self._match(screen, self.config.close_template)
        if not close.found:
            raise RuntimeError("Hoạt động: thiếu nút đóng")
        self._tap(close)
        logger.info("HD | đóng Hoạt động")
        for _ in range(5):
            screen = self.screen_provider()
            if self._first(screen, self.config.home_markers) and self._first(screen, self.config.panel_markers) is None:
                return True
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Hoạt động: đóng xong nhưng chưa về HOME")
