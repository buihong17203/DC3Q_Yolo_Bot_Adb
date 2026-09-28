from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET
from app.accounts.manager import Account
from app.adb.input import AdbInput
from app.vision import VisionDetector
from app.state.login import LoginScreenState


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

class AccountLoginAction:
    """Physical UI login only: screenshot -> locate -> tap -> type.

    No game data, database, shared preference, memory, package internals, ESC,
    BACK or automated logout is used by this action.
    """
    def __init__(self, adb_input: AdbInput, coordinates: LoginCoordinates | None = None,
                 vision: VisionDetector | None = None):
        self.input = adb_input
        self.coordinates = coordinates or LoginCoordinates()
        self.vision = vision or VisionDetector()

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

    def _require_login_screen(self, screen_provider, detector, login_templates, threshold_screen: float) -> None:
        screen = screen_provider()
        d = detector.detect(screen, login_templates=login_templates, logged_in_templates=[], threshold=threshold_screen)
        if d.state != LoginScreenState.LOGIN_SCREEN:
            raise RuntimeError(f"Không thao tác: màn hình hiện tại không phải LOGIN_SCREEN ({d.state.value})")

    def login(self, account: Account, screen_provider, *, username_template, password_templates,
              submit_template, threshold=0.75, expected_login_detector=None,
              login_templates=None, threshold_screen=0.80) -> None:
        detector = expected_login_detector
        if detector is None or login_templates is None:
            raise RuntimeError("Login action bắt buộc phải có screen detector")

        # Username: confirm screen -> locate -> physical tap -> physical typing.
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

        # Password: confirm screen again before physical interaction.
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

        # Submit: confirm screen again before physical click.
        self._require_login_screen(screen_provider, detector, login_templates, threshold_screen)
        screen = screen_provider()
        if self.coordinates.submit:
            self.input.tap(*self.coordinates.submit)
        elif self._tap_accessibility("com.daichien.mobile:id/btn_login"):
            pass
        elif not self._find_and_tap(screen, submit_template, threshold):
            raise RuntimeError("Không tìm thấy nút đăng nhập trên màn hình login")
