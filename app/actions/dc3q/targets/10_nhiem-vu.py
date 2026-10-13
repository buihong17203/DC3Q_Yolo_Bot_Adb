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
    close_template: Path
    blocked_popup_close_point: tuple[int, int]
    blocked_popup_den: Path
    daily_open: Path
    daily_closed: Path
    claim_button: Path
    available_markers: list[Path]
    claimed_markers: list[Path]
    unavailable_markers: list[Path]
    threshold: float = 0.60
    state_threshold: float = 0.76
    max_steps: int = 24
    wait_seconds: float = 0.8
    reward_dismiss_point: tuple[int, int] = (480, 430)


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
        self._rapid_ocr = None

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
        if self._rapid_ocr is None:
            self._rapid_ocr = RapidOCR()
        result, _ = self._rapid_ocr(image)
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
        den = self._match(screen, self.config.blocked_popup_den, self.config.state_threshold)
        if not den.found:
            return False
        return "nhannhiemvu" in self._ocr_text(screen)

    def _daily_tab_state(self, screen) -> str:
        opened = self._match(screen, self.config.daily_open, self.config.state_threshold)
        closed = self._match(screen, self.config.daily_closed, self.config.state_threshold)
        if opened.found and opened.confidence > closed.confidence + 0.03:
            return "open"
        if closed.found and closed.confidence > opened.confidence + 0.03:
            return "closed"
        return "unknown"

    def _is_panel(self, screen) -> bool:
        return self._daily_tab_state(screen) == "open"

    def _close_panel(self, screen) -> None:
        close = self._match(screen, self.config.close_template, self.config.state_threshold)
        if not close.found:
            raise RuntimeError("Nhiệm vụ: bảng Hằng ngày thiếu nút X đóng")
        self._tap(close)

    def _all_matches(self, screen, template: Path, threshold: float):
        import cv2
        import numpy as np
        from app.vision.template import MatchResult

        data = screen.data if hasattr(screen, "data") else screen
        if hasattr(data, "convert") and not hasattr(data, "shape"):
            data = np.asarray(data.convert("RGB"))
        else:
            data = np.asarray(data)
        target = cv2.imread(str(template), cv2.IMREAD_COLOR)
        if target is None:
            raise FileNotFoundError(f"Không đọc được template: {template}")
        source = cv2.cvtColor(data, cv2.COLOR_RGB2GRAY) if data.ndim == 3 else data
        target = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(source, target, cv2.TM_CCOEFF_NORMED)
        mask = (result >= threshold).astype("uint8")
        count, labels, _, _ = cv2.connectedComponentsWithStats(mask)
        height, width = target.shape[:2]
        matches = []
        for label in range(1, count):
            ys, xs = np.where(labels == label)
            if not len(xs):
                continue
            best = int(np.argmax(result[ys, xs]))
            matches.append(MatchResult(
                True, float(result[ys[best], xs[best]]),
                int(xs[best]), int(ys[best]), width, height,
            ))
        return sorted(matches, key=lambda item: (item.y, item.x))

    @staticmethod
    def _same_control(left, right) -> bool:
        left_center = (left.x + left.width // 2, left.y + left.height // 2)
        right_center = (right.x + right.width // 2, right.y + right.height // 2)
        return (
            abs(left_center[0] - right_center[0]) <= max(left.width, right.width) // 2
            and abs(left_center[1] - right_center[1]) <= max(left.height, right.height) // 2
        )

    def _task_claim_buttons(self, screen):
        """Chỉ trả nút Nhận; loại mọi control cùng vị trí nhận diện là Đến."""
        claims = self._all_matches(
            screen, self.config.claim_button, self.config.state_threshold,
        )
        forbidden = self._all_matches(
            screen, self.config.blocked_popup_den, min(0.60, self.config.state_threshold),
        )
        return [
            claim for claim in claims
            if 730 <= claim.x + claim.width // 2 <= 830
            and 180 <= claim.y + claim.height // 2 <= 500
            and not any(
                self._same_control(claim, den)
                and den.confidence >= claim.confidence - 0.08
                for den in forbidden
            )
        ]

    def _task_den_buttons(self, screen):
        """Nút Đến trong danh sách chỉ là trạng thái kết thúc, không bao giờ tap."""
        return [
            match for match in self._all_matches(
                screen, self.config.blocked_popup_den, self.config.state_threshold,
            )
            if match.x + match.width // 2 >= 650
        ]

    def _same_claim_control_present(self, screen, prior) -> bool:
        return any(
            self._same_control(prior, current)
            for current in self._task_claim_buttons(screen)
        )

    def _claim_task_once(self, claim):
        """Tap once, then require that exact Claim control to change/disappear."""
        self._tap(claim)
        for _ in range(3):
            screen = self.screen_provider()
            if not self._same_claim_control_present(screen, claim):
                return screen
            self.sleep(0.15)
        raise RuntimeError("Nhiệm vụ: bấm Nhận nhưng control không đổi")

    @staticmethod
    def _task_list_changed(before, after) -> bool:
        import cv2
        import numpy as np

        def pixels(frame):
            value = frame.data if hasattr(frame, "data") else frame
            return np.asarray(value.convert("RGB")) if hasattr(value, "convert") else np.asarray(value)

        left = pixels(before)[180:510, 250:920]
        right = pixels(after)[180:510, 250:920]
        return left.shape == right.shape and float(cv2.absdiff(left, right).mean()) >= 1.5

    def _scan_more_task_claims(self, screen):
        self.input.swipe(700, 445, 700, 250, 1200)
        self.sleep(max(self.config.wait_seconds, 1.0))
        after = self.screen_provider()
        return after, self._task_list_changed(screen, after)

    def _chest_decision(self, screen):
        """Compete three states per milestone; only a clear available winner is tappable."""
        terminal_states = []
        reference_centers = (352, 450, 548, 647, 797)
        for center_x, available, claimed, unavailable in zip(
            reference_centers,
            self.config.available_markers,
            self.config.claimed_markers,
            self.config.unavailable_markers,
        ):
            ordered = sorted((
                ("available", self._match_chest_roi(screen, available, center_x)),
                ("claimed", self._match_chest_roi(screen, claimed, center_x)),
                ("unavailable", self._match_chest_roi(screen, unavailable, center_x)),
            ), key=lambda item: item[1].confidence, reverse=True)
            winner, match = ordered[0]
            if match.confidence < self.config.state_threshold:
                terminal_states.append("unknown")
            elif winner == "available":
                if match.confidence >= ordered[1][1].confidence + 0.03:
                    return "available", match
                terminal_states.append("unknown")
            else:
                terminal_states.append(winner)
        if "unknown" in terminal_states:
            return "unknown", None
        if "unavailable" in terminal_states:
            return "unavailable", None
        return "claimed", None

    def _match_chest_roi(self, screen, template: Path, reference_center_x: int):
        """Match one milestone only inside the fixed Sôi nổi strip."""
        import cv2
        import numpy as np
        from app.vision.template import MatchResult

        data = screen.data if hasattr(screen, "data") else screen
        source = np.asarray(data.convert("RGB")) if hasattr(data, "convert") else np.asarray(data)
        source = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY) if source.ndim == 3 else source
        target = cv2.imread(str(template), cv2.IMREAD_GRAYSCALE)
        if target is None:
            raise FileNotFoundError(f"Không đọc được template: {template}")
        scale_x = source.shape[1] / 960.0
        scale_y = source.shape[0] / 540.0
        x1 = max(0, int((reference_center_x - 55) * scale_x))
        x2 = min(source.shape[1], int((reference_center_x + 55) * scale_x))
        y1 = max(0, int(45 * scale_y))
        y2 = min(source.shape[0], int(190 * scale_y))
        roi = source[y1:y2, x1:x2]
        result = cv2.matchTemplate(roi, target, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, point = cv2.minMaxLoc(result)
        return MatchResult(
            confidence >= self.config.state_threshold, float(confidence),
            point[0] + x1, point[1] + y1, target.shape[1], target.shape[0],
        )

    def _claim_button(self, screen):
        claim = self._match(screen, self.config.claim_button, self.config.state_threshold)
        return claim if claim.found else None

    def _is_reward_popup(self, screen) -> bool:
        text = self._ocr_text(screen)
        return "chucmung" in text and "nhanduoc" in text

    def _dismiss_reward_popup(self, screen):
        if not self._is_reward_popup(screen):
            raise RuntimeError("Nhiệm vụ: chưa chứng minh popup nhận thưởng")
        self.input.tap(*self.config.reward_dismiss_point)
        self.sleep(self.config.wait_seconds)
        after = self.screen_provider()
        if self._is_reward_popup(after):
            raise RuntimeError("Nhiệm vụ: popup nhận thưởng chưa đóng")
        return after

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
                self._close_panel(screen)
                continue
            self.sleep(self.config.wait_seconds)
        return False

    def run(self) -> bool:
        logger = logging.getLogger("dc3q")
        opened = False
        destination_seen = False
        task_claims = 0
        must_scroll_tasks = False
        phase = "TASKS"
        chest_tapped = False

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

            panel = self._is_panel(screen)
            if not panel and self._is_blocking_popup(screen):
                destination_seen = True
                logger.info("NV | popup nhiệm vụ chặn bảng Hằng ngày; đóng X, không bấm Đến")
                self.input.tap(*self.config.blocked_popup_close_point)
                self.sleep(self.config.wait_seconds)
                continue

            if self._daily_tab_state(screen) == "closed":
                destination_seen = True
                daily = self._match(screen, self.config.daily_closed, self.config.state_threshold)
                self._tap(daily)
                logger.info("NV | mở tab Hằng Ngày bằng asset đã xác minh")
                continue

            if panel:
                destination_seen = True

            if self._is_home(screen) and not panel:
                if destination_seen:
                    return True
                logger.info("NV | HOME còn tồn tại ngay sau tap; chờ panel Nhiệm vụ render")
                self.sleep(self.config.wait_seconds)
                continue

            if not panel:
                if phase == "CHEST_REWARD" and self._is_reward_popup(screen):
                    screen = self._dismiss_reward_popup(screen)
                    phase = "CLOSE"
                    logger.info("NV | đã đóng popup nhận toàn bộ rương Sôi nổi")
                    panel = self._is_panel(screen)
                if phase == "CHEST_REWARD" and not panel:
                    self.sleep(self.config.wait_seconds)
                    continue
            if not panel:
                self.sleep(self.config.wait_seconds)
                continue

            if phase == "TASKS":
                buttons = self._task_claim_buttons(screen)
                if not must_scroll_tasks and buttons:
                    self._claim_task_once(buttons[0])
                    task_claims += 1
                    must_scroll_tasks = True
                    logger.info("NV | nhận thưởng nhiệm vụ | tổng=%d", task_claims)
                    if task_claims >= 30:
                        raise RuntimeError("Nhiệm vụ: vượt giới hạn 30 nút Nhận")
                    continue

                screen, moved = self._scan_more_task_claims(screen)
                must_scroll_tasks = False
                if self._task_claim_buttons(screen):
                    continue
                if moved:
                    logger.info("NV | chưa thấy Nhận; danh sách còn cuộn, quét tiếp")
                    continue
                phase = "CHESTS"
                logger.info("NV | hết nút Nhận; phân loại rương Sôi nổi")

            if phase == "CHESTS":
                state, chest = self._chest_decision(screen)
                logger.info("NV | trạng thái rương Sôi nổi=%s", state)
                if state == "available" and not chest_tapped:
                    self._tap(chest)
                    chest_tapped = True
                    phase = "CHEST_REWARD"
                    logger.info("NV | bấm một rương được nhận; chờ popup nhận toàn bộ")
                    continue
                if state == "unknown":
                    raise RuntimeError("Nhiệm vụ: trạng thái rương Sôi nổi không rõ")
                phase = "CLOSE"

            if phase == "CHEST_REWARD":
                if self._is_reward_popup(screen):
                    screen = self._dismiss_reward_popup(screen)
                    phase = "CLOSE"
                    logger.info("NV | đã đóng popup nhận toàn bộ rương Sôi nổi")
                else:
                    self.sleep(self.config.wait_seconds)
                    continue

            if phase == "CLOSE":
                logger.info("NV | bấm X đóng Nhiệm vụ về HOME | tổng Nhận=%d", task_claims)
                self._close_panel(screen)
                continue

        raise RuntimeError("Nhiệm vụ: vượt quá số bước cho phép")
