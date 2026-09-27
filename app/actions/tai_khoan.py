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


def reflected_point(anchor: tuple[int, int], size: tuple[int, int],
                    offset: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Reflect an anchor through screen center, then apply calibrated offset."""
    x, y = anchor
    width, height = size
    dx, dy = offset
    return width - x + dx, height - y + dy


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
        if label not in {"x", "×", "đóng", "thoát", "close"}:
            continue
        values = [int(value) for value in re.findall(r"\d+", node.attrib.get("bounds", ""))]
        if len(values) == 4:
            return "profile_update_close", ((values[0] + values[2]) // 2, (values[1] + values[3]) // 2)
    return "profile_update_blocked", None


def select_logout_state(found: dict[str, bool]) -> str:
    """Resume forward from the deepest positively recognized logout layer."""
    for state in ("login", "confirm", "switch", "settings", "options", "home"):
        if found.get(state):
            return state
    return "unknown"


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


@dataclass(frozen=True)
class LogoutTemplates:
    open_tuychon: Path
    open_cdnd: Path
    open_dtk: Path
    confirm_dtk: Path
    home_anchor_template: Path
    home_anchor_roi: tuple[int, int, int, int] = (840, 490, 980, 575)
    avatar_mirror_offset: tuple[int, int] = (-8, 21)


class AccountLogoutAction:
    """Forward-only, restart-safe switch-account state machine."""
    def __init__(self, adb_input: AdbInput, templates: LogoutTemplates | None = None,
                 vision: VisionDetector | None = None):
        self.input = adb_input
        self.templates = templates
        self.vision = vision or VisionDetector()

    def _match(self, screen, template, threshold: float):
        return self.vision.find_template(screen, "logout_control", template, threshold).match

    def _find_and_tap(self, screen, template: str | Path, threshold: float = 0.75) -> bool:
        r = self._match(screen, template, threshold)
        if not r.found:
            return False
        self.input.tap(r.x + r.width // 2, r.y + r.height // 2)
        return True

    def _avatar_from_noi_chinh(self, screen, templates: LogoutTemplates,
                               threshold: float) -> tuple[int, int] | None:
        """Find Nội chính, reflect it through screen center, derive avatar."""
        import cv2
        import numpy as np

        anchor = cv2.imdecode(
            np.fromfile(str(templates.home_anchor_template), dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if anchor is None:
            raise FileNotFoundError(templates.home_anchor_template)
        x1, y1, x2, y2 = templates.home_anchor_roi
        data = screen.data if hasattr(screen, "data") else screen
        if hasattr(data, "convert"):
            data = np.asarray(data.convert("RGB"))
        else:
            data = np.asarray(data)
        height, width = data.shape[:2]
        ref_width, ref_height = 1000, 575
        scaled = cv2.resize(anchor, (max(1, round(anchor.shape[1] * width / ref_width)),
                                     max(1, round(anchor.shape[0] * height / ref_height))),
                            interpolation=cv2.INTER_AREA)
        sx1 = max(0, round(x1 * width / ref_width))
        sy1 = max(0, round(y1 * height / ref_height))
        sx2 = min(width, round(x2 * width / ref_width))
        sy2 = min(height, round(y2 * height / ref_height))
        # Template can sit on the right/bottom border. Keep the full scaled
        # crop inside the search ROI instead of clipping its last columns.
        sx2 = min(width, max(sx2, sx1 + scaled.shape[1]))
        sy2 = min(height, max(sy2, sy1 + scaled.shape[0]))
        search = data[sy1:sy2, sx1:sx2]
        if search.ndim == 3:
            search = cv2.cvtColor(search, cv2.COLOR_RGB2GRAY)
        if scaled.ndim == 3:
            scaled = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
        if search.shape[0] < scaled.shape[0] or search.shape[1] < scaled.shape[1]:
            return None
        result = cv2.matchTemplate(search, scaled, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        # Small edge HUD crops vary slightly with animation/compression. The
        # configured threshold remains strict elsewhere; this anchor has a
        # narrow ROI and only authorizes opening the profile.
        anchor_threshold = max(0.0, threshold - 0.02)
        if score < anchor_threshold:
            return None
        anchor_center = (
            sx1 + location[0] + scaled.shape[1] // 2,
            sy1 + location[1] + scaled.shape[0] // 2,
        )
        point = reflected_point(anchor_center, (width, height), templates.avatar_mirror_offset)
        return max(0, min(width - 1, point[0])), max(0, min(height - 1, point[1]))

    def logout(self, screen_provider, *, templates: LogoutTemplates | None = None,
               threshold: float = 0.75, max_attempts: int = 5,
               login_detector=None, login_templates=(), login_threshold: float = 0.80) -> bool:
        tpls = templates or self.templates
        if tpls is None:
            raise RuntimeError("AccountLogoutAction cần cấu hình templates")

        unknown_hits = 0
        for _ in range(max_attempts * 6):
            screen = screen_provider()
            at_login = False
            if login_detector is not None:
                at_login = login_detector.detect(
                    screen,
                    login_templates=login_templates,
                    logged_in_templates=[],
                    threshold=login_threshold,
                ).state == LoginScreenState.LOGIN_SCREEN

            matches = {
                "login": at_login,
                "confirm": self._match(screen, tpls.confirm_dtk, threshold).found,
                "switch": self._match(screen, tpls.open_dtk, threshold).found,
                "settings": self._match(screen, tpls.open_cdnd, threshold).found,
                "options": self._match(screen, tpls.open_tuychon, threshold).found,
            }
            avatar = self._avatar_from_noi_chinh(screen, tpls, threshold)
            matches["home"] = avatar is not None
            state = select_logout_state(matches)

            if state == "login":
                return True
            if state == "confirm":
                self._find_and_tap(screen, tpls.confirm_dtk, threshold)
            elif state == "switch":
                self._find_and_tap(screen, tpls.open_dtk, threshold)
            elif state == "settings":
                self._find_and_tap(screen, tpls.open_cdnd, threshold)
            elif state == "options":
                self._find_and_tap(screen, tpls.open_tuychon, threshold)
            elif state == "home" and avatar is not None:
                self.input.tap(*avatar)
            else:
                # Game can show loading/transition frames for several seconds
                # after Confirm. Keep polling to the controller's full bounded
                # budget; never mistake a temporary UNKNOWN frame for failure.
                unknown_hits += 1
                if unknown_hits >= max_attempts * 6:
                    raise RuntimeError("Không nhận diện được HOME hoặc lớp đăng xuất hiện tại")
                time.sleep(0.8)
                continue

            unknown_hits = 0
            time.sleep(0.8)

        raise RuntimeError("Đăng xuất quá số bước cho phép; chưa về màn hình đăng nhập")
