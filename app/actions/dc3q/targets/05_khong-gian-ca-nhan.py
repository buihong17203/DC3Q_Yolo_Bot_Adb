from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable

LOGGER = logging.getLogger("dc3q")


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
    battle_report_entry: Path
    mail_tab_closed: Path
    mail_tab_open: Path
    mail_claim: Path
    mail_claimed: Path
    mail_delete: Path
    mail_close: Path
    threshold: float = 0.65
    state_threshold: float = 0.80
    max_steps: int = 24
    wait_seconds: float = 0.8
    state_wait_attempts: int = 24
    info_close: Path | None = None
    mail_max_messages: int = 30


class KhongGianCaNhanRunner:
    runtime_task = "KHONG_GIAN_CA_NHAN"

    def __init__(self, screen_provider, adb_input, vision, config: KhongGianCaNhanConfig,
                 sleep: Callable[[float], None] = default_sleep,
                 home_entry: Callable[[object], tuple[int, int] | None] | None = None,
                 account_level_provider: Callable[[], str] | None = None):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep
        self.home_entry = home_entry
        self.account_level_provider = account_level_provider or (lambda: "")

    def _get_account_level(self) -> int | None:
        try:
            raw = str(self.account_level_provider() or "").strip()
            if raw.isdigit():
                return int(raw)
        except Exception:
            pass
        return None

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
            if self._first(screen, self.config.info_markers) is not None:
                if self.config.info_close is None:
                    return False
                close = self._match(screen, self.config.info_close)
                if not close.found:
                    return False
                self._tap(close)
                continue
            cb_close = self._match(screen, self.config.mail_close)
            if cb_close.found:
                self._tap(cb_close)
                continue
            self.sleep(self.config.wait_seconds)
        return False

    def home_templates(self) -> list[Path]:
        return self.config.home_markers

    def _return_to_info_after_personal_close(self, screen):
        if self._first(screen, self.config.info_markers) is not None:
            return screen
        if self._first(screen, self.home_templates()) is None:
            return self._prove(
                self.config.info_markers,
                "Không gian cá nhân: đóng panel nhưng chưa về Thông tin của tôi/HOME",
            )
        point = self.home_entry(screen) if self.home_entry else None
        if point is None:
            raise RuntimeError("Không gian cá nhân: về HOME nhưng chưa chứng minh được nút mở hồ sơ")
        self.input.tap(*point)
        self.sleep(self.config.wait_seconds)
        return self._prove(
            self.config.info_markers,
            "Không gian cá nhân: mở lại hồ sơ nhưng chưa thấy Thông tin của tôi",
        )

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

    @staticmethod
    def _plain(text: str) -> str:
        import unicodedata
        return "".join(
            char for char in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(char)
        ).lower()

    def _ocr_rows(self, screen):
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        data = screen.data if hasattr(screen, "data") else screen
        image = np.asarray(data.convert("RGB")) if hasattr(data, "convert") else np.asarray(data)
        result, _ = RapidOCR()(image)
        return result or []

    def _ocr_text(self, screen) -> str:
        return self._plain(" ".join(str(row[1]) for row in self._ocr_rows(screen)))

    def _find_ocr_center(
        self, screen, keywords: str | list[str],
        y_min: int = 0, y_max: int = 9999,
        x_min: int = 0, x_max: int = 9999,
    ) -> tuple[int, int] | None:
        if isinstance(keywords, str):
            keywords = [keywords]
        clean_keys = [self._plain(k).replace(" ", "") for k in keywords]
        for row in self._ocr_rows(screen):
            text = self._plain(str(row[1])).replace(" ", "")
            if any(k in text for k in clean_keys):
                points = row[0]
                x = int(sum(point[0] for point in points) / len(points))
                y = int(sum(point[1] for point in points) / len(points))
                if x_min <= x <= x_max and y_min <= y <= y_max:
                    return x, y
        return None

    def _mail_count(self, screen) -> int | None:
        import re
        text = self._ocr_text(screen)
        match = re.search(r"(\d+)\s*/\s*30", text)
        if match:
            return int(match.group(1))
        match_alt = re.search(r"(\d+)\s*/\s*\d+", text)
        if match_alt:
            return int(match_alt.group(1))
        return None

    def _has_claim_button(self, screen) -> tuple[bool, tuple[int, int] | None]:
        claim = self._match(screen, self.config.mail_claim, self.config.state_threshold)
        claimed = self._match(screen, self.config.mail_claimed, self.config.state_threshold)
        if claim.found and claim.confidence >= (claimed.confidence if claimed.found else 0.0):
            return True, (claim.x + claim.width // 2, claim.y + claim.height // 2)
        ocr_pos = self._find_ocr_center(screen, "nhan", y_min=450, x_min=650)
        if ocr_pos:
            return True, ocr_pos
        return False, None

    def _has_delete_button(self, screen) -> tuple[bool, tuple[int, int] | None]:
        delete = self._match(screen, self.config.mail_delete, self.config.state_threshold)
        if delete.found:
            return True, (delete.x + delete.width // 2, delete.y + delete.height // 2)
        ocr_pos = self._find_ocr_center(screen, "xoa", y_min=450, x_min=350, x_max=550)
        if ocr_pos:
            return True, ocr_pos
        return False, None

    def _open_battle_report(self, screen):
        if self._first(screen, self.home_templates()) is None:
            if not self.recover_home():
                raise RuntimeError("Không gian cá nhân: chưa ở HOME trước Chiến báo")
            screen = self.screen_provider()

        entry_match = self._match(screen, self.config.battle_report_entry)
        if entry_match.found:
            self._tap(entry_match)
        else:
            cb_pos = self._find_ocr_center(screen, "chienbao")
            if cb_pos:
                self.input.tap(*cb_pos)
                self.sleep(self.config.wait_seconds)
            else:
                raise RuntimeError("Không gian cá nhân: HOME thiếu control Chiến báo (template & OCR)")

        screen = self._prove(
            [self.config.mail_tab_closed, self.config.mail_tab_open, self.config.mail_close],
            "Không gian cá nhân: bấm Chiến báo nhưng chưa mở bảng",
            self.config.state_wait_attempts,
        )

        closed = self._match(screen, self.config.mail_tab_closed, self.config.state_threshold)
        opened = self._match(screen, self.config.mail_tab_open, self.config.state_threshold)
        if closed.found and (not opened.found or closed.confidence > opened.confidence):
            self._tap(closed)
            screen = self._prove(
                [self.config.mail_tab_open],
                "Không gian cá nhân: mở Nhận rương nhưng chưa thấy tab mở",
                self.config.state_wait_attempts,
            )
        elif not opened.found:
            nr_pos = self._find_ocr_center(screen, ["nhenruong", "nhanruong"])
            if nr_pos:
                self.input.tap(*nr_pos)
                self.sleep(self.config.wait_seconds)
                screen = self.screen_provider()

        return screen

    def _dismiss_full_bag(self, screen) -> tuple[object, bool]:
        text = self._ocr_text(screen)
        if "khong du cho" not in text or "tui the vo tuong" not in text:
            return screen, False
        LOGGER.info("KGCN | Phát hiện popup kho không đủ chỗ, đang đóng nút X...")
        # Live 960x540 popup: X=(705, 139); never Enhance/Expand bag.
        self.input.tap(705, 139)
        self.sleep(self.config.wait_seconds)
        after = self.screen_provider()
        after_text = self._ocr_text(after)
        if "khong du cho" in after_text and "tui the vo tuong" in after_text:
            raise RuntimeError("Không gian cá nhân: popup kho đầy chưa đóng")
        return after, True

    def _delete_current_mail(self, screen, count_before: int | None):
        has_del, del_pos = self._has_delete_button(screen)
        if not has_del:
            LOGGER.info("KGCN | Không tìm thấy nút Xóa thư hiện tại")
            return screen
        self.input.tap(*del_pos)
        self.sleep(self.config.wait_seconds)

        # Prove the destructive popup before its right-side confirm.
        popup_handled = False
        for _ in range(6):
            prompt = self.screen_provider()
            prompt_text = self._ocr_text(prompt)
            if any(phrase in prompt_text for phrase in ("chac chan", "muon xoa", "dinh kem", "xoa thu", "vat pham")) or any(k in prompt_text for k in ("xacnhan", "dongy")):
                confirm_pos = self._find_ocr_center(
                    prompt, ["xacnhan", "dongy"], y_min=300, y_max=410, x_min=500,
                )
                if confirm_pos:
                    self.input.tap(*confirm_pos)
                else:
                    self.input.tap(590, 354)
                self.sleep(self.config.wait_seconds)
                popup_handled = True
                break
            if count_before is not None and self._mail_count(prompt) == count_before - 1:
                return prompt
            self.sleep(0.3)

        if not popup_handled:
            LOGGER.info("KGCN | không có popup xác nhận xóa (hoặc đã xóa thẳng); tiếp tục")


        if count_before is None:
            raise RuntimeError("Không gian cá nhân: không đọc được số thư trước khi Xóa")
        # Only exact N→N-1 proves deletion; popup disappearance is insufficient.
        for _ in range(self.config.state_wait_attempts):
            after = self.screen_provider()
            count_after = self._mail_count(after)
            if count_after == count_before - 1:
                return after
            self.sleep(self.config.wait_seconds)
        raise RuntimeError("Không gian cá nhân: Xóa thư nhưng số lượng không giảm đúng 1")

    def _process_battle_report_mail(self, screen):
        for index in range(self.config.mail_max_messages):
            count_before = self._mail_count(screen)
            if count_before == 0:
                LOGGER.info("KGCN | Chiến báo đã xử lý hết thư (count=0)")
                break

            has_del, _ = self._has_delete_button(screen)
            has_claim, claim_pos = self._has_claim_button(screen)
            if not has_del and not has_claim:
                LOGGER.info("KGCN | Không còn nút Nhận/Xóa trên màn hình -> Hết thư")
                break

            # 1. Nếu có nút nhận thưởng: bấm nhận thưởng
            if has_claim and claim_pos:
                LOGGER.info("KGCN | Thư %d: bấm nút Nhận tại %s", index + 1, claim_pos)
                self.input.tap(*claim_pos)
                self.sleep(self.config.wait_seconds)
                screen = self.screen_provider()

                # Kiểm tra popup kho không đủ chỗ
                screen, full = self._dismiss_full_bag(screen)
                if full:
                    # Bấm nhận tiếp lần 2
                    has_claim2, claim_pos2 = self._has_claim_button(screen)
                    if has_claim2 and claim_pos2:
                        LOGGER.info("KGCN | Thư %d: kho đầy -> bấm Nhận tiếp lần 2", index + 1)
                        self.input.tap(*claim_pos2)
                        self.sleep(self.config.wait_seconds)
                        screen = self.screen_provider()
                        screen, _ = self._dismiss_full_bag(screen)

            # 2. Bấm nút xóa (sau khi nhận xong hoặc nếu không có nút nhận thưởng)
            LOGGER.info("KGCN | Thư %d: thực hiện Xóa thư", index + 1)
            screen = self._delete_current_mail(screen, count_before)

        # Đóng cửa sổ Chiến báo
        close = self._match(screen, self.config.mail_close, self.config.state_threshold)
        if close.found:
            self._tap(close)
        else:
            self.input.tap(876, 75)
            self.sleep(self.config.wait_seconds)

        return self._prove(self.home_templates(), "Không gian cá nhân: đóng Chiến báo nhưng chưa về HOME")

    def run(self) -> bool:
        level = self._get_account_level()
        if level is not None and level < 50:
            LOGGER.info("KGCN | cấp=%d < 50 | không cần làm không gian cá nhân -> bỏ qua", level)
            return True
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
            entry = self._first(screen, self.config.entry_templates)
            if entry is None:
                raise RuntimeError("Không gian cá nhân: không tìm thấy nút mở")
            self._tap(entry)
            screen = self._prove(
                self.config.personal_markers,
                "Không gian cá nhân: bấm mở nhưng chưa thấy panel",
                self.config.state_wait_attempts,
            )
        screen = self._like_all(screen)
        close = self._match(screen, self.config.close_template)
        if not close.found:
            raise RuntimeError("Không gian cá nhân: Like xong nhưng thiếu nút đóng panel")
        self._tap(close)
        screen = self._return_to_info_after_personal_close(self.screen_provider())
        self._share_once(screen)
        if not self.recover_home():
            raise RuntimeError("Không gian cá nhân: không recover_home được")
        screen = self._open_battle_report(self.screen_provider())
        self._process_battle_report_mail(screen)
        return True
