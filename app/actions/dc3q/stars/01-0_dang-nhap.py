from __future__ import annotations
from dataclasses import dataclass
import logging
from pathlib import Path
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from app.accounts.manager import Account
from app.adb.input import AdbInput
from app.vision import VisionDetector
from app.state.login import LoginScreenState

LOGGER = logging.getLogger("dc3q")


def classify_login_ui(xml: str) -> tuple[str, tuple[int, int] | None]:
    """Classify safe post-submit states without exposing field values."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return "unknown", None
    nodes = list(root.iter("node"))
    text = " ".join(
        f"{node.attrib.get('text', '')} {node.attrib.get('content-desc', '')}"
        for node in nodes
    ).casefold()
    if "tên đăng nhập hoặc mật khẩu không đúng" in text:
        return "credential_rejected", None
    if any(marker in text for marker in ("bảo trì", "bao tri", "maintenance")):
        return "maintenance", None
    if any(marker in text for marker in ("captcha", "otp", "xác minh bảo mật", "chọn tài khoản google")):
        return "operator_required", None
    if "cập nhật thông tin" not in text:
        return "unknown", None
    for node in nodes:
        label = f"{node.attrib.get('text', '')} {node.attrib.get('content-desc', '')}".strip().casefold()
        resource_id = node.attrib.get("resource-id", "").rsplit("/", 1)[-1].casefold()
        if label not in {"x", "×", "đóng", "thoát", "close"} and resource_id not in {"btn_close", "button_close"}:
            continue
        values = [int(value) for value in re.findall(r"\d+", node.attrib.get("bounds", ""))]
        if len(values) == 4:
            return "profile_update_close", ((values[0] + values[2]) // 2, (values[1] + values[3]) // 2)
    return "profile_update_blocked", None


@dataclass(frozen=True)
class LoginCoordinates:
    username: tuple[int, int] | None = None
    password: tuple[int, int] | None = None
    submit: tuple[int, int] | None = None
    tiep_tuc: tuple[int, int] | None = None


class AccountLoginAction:
    """Physical UI login: emulator direct input or physical phone with soft keyboard next/continue flow."""

    def __init__(self, adb_input: AdbInput, coordinates: LoginCoordinates | None = None,
                 vision: VisionDetector | None = None):
        self.input = adb_input
        self.coordinates = coordinates or LoginCoordinates()
        self.vision = vision or VisionDetector()

    @staticmethod
    def _plain(text: str) -> str:
        return "".join(
            char for char in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(char)
        ).lower()

    def _find_and_tap(self, screen, template: str | Path, threshold: float) -> bool:
        r = self.vision.find_template(screen, "login_control", template, threshold).match
        if not r.found:
            return False
        self.input.tap(r.x + r.width // 2, r.y + r.height // 2)
        return True

    def _tap_accessibility(self, resource_id: str) -> bool:
        try:
            root = ET.fromstring(self.input.ui_xml())
        except (RuntimeError, ET.ParseError):
            return False
        node = next((n for n in root.iter("node") if n.attrib.get("resource-id") == resource_id), None)
        if node is None:
            return False
        values = [int(value) for value in re.findall(r"\d+", node.attrib.get("bounds", ""))]
        if len(values) != 4:
            return False
        x1, y1, x2, y2 = values
        self.input.tap((x1 + x2) // 2, (y1 + y2) // 2)
        return True

    def _tap_accessibility_by_keywords(self, keywords: list[str]) -> bool:
        try:
            xml = self.input.ui_xml()
            if not xml:
                return False
            root = ET.fromstring(xml)
        except (RuntimeError, ET.ParseError):
            return False

        clean_keys = [self._plain(k).replace(" ", "") for k in keywords]
        for node in root.iter("node"):
            combined = f"{node.attrib.get('text', '')} {node.attrib.get('content-desc', '')} {node.attrib.get('resource-id', '')}"
            text = self._plain(combined).replace(" ", "")
            if any(k in text for k in clean_keys):
                bounds = node.attrib.get("bounds", "")
                values = [int(v) for v in re.findall(r"\d+", bounds)]
                if len(values) == 4:
                    x1, y1, x2, y2 = values
                    self.input.tap((x1 + x2) // 2, (y1 + y2) // 2)
                    return True
        return False

    def _find_ocr_center(self, screen, keywords: list[str]) -> tuple[int, int] | None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            import numpy as np

            data = screen.data if hasattr(screen, "data") else screen
            image = np.asarray(data.convert("RGB")) if hasattr(data, "convert") else np.asarray(data)
            result, _ = RapidOCR()(image)
            if not result:
                return None

            clean_keys = [self._plain(k).replace(" ", "") for k in keywords]
            for row in result:
                text = self._plain(str(row[1])).replace(" ", "")
                if any(k in text for k in clean_keys):
                    points = row[0]
                    cx = int(sum(pt[0] for pt in points) / len(points))
                    cy = int(sum(pt[1] for pt in points) / len(points))
                    return cx, cy
            return None
        except Exception as exc:
            LOGGER.warning("ACTION | TIEP_TUC | Lỗi OCR: %s", exc)
            return None

    def _tap_next_or_continue(self, screen_provider) -> bool:
        """Nhấn nút Tiếp tục (hoặc gửi IME Action Next/Done) trên bảng bàn phím điện thoại."""
        if self.coordinates.tiep_tuc:
            LOGGER.info("ACTION | TIEP_TUC | Dùng tọa độ cấu hình: %s", self.coordinates.tiep_tuc)
            self.input.tap(*self.coordinates.tiep_tuc)
            return True

        keywords = ["tieptuc", "tieptheo", "tiep", "next", "continue", "done", "xong", "hoantat"]
        if self._tap_accessibility_by_keywords(keywords):
            LOGGER.info("ACTION | TIEP_TUC | Tìm thấy và bấm nút qua Accessibility UI")
            return True

        screen = screen_provider()
        ocr_pos = self._find_ocr_center(screen, keywords)
        if ocr_pos:
            LOGGER.info("ACTION | TIEP_TUC | Tìm thấy và bấm nút qua OCR tại: %s", ocr_pos)
            self.input.tap(*ocr_pos)
            return True

        LOGGER.info("ACTION | TIEP_TUC | Fallback gửi KEYCODE_ENTER (66)")
        self.input.keyevent("KEYCODE_ENTER")
        return True

    def clear_login_form(self) -> None:
        """Clear both rejected fields physically; never expose their values."""
        for resource_id in (
            "com.daichien.mobile:id/edt_username",
            "com.daichien.mobile:id/edt_password",
        ):
            if not self._tap_accessibility(resource_id):
                raise RuntimeError(f"Không tìm thấy input cần xóa: {resource_id}")
            self.input.clear_focused_text()

    def _require_login_screen(self, screen_provider, detector, login_templates, threshold_screen: float) -> None:
        screen = screen_provider()
        d = detector.detect(screen, login_templates=login_templates, logged_in_templates=[], threshold=threshold_screen)
        if d.state != LoginScreenState.LOGIN_SCREEN:
            raise RuntimeError(f"Không thao tác: màn hình hiện tại không phải LOGIN_SCREEN ({d.state.value})")

    def _submit_once(self, screen_provider, submit_template, threshold: float,
                     *, missing_is_transition: bool = False) -> bool:
        """Tap a visible submit; during retry, absence means transition in progress."""
        if self._tap_accessibility("com.daichien.mobile:id/btn_login"):
            return True
        screen = screen_provider()
        if self._find_and_tap(screen, submit_template, threshold):
            return True
        if missing_is_transition:
            return False
        raise RuntimeError("Không tìm thấy nút đăng nhập trên màn hình login")

    def submit_current_form(self, screen_provider, submit_template, threshold: float) -> bool:
        return self._submit_once(
            screen_provider, submit_template, threshold, missing_is_transition=True,
        )

    def login(self, account: Account, screen_provider, *, username_template, password_templates,
              submit_template, threshold=0.75, expected_login_detector=None,
              login_templates=None, threshold_screen=0.80) -> None:
        detector = expected_login_detector
        if detector is None or login_templates is None:
            raise RuntimeError("Login action bắt buộc phải có screen detector")

        device = getattr(self.input, "device", None)
        is_emulator = getattr(device, "is_emulator", True) if device else True

        if is_emulator:
            LOGGER.info("LOGIN | Chế độ: GIẢ LẬP PC (tìm nút & nhập trực tiếp)")
            # 1. Username: confirm screen -> locate -> physical tap -> physical typing.
            self._require_login_screen(screen_provider, detector, login_templates, threshold_screen)
            screen = screen_provider()
            if self.coordinates.username:
                self.input.tap(*self.coordinates.username)
            elif self._tap_accessibility("com.daichien.mobile:id/edt_username"):
                pass
            elif not self._find_and_tap(screen, username_template, threshold):
                raise RuntimeError("Không tìm thấy ô tài khoản trên màn hình login")
            time.sleep(0.3)
            self.input.clear_focused_text()
            time.sleep(0.1)
            self.input.text(account.username)
            time.sleep(0.3)

            # 2. Password: confirm screen again before physical interaction.
            self._require_login_screen(screen_provider, detector, login_templates, threshold_screen)
            screen = screen_provider()
            if self.coordinates.password:
                self.input.tap(*self.coordinates.password)
            elif self._tap_accessibility("com.daichien.mobile:id/edt_password"):
                pass
            else:
                if not any(self._find_and_tap(screen, tpl, threshold) for tpl in password_templates):
                    raise RuntimeError("Không tìm thấy ô mật khẩu trên màn hình login")
            time.sleep(0.3)
            self.input.clear_focused_text()
            time.sleep(0.1)
            self.input.text(account.password)
            time.sleep(0.3)

            # 3. Submit
            self._require_login_screen(screen_provider, detector, login_templates, threshold_screen)
            if self.coordinates.submit:
                self.input.tap(*self.coordinates.submit)
            else:
                self._submit_once(screen_provider, submit_template, threshold)
        else:
            LOGGER.info("LOGIN | Chế độ: ĐIỆN THOẠI (sử dụng bảng bàn phím & nút Tiếp tục)")
            # 1. Bấm ô tài khoản để bật bàn phím
            self._require_login_screen(screen_provider, detector, login_templates, threshold_screen)
            screen = screen_provider()
            if self.coordinates.username:
                self.input.tap(*self.coordinates.username)
            elif self._tap_accessibility("com.daichien.mobile:id/edt_username"):
                pass
            elif not self._find_and_tap(screen, username_template, threshold):
                raise RuntimeError("Không tìm thấy ô tài khoản trên màn hình login")
            time.sleep(0.8)  # Đợi bảng bàn phím hiện lên

            # 2. Nhập username
            self.input.clear_focused_text()
            time.sleep(0.2)
            self.input.text(account.username)
            time.sleep(0.5)

            # 3. Bấm nút Tiếp tục để chuyển sang ô nhập mật khẩu
            LOGGER.info("LOGIN | Bấm nút Tiếp tục để chuyển sang ô mật khẩu")
            self._tap_next_or_continue(screen_provider)
            time.sleep(0.8)  # Chờ chuyển focus sang ô mật khẩu

            # 4. Nhập password
            self.input.clear_focused_text()
            time.sleep(0.2)
            self.input.text(account.password)
            time.sleep(0.5)

            # 5. Bấm nút Tiếp tục để đóng bàn phím & quay về màn đăng nhập chính
            LOGGER.info("LOGIN | Bấm nút Tiếp tục để đóng bàn phím & quay về màn đăng nhập chính")
            self._tap_next_or_continue(screen_provider)
            time.sleep(0.8)

            # 6. Đợi và kiểm tra đã quay về màn đăng nhập chính
            for _ in range(5):
                screen = screen_provider()
                d = detector.detect(screen, login_templates=login_templates, logged_in_templates=[], threshold=threshold_screen)
                if d.state == LoginScreenState.LOGIN_SCREEN:
                    break
                # Nếu bàn phím ảo chưa hạ che mất màn hình, bấm BACK nhẹ để ẩn bàn phím
                self.input.keyevent("KEYCODE_BACK")
                time.sleep(0.5)

            self._require_login_screen(screen_provider, detector, login_templates, threshold_screen)

            # 7. Bấm nút đăng nhập trên màn hình chính
            LOGGER.info("LOGIN | Đã ở màn hình chính -> Bấm nút Đăng nhập")
            if self.coordinates.submit:
                self.input.tap(*self.coordinates.submit)
            else:
                self._submit_once(screen_provider, submit_template, threshold)
