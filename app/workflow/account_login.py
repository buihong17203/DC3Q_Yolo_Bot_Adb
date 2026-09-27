from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic, sleep
from app.accounts.manager import AccountManager, Account
from app.accounts.runtime import AccountRuntime
from app.actions.tai_khoan import (
    AccountLoginAction, LoginCoordinates, AccountLogoutAction, LogoutTemplates,
    classify_login_ui,
)
from app.adb import AdbClient, AdbDevice
from app.adb.screenshot import AdbScreenshot
from app.adb.input import AdbInput
from app.state.login import LoginStateDetector, LoginScreenState


def redact_runtime_screenshot(image, *, authentication: bool):
    """Keep one rolling frame without persisting populated credentials."""
    if not authentication:
        return image.copy()
    redacted = image.copy()
    from PIL import ImageDraw
    width, height = redacted.size
    ImageDraw.Draw(redacted).rectangle(
        (round(width * .20), round(height * .24), round(width * .80), round(height * .66)),
        fill=(0, 0, 0),
    )
    return redacted


class AccountLoginPhase(str, Enum):
    WAIT_LOGIN_SCREEN = "wait_login_screen"
    LOGGING_IN = "logging_in"
    PROCESS_HOME_EVENTS = "process_home_events"
    LOGGING_OUT = "logging_out"
    WAIT_MANUAL_LOGOUT = "wait_manual_logout"
    EXHAUSTED = "exhausted"


@dataclass
class AccountLoginConfig:
    login_templates: list[Path]
    logged_in_templates: list[Path]
    username_template: Path
    password_templates: list[Path]
    submit_template: Path
    username: tuple[int, int] | None = None
    password: tuple[int, int] | None = None
    submit: tuple[int, int] | None = None
    threshold: float = 0.80
    control_threshold: float = 0.75
    poll_seconds: float = 1.0
    login_timeout_seconds: float = 180.0
    logged_in_threshold: float = 0.55
    logged_in_confirmations: int = 3
    auto_logout: bool = False
    logout_templates: LogoutTemplates | None = None
    logout_threshold: float = 0.75
    logout_max_attempts: int = 5
    home_events: list[tuple[Path, Path, float]] | None = None


class AccountLoginController:
    """Physical-screen-only login loop.

    Every input is preceded by a fresh screenshot/state confirmation. This
    workflow never reads/modifies game files, shared preferences, databases,
    memory, or other internal game state.
    """
    def __init__(self, adb: AdbClient, device: AdbDevice, accounts: AccountManager,
                 config: AccountLoginConfig, runtime: AccountRuntime):
        self.device, self.accounts, self.config, self.runtime = device, accounts, config, runtime
        self.detector = LoginStateDetector()
        self.screenshot = AdbScreenshot(adb, device)
        self.input = AdbInput(adb, device)
        self.login_action = AccountLoginAction(self.input, LoginCoordinates(config.username, config.password, config.submit))
        self.logout_action = AccountLogoutAction(self.input, config.logout_templates)
        self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
        self.current: Account | None = None
        self._logged_in_hits = 0
        self._profile_update_closed = 0
        self._home_hits = 0
        port = self.device.serial.rsplit("-", 1)[-1]
        self._rolling_screenshot = Path.cwd() / "temp" / f"screenshot_multi_{port}.png"

    def _screen(self):
        from app.vision.image import load_image
        image = load_image(self.screenshot.png_bytes()).data
        self._rolling_screenshot.parent.mkdir(parents=True, exist_ok=True)
        authentication = self.phase in {
            AccountLoginPhase.WAIT_LOGIN_SCREEN,
            AccountLoginPhase.LOGGING_IN,
        }
        temporary = self._rolling_screenshot.with_suffix(".tmp.png")
        redact_runtime_screenshot(image, authentication=authentication).save(temporary)
        temporary.replace(self._rolling_screenshot)
        return image

    def _handle_known_home_event(self, image) -> bool:
        """Close one positively recognized safe random popup."""
        for state_template, close_template, threshold in self.config.home_events or []:
            state = self.logout_action.vision.find_template(
                image, "random_event_state", state_template, threshold,
            ).match
            if not state.found:
                continue
            close = self.logout_action.vision.find_template(
                image, "random_event_close", close_template, threshold,
            ).match
            if not close.found:
                raise RuntimeError(f"Sự kiện ngẫu nhiên đã nhận diện nhưng thiếu nút đóng: {state_template}")
            self.input.tap(close.x + close.width // 2, close.y + close.height // 2)
            return True
        return False

    def _detect(self):
        image = self._screen()
        d = self.detector.detect(image, login_templates=self.config.login_templates,
                                 logged_in_templates=self.config.logged_in_templates,
                                 threshold=self.config.threshold,
                                 logged_in_threshold=self.config.logged_in_threshold)
        LOGGER = __import__("logging").getLogger("dc3q")
        LOGGER.info("SCREEN | device=%s | state=%s | confidence=%.3f | evidence=%s",
                    self.device.serial, d.state.value, d.confidence, d.evidence or "-")
        return image, d

    def poll_once(self) -> AccountLoginPhase:
        self.runtime.maybe_rollover()
        image, d = self._detect()

        if self.phase == AccountLoginPhase.WAIT_LOGIN_SCREEN:
            if d.state == LoginScreenState.LOGIN_SCREEN:
                account = self.accounts.peek_next()
                if account is None:
                    self.phase = AccountLoginPhase.EXHAUSTED
                    return self.phase
                self.current = account
                self.runtime.mark_login_attempt(account.id, self.device.serial)
                try:
                    # The action itself re-screens before every physical input.
                    self.login_action.login(
                        account, self._screen,
                        username_template=self.config.username_template,
                        password_templates=self.config.password_templates,
                        submit_template=self.config.submit_template,
                        threshold=self.config.control_threshold,
                        expected_login_detector=self.detector,
                        login_templates=self.config.login_templates,
                        threshold_screen=self.config.threshold,
                    )
                    self.phase = AccountLoginPhase.LOGGING_IN
                except Exception as exc:
                    self.runtime.mark_error(account.id, self.device.serial, str(exc))
                    raise
            return self.phase

        if self.phase == AccountLoginPhase.LOGGING_IN:
            try:
                unexpected, point = classify_login_ui(self.input.ui_xml())
            except RuntimeError:
                unexpected, point = "unknown", None
            if unexpected == "credential_rejected":
                assert self.current
                message = "Máy chủ từ chối tài khoản hoặc mật khẩu"
                self.runtime.mark_error(self.current.id, self.device.serial, message)
                raise RuntimeError(message)
            if unexpected in {"operator_required", "profile_update_blocked"}:
                assert self.current
                message = f"Cần người vận hành: {unexpected}"
                self.runtime.mark_error(self.current.id, self.device.serial, message)
                raise RuntimeError(message)
            if unexpected == "profile_update_close" and point is not None:
                if self._profile_update_closed >= 1:
                    raise RuntimeError("Popup cập nhật thông tin xuất hiện lại sau khi đã đóng")
                self.input.tap(*point)
                self._profile_update_closed += 1
                self._logged_in_hits = 0
                return self.phase
            if self._handle_known_home_event(image):
                self._logged_in_hits = 0
                return self.phase
            if d.state == LoginScreenState.LOGGED_IN:
                # HOME is proven only by the configured Chính vụ crop.
                self._logged_in_hits += 1
                if self._logged_in_hits >= self.config.logged_in_confirmations:
                    assert self.current
                    self.accounts.commit_logged_in(self.current.id)
                    self.runtime.mark_logged_in(self.current.id, self.device.serial)
                    self.phase = AccountLoginPhase.PROCESS_HOME_EVENTS
            else:
                self._logged_in_hits = 0
            return self.phase

        if self.phase == AccountLoginPhase.PROCESS_HOME_EVENTS:
            if self._handle_known_home_event(image):
                self._home_hits = 0
                return self.phase
            if d.state != LoginScreenState.LOGGED_IN:
                self._home_hits = 0
                return self.phase
            self._home_hits += 1
            if self._home_hits >= self.config.logged_in_confirmations:
                self.phase = (
                    AccountLoginPhase.LOGGING_OUT
                    if self.config.auto_logout
                    else AccountLoginPhase.WAIT_MANUAL_LOGOUT
                )
            return self.phase

        if self.phase == AccountLoginPhase.LOGGING_OUT:
            assert self.current
            LOGGER = __import__("logging").getLogger("dc3q")
            LOGGER.info("Bắt đầu tự động đăng xuất tài khoản: %s", self.current.id)
            try:
                self.logout_action.logout(
                    self._screen,
                    templates=self.config.logout_templates,
                    threshold=self.config.logout_threshold,
                    max_attempts=self.config.logout_max_attempts,
                    login_detector=self.detector,
                    login_templates=self.config.login_templates,
                    login_threshold=self.config.threshold,
                )
                self.runtime.mark_logged_out(self.current.id)
                LOGGER.info("Đã đăng xuất thành công tài khoản: %s. Chờ màn hình đăng nhập...", self.current.id)
                self.current = None
                self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                self._profile_update_closed = 0
                self._home_hits = 0
            except Exception as exc:
                LOGGER.error("Lỗi khi đăng xuất tài khoản %s: %s", self.current.id, exc)
                self.runtime.mark_error(self.current.id, self.device.serial, f"logout error: {exc}")
                raise
            return self.phase

        if self.phase == AccountLoginPhase.WAIT_MANUAL_LOGOUT:
            # INFINITE WAIT: never timeout and never perform logout/back/escape.
            # Advance only after a real screenshot confirms the login screen.
            if d.state == LoginScreenState.LOGIN_SCREEN:
                assert self.current
                self.runtime.mark_logged_out(self.current.id)
                self.current = None
                self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
        return self.phase

    def run(self, stop_event=None) -> None:
        deadline = monotonic() + self.config.login_timeout_seconds
        while not (stop_event and stop_event.is_set()):
            before = self.phase
            self.poll_once()
            if self.phase == AccountLoginPhase.EXHAUSTED:
                return
            if before == AccountLoginPhase.LOGGING_IN and self.phase == AccountLoginPhase.LOGGING_IN and monotonic() > deadline:
                if self.current:
                    self.runtime.mark_error(self.current.id, self.device.serial, "login timeout")
                raise TimeoutError(f"Login timeout: {self.device.serial}")
            if self.phase not in (AccountLoginPhase.LOGGING_IN, AccountLoginPhase.LOGGING_OUT):
                deadline = monotonic() + self.config.login_timeout_seconds
                self._logged_in_hits = 0
            sleep(self.config.poll_seconds)
