from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic, sleep
from typing import Callable
from datetime import datetime
from zoneinfo import ZoneInfo
from app.adb.input import DailyCutoff
from app.accounts.manager import AccountManager, Account
from app.accounts.runtime import AccountRuntime
from app.actions.dc3q.stars import (
    AccountLoginAction, LoginCoordinates, AccountLogoutAction, LogoutTemplates,
    GameRestartRequired, HomeAction, classify_login_ui,
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
    pixels = redacted.data if hasattr(redacted, "data") and hasattr(redacted.data, "shape") else redacted
    if hasattr(pixels, "shape"):
        import cv2
        height, width = pixels.shape[:2]
        cv2.rectangle(
            pixels,
            (round(width * .20), round(height * .24)),
            (round(width * .80), round(height * .66)),
            (0, 0, 0),
            -1,
        )
    else:
        from PIL import ImageDraw
        width, height = redacted.size
        ImageDraw.Draw(redacted).rectangle(
            (round(width * .20), round(height * .24), round(width * .80), round(height * .66)),
            fill=(0, 0, 0),
        )
    return redacted


TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def in_daily_cutoff(now: datetime, hour: int = 22, minute: int = 59) -> bool:
    """Pause gameplay during the one-minute pre-reset drain window."""
    return now.hour == hour and now.minute >= minute


def save_optional_knb(reader, screen, icon, writer, account_id: str) -> bool:
    """Best-effort metadata capture; never blocks verified logout."""
    try:
        value = reader(screen, icon, (82, 8, 125, 32), search_roi=(750, 50, 850, 150), threshold=.45)
        writer(account_id, value)
        return True
    except Exception as exc:
        import logging
        logging.getLogger("dc3q").warning("HOME | bỏ qua lưu KNB: %s", exc)
        return False


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
    tiep_tuc: tuple[int, int] | None = None
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
    home_targets: list[object] | None = None
    save_knb_balance: Callable[[str, int], None] | None = None
    knb_icon: Path | None = None
    cutoff_hour: int = 22
    cutoff_minute: int = 59
    persistent_daily: bool = True
    target_retry_limit: int = 3
    out_game_title: Path | None = None
    out_game_confirm: Path | None = None
    out_game_threshold: float = 0.75
    out_game_confirm_threshold: float = 0.50
    restart_wait_attempts: int = 60
    sub_screen_close_templates: list[Path] | None = None


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
        self.input.set_cutoff_guard(
            lambda: in_daily_cutoff(datetime.now(TIMEZONE), config.cutoff_hour, config.cutoff_minute)
        )
        self.login_action = AccountLoginAction(
            self.input,
            LoginCoordinates(config.username, config.password, config.submit, config.tiep_tuc),
        )
        self.logout_action = AccountLogoutAction(self.input, config.logout_templates)
        self.home_action = HomeAction(self.input, self.logout_action.vision, config)
        from app.state.scene import SceneClassifier, GameScene
        self.scene_classifier = SceneClassifier(
            vision=self.logout_action.vision,
            login_templates=config.login_templates,
            logged_in_templates=config.logged_in_templates,
            home_events=config.home_events,
            out_game_title=config.out_game_title,
            out_game_confirm=config.out_game_confirm,
            sub_screen_close_templates=config.sub_screen_close_templates,
            threshold=config.threshold,
            logged_in_threshold=config.logged_in_threshold,
        )
        self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
        self.current: Account | None = None
        self._logged_in_hits = 0
        self._profile_update_closed = 0
        self._home_hits = 0
        self._home_target_done = False
        self._submit_attempts = 0
        self._last_submit_at = 0.0
        self._submit_transitioning = False
        self._active_game_day = self.runtime.game_day(datetime.now(TIMEZONE), self.runtime.reset_hour)
        port = self.device.serial.rsplit("-", 1)[-1]
        self._rolling_screenshot = Path.cwd() / "temp" / f"screenshot_multi_{port}.png"

    def ensure_game_active(self) -> None:
        """Launch the game only when another package owns the foreground."""
        foreground = self.input.shell("dumpsys", "window", "windows")
        if "com.daichien.mobile" not in foreground:
            self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
            sleep(3)

    @staticmethod
    def _plain_ocr(screen) -> str:
        import unicodedata
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        image = screen.data if hasattr(screen, "data") else (
            np.asarray(screen.convert("RGB")) if hasattr(screen, "convert") else np.asarray(screen)
        )
        result, _ = RapidOCR()(image)
        text = " ".join(str(row[1]) for row in (result or []))
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()

    def _exit_game_with_esc(self) -> bool:
        """Return False if ESC itself safely recovers HOME; True after confirmed exit."""
        if self.config.out_game_title is None or self.config.out_game_confirm is None:
            raise RuntimeError("Thiếu asset title/Xác nhận out_game")
        self.input.keyevent("KEYCODE_ESCAPE")
        screen = None
        title = None
        for _ in range(3):
            sleep(self.config.poll_seconds)
            screen = self._screen()
            detection = self.detector.detect(
                screen, login_templates=self.config.login_templates,
                logged_in_templates=self.config.logged_in_templates,
                threshold=self.config.threshold,
                logged_in_threshold=self.config.logged_in_threshold,
            )
            if detection.state == LoginScreenState.LOGGED_IN:
                __import__("logging").getLogger("dc3q").info(
                    "RECOVERY | ESC đã đưa về HOME; không out game"
                )
                return False
            title = self.logout_action.vision.find_template(
                screen, "out_game_title", self.config.out_game_title,
                self.config.out_game_threshold,
            ).match
            if title.found:
                break
        if title is None or not title.found:
            logger = __import__("logging").getLogger("dc3q")
            logger.warning(
                "RECOVERY | ESC thất bại sau 3 frame; force-stop riêng com.daichien.mobile"
            )
            self.input.shell("am", "force-stop", "com.daichien.mobile")
            sleep(self.config.poll_seconds)
            return True
        import numpy as np
        image = screen.data if hasattr(screen, "data") else (
            np.asarray(screen.convert("RGB")) if hasattr(screen, "convert") else np.asarray(screen)
        )
        split_x = image.shape[1] // 2
        confirm = self.logout_action.vision.find_template(
            image[:, split_x:], "out_game_confirm", self.config.out_game_confirm,
            self.config.out_game_confirm_threshold,
        ).match
        if not confirm.found:
            logger = __import__("logging").getLogger("dc3q")
            logger.warning(
                "RECOVERY | popup Thoát game thiếu Xác nhận; force-stop riêng com.daichien.mobile"
            )
            self.input.shell("am", "force-stop", "com.daichien.mobile")
            sleep(self.config.poll_seconds)
            return True
        self.input.tap(split_x + confirm.x + confirm.width // 2, confirm.y + confirm.height // 2)
        sleep(self.config.poll_seconds)
        return True

    def _restart_game_to_retained_home(self) -> None:
        logger = __import__("logging").getLogger("dc3q")
        for launch_number in (1, 2):
            if launch_number == 2:
                logger.warning("RECOVERY | lần mở đầu bị treo; out game rồi mở lại lần 2")
                if not self._exit_game_with_esc():
                    return
            self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
            home_hits = 0
            for _ in range(self.config.restart_wait_attempts):
                image = self._screen()
                detection = self.detector.detect(
                    image, login_templates=self.config.login_templates,
                    logged_in_templates=self.config.logged_in_templates,
                    threshold=self.config.threshold,
                    logged_in_threshold=self.config.logged_in_threshold,
                )
                if detection.state == LoginScreenState.LOGGED_IN:
                    home_hits += 1
                    if home_hits >= self.config.logged_in_confirmations:
                        logger.info("RECOVERY | game mở lại tại HOME tài khoản hiện tại")
                        return
                else:
                    home_hits = 0
                    if self.config.home_events:
                        for state_tpl, close_tpl, thresh in self.config.home_events:
                            r = self.home_action.vision.find_template(image, "home_event", state_tpl, thresh).match
                            if r.found:
                                cr = self.home_action.vision.find_template(image, "home_event_close", close_tpl, thresh).match
                                if cr.found:
                                    logger.info("RECOVERY | Đóng popup sự kiện trong lúc mở game")
                                    self.input.tap(cr.x + cr.width // 2, cr.y + cr.height // 2)
                                    break
                sleep(self.config.poll_seconds)
        raise RuntimeError("Mở game lại 2 lần nhưng chưa về HOME")

    def reconcile_existing_home(self) -> None:
        """Return a retained session to LOGIN before allocating acc_001."""
        self.scene_classifier.ensure_home(self._screen, self.input, max_steps=4)
        self.logout_action.logout(
            self._screen,
            templates=self.config.logout_templates,
            threshold=self.config.logout_threshold,
            max_attempts=self.config.logout_max_attempts,
            login_detector=self.detector,
            login_templates=self.config.login_templates,
            login_threshold=self.config.threshold,
        )

    def _screen(self):
        from app.vision.image import load_image
        image = load_image(self.screenshot.png_bytes())
        self._rolling_screenshot.parent.mkdir(parents=True, exist_ok=True)
        authentication = self.phase in {
            AccountLoginPhase.WAIT_LOGIN_SCREEN,
            AccountLoginPhase.LOGGING_IN,
        }
        temporary = self._rolling_screenshot.with_suffix(".tmp.png")
        redacted = redact_runtime_screenshot(image, authentication=authentication)
        if hasattr(redacted, "save"):
            redacted.save(temporary)
        else:
            import cv2
            cv2.imwrite(str(temporary), redacted)
        temporary.replace(self._rolling_screenshot)
        return image

    def _handle_known_home_event(self, image) -> bool:
        """Close one positively recognized safe random popup."""
        return self.home_action.handle_known_event(image)

    def _detect(self):
        image = self._screen()
        d = self.detector.detect(image, login_templates=self.config.login_templates,
                                 logged_in_templates=self.config.logged_in_templates,
                                 threshold=self.config.threshold,
                                 logged_in_threshold=self.config.logged_in_threshold)
        LOGGER = __import__("logging").getLogger("dc3q")
        if d.state == LoginScreenState.LOGGED_IN:
            from app.state.scene import GameScene, SceneResult
            scene_res = SceneResult(GameScene.HOME, "Màn hình chính HOME (Nội chính)", d.confidence)
        elif d.state == LoginScreenState.LOGIN_SCREEN:
            from app.state.scene import GameScene, SceneResult
            scene_res = SceneResult(GameScene.LOGIN_SCREEN, "Màn hình Đăng nhập", d.confidence)
        else:
            scene_res = self.scene_classifier.classify(image, self.input)
        LOGGER.info("SCREEN | device=%s | scene=%s (%s) | login_state=%s (conf=%.3f)",
                    self.device.serial, scene_res.scene.value, scene_res.detail, d.state.value, d.confidence)
        return image, d, scene_res

    def _retry_submit_if_stuck(self, state, now: float) -> bool:
        """Retry only an unchanged login form; bounded, never during another state."""
        state_value = state.value if hasattr(state, "value") else str(state)
        if state_value != LoginScreenState.LOGIN_SCREEN.value or self._submit_transitioning:
            return False
        if self._submit_attempts >= 5 or now - self._last_submit_at < 3.0:
            return False
        tapped = self.login_action.submit_current_form(
            self._screen, self.config.submit_template, self.config.control_threshold,
        )
        if not tapped:
            self._submit_transitioning = True
            __import__("logging").getLogger("dc3q").info(
                "LOGIN | nút Đăng nhập đã biến mất; dừng bấm, chờ chuyển trạng thái",
            )
            return False
        self._submit_attempts += 1
        self._last_submit_at = now
        __import__("logging").getLogger("dc3q").info(
            "LOGIN | bấm lại Đăng nhập | lần=%d/5", self._submit_attempts,
        )
        return True

    def _drain_daily_cutoff(self) -> None:
        logger = __import__("logging").getLogger("dc3q")
        logger.info("ROLLOVER | 22:59: dừng nghiệp vụ, recover HOME và đăng xuất")
        with self.input.allow_cutoff_actions():
            if self.current and self.phase == AccountLoginPhase.PROCESS_HOME_EVENTS:
                targets = self.config.home_targets or []
                index = self.home_action.target_index
                if index < len(targets):
                    recover = getattr(targets[index], "recover_home", None)
                    if recover is None or not recover():
                        raise RuntimeError("22:59: không recover được HOME; dừng an toàn")
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
            elif self.current and self.phase in {
                AccountLoginPhase.LOGGING_IN, AccountLoginPhase.LOGGING_OUT,
            }:
                # Không gửi lại login sau cutoff. Chỉ logout nếu phiên đã vào game;
                # logout state machine tự chấp nhận LOGIN là hậu điều kiện terminal.
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
        self.current = None
        self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
        self.home_action.reset()
        while in_daily_cutoff(datetime.now(TIMEZONE), self.config.cutoff_hour, self.config.cutoff_minute):
            sleep(1)
        now = datetime.now(TIMEZONE)
        self.runtime.maybe_rollover(now)
        loaded = self.accounts.reload(self.runtime.statuses())
        self._active_game_day = self.runtime.game_day(now, self.runtime.reset_hour)
        logger.info("ROLLOVER | queue ngày mới=%s", [account.id for account in loaded])

    def poll_once(self) -> AccountLoginPhase:
        self.runtime.maybe_rollover()
        detected = self._detect()
        if len(detected) == 3:
            image, d, scene_res = detected
        else:
            image, d = detected
            scene_res = self.scene_classifier.classify(image, self.input)

        from app.state.scene import GameScene
        if self.phase == AccountLoginPhase.WAIT_LOGIN_SCREEN:
            if scene_res.scene == GameScene.DESKTOP:
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.info("WAIT_LOGIN_SCREEN | Game không ở foreground; tự động mở lại com.daichien.mobile")
                self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
                sleep(2.0)
                return self.phase

            if scene_res.scene == GameScene.POPUP and scene_res.action_point is not None:
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.info("WAIT_LOGIN_SCREEN | Tự động đóng popup %s tại %s", scene_res.detail, scene_res.action_point)
                self.input.tap(*scene_res.action_point)
                sleep(1.0)
                return self.phase

            if scene_res.scene == GameScene.SUB_SCREEN and scene_res.action_point is not None:
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.info("WAIT_LOGIN_SCREEN | Tự động đóng màn hình con %s tại %s", scene_res.detail, scene_res.action_point)
                self.input.tap(*scene_res.action_point)
                sleep(1.0)
                return self.phase

            if self._handle_known_home_event(image):
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.info("WAIT_LOGIN_SCREEN | Đã đóng popup sự kiện ngẫu nhiên che khuất màn hình")
                sleep(1.0)
                return self.phase

            if d.state == LoginScreenState.LOGGED_IN:
                try:
                    self.reconcile_existing_home()
                except Exception as exc:
                    LOGGER = __import__("logging").getLogger("dc3q")
                    LOGGER.warning("WAIT_LOGIN_SCREEN | reconcile_existing_home thất bại: %s -> thử out game bằng ESC/force-stop", exc)
                    self._exit_game_with_esc()
                    sleep(2.0)
                    self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
                return self.phase
            if d.state == LoginScreenState.LOGIN_SCREEN:
                account = self.accounts.claim_next()
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
                    self._submit_attempts = 1
                    self._last_submit_at = monotonic()
                    self._submit_transitioning = False
                except Exception as exc:
                    LOGGER = __import__("logging").getLogger("dc3q")
                    LOGGER.error("LOGIN | Không thể điền thông tin đăng nhập tài khoản %s: %s", account.id, exc)
                    self.runtime.mark_error(account.id, self.device.serial, str(exc))
                    try:
                        self.accounts.skip_current(account.id)
                    except Exception:
                        pass
                    self.current = None
                    self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                    self._logged_in_hits = 0
                    return self.phase
            return self.phase

        if self.phase == AccountLoginPhase.LOGGING_IN:
            if d.state == LoginScreenState.LOGGED_IN:
                # HOME is proven only by the configured Chính vụ crop.
                self._logged_in_hits += 1
                if self._logged_in_hits >= self.config.logged_in_confirmations:
                    assert self.current
                    self.accounts.commit_logged_in(self.current.id)
                    self.runtime.mark_logged_in(self.current.id, self.device.serial)
                    row = self.runtime.statuses().get(self.current.id, {})
                    completed = set()
                    for target in self.config.home_targets or []:
                        task = getattr(target, "runtime_task", "")
                        field = self.runtime._normalize_task(task)
                        if field and row.get(field) in {"DONE", "ERROR"}:
                            completed.add(task)
                    self.home_action.set_completed_tasks(completed)
                    if self.home_action.target_done:
                        self.phase = (
                            AccountLoginPhase.LOGGING_OUT
                            if self.config.auto_logout
                            else AccountLoginPhase.WAIT_MANUAL_LOGOUT
                        )
                    else:
                        self.phase = AccountLoginPhase.PROCESS_HOME_EVENTS
                    return self.poll_once()

                return self.phase

            # Ưu tiên cặp title + nút đóng đã xác minh. UI XML thường thấy
            # title nhưng không expose nút X, không được kết luận bị chặn sớm.
            if self._handle_known_home_event(image):
                self._logged_in_hits = 0
                return self.phase
            try:
                unexpected, point = classify_login_ui(self.input.ui_xml())
            except Exception:
                unexpected, point = "unknown", None
            if unexpected == "credential_rejected":
                assert self.current
                message = "Máy chủ từ chối tài khoản hoặc mật khẩu"
                self.runtime.mark_error(self.current.id, self.device.serial, message)
                self.login_action.clear_login_form()
                self.accounts.skip_current(self.current.id)
                self.current = None
                self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                self._logged_in_hits = 0
                return self.phase
            if unexpected == "maintenance":
                assert self.current
                message = "Máy chủ đang bảo trì; dừng an toàn, không gửi lại đăng nhập"
                self.runtime.mark_error(self.current.id, self.device.serial, message)
                raise RuntimeError(message)
            if unexpected in {"operator_required", "profile_update_blocked"}:
                assert self.current
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.warning("LOGIN | Tài khoản %s yêu cầu can thiệp (%s) -> ghi nhận lỗi và chuyển tài khoản tiếp theo", self.current.id, unexpected)
                message = f"Cần người vận hành: {unexpected}"
                self.runtime.mark_error(self.current.id, self.device.serial, message)
                self.accounts.skip_current(self.current.id)
                self.current = None
                self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                self._logged_in_hits = 0
                return self.phase
            if unexpected == "profile_update_close" and point is not None:
                if self._profile_update_closed >= 3:
                    LOGGER = __import__("logging").getLogger("dc3q")
                    LOGGER.warning("LOGIN | Tài khoản %s popup cập nhật thông tin xuất hiện lại sau 3 lần đóng -> bỏ qua sang acc tiếp theo", self.current.id)
                    self.runtime.mark_error(self.current.id, self.device.serial, "Popup cập nhật thông tin xuất hiện lại")
                    self.accounts.skip_current(self.current.id)
                    self.current = None
                    self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                    self._logged_in_hits = 0
                    return self.phase
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.info("LOGIN | Đóng popup Cập nhật thông tin cá nhân lần %d tại %s", self._profile_update_closed + 1, point)
                self.input.tap(*point)
                sleep(1.0)
                self._profile_update_closed += 1
                self._logged_in_hits = 0
                return self.phase
            if self._handle_known_home_event(image):
                self._logged_in_hits = 0
                return self.phase
            if d.state == LoginScreenState.LOGIN_SCREEN:
                self._retry_submit_if_stuck(d.state, monotonic())
                self._logged_in_hits = 0
                return self.phase
            else:
                self._logged_in_hits = 0
            return self.phase

        if self.phase == AccountLoginPhase.PROCESS_HOME_EVENTS:
            assert self.current
            task_before = self.home_action.current_task
            self.runtime.mark_current_task(self.current.id, task_before)
            try:
                home_done = self.home_action.process(
                    image, logged_in=d.state == LoginScreenState.LOGGED_IN,
                )
                if self.home_action.current_task != task_before:
                    if self.home_action.last_task_error:
                        self.runtime.mark_task_error(
                            self.current.id, task_before,
                            f"home target error: {self.home_action.last_task_error}",
                        )
                        self.home_action.last_task_error = ""
                    else:
                        self.runtime.mark_task_done(self.current.id, task_before)
                self._home_target_done = self.home_action.target_done
                self._home_hits = self.home_action.confirmations
            except GameRestartRequired as exc:
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.warning(
                    "RECOVERY | task=%s lỗi đủ %d lần; xử lý phục hồi HOME để chạy tiếp các task còn lại",
                    exc.task, self.config.target_retry_limit,
                )
                self.runtime.mark_task_error(
                    self.current.id, exc.task, f"home target error: {exc}",
                )
                # 1. Thử dùng ensure_home trước để đóng popup / sub-screen
                at_home = False
                try:
                    at_home = self.scene_classifier.ensure_home(self._screen, self.input, max_steps=4)
                except Exception as ensure_err:
                    LOGGER.warning("RECOVERY | ensure_home gặp lỗi: %s", ensure_err)

                # 2. Nếu ensure_home không về được HOME thì mới ESC / restart game về HOME
                if not at_home:
                    exited = self._exit_game_with_esc()
                    if exited:
                        try:
                            self._restart_game_to_retained_home()
                            at_home = True
                        except Exception as restart_exc:
                            LOGGER.error("RECOVERY | không thể restart về HOME tài khoản %s: %s -> chuyển sang acc tiếp theo", self.current.id, restart_exc)
                            self.runtime.mark_error(self.current.id, self.device.serial, f"restart error: {restart_exc}", task=exc.task)
                            try:
                                self.reconcile_existing_home()
                            except Exception as recon_exc:
                                LOGGER.warning("RECOVERY | reconcile thất bại: %s", recon_exc)
                                try:
                                    self.input.shell("am", "force-stop", "com.daichien.mobile")
                                    sleep(1.0)
                                    self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
                                except Exception:
                                    pass
                            self.current = None
                            self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                            self.home_action.reset()
                            return self.phase

                # 3. Bỏ qua task lỗi hiện tại và chuyển sang task tiếp theo của tài khoản này
                self.home_action.continue_after_esc_home(exc.task)
                if self.home_action.target_done:
                    self.phase = (
                        AccountLoginPhase.LOGGING_OUT
                        if self.config.auto_logout
                        else AccountLoginPhase.WAIT_MANUAL_LOGOUT
                    )
                self.runtime.update(
                    self.current.id, status="LOGGED_IN", assigned_device=self.device.serial,
                    last_run=datetime.now(TIMEZONE).isoformat(timespec="seconds"),
                )
                return self.phase
            except Exception as exc:
                assert self.current
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.error("HOME | task=%s lỗi: %s -> ghi nhận và bỏ qua để chạy task tiếp theo", self.home_action.current_task, exc)
                task_failed = self.home_action.current_task
                self.runtime.mark_task_error(
                    self.current.id, task_failed, f"home target error: {exc}",
                )
                try:
                    self.scene_classifier.ensure_home(self._screen, self.input, max_steps=4)
                except Exception as ensure_err:
                    LOGGER.warning("HOME | ensure_home gặp lỗi: %s", ensure_err)
                self.home_action.last_task_error = ""
                self.home_action.target_index += 1
                self.home_action.recovery_attempts = 0
                self.home_action._skip_completed()
                if self.home_action.target_done:
                    self.phase = (
                        AccountLoginPhase.LOGGING_OUT
                        if self.config.auto_logout
                        else AccountLoginPhase.WAIT_MANUAL_LOGOUT
                    )
                self.runtime.update(
                    self.current.id, status="LOGGED_IN", assigned_device=self.device.serial,
                    last_run=datetime.now(TIMEZONE).isoformat(timespec="seconds"),
                )
                return self.phase
            if home_done or self.home_action.target_done:
                self.phase = (
                    AccountLoginPhase.LOGGING_OUT
                    if self.config.auto_logout
                    else AccountLoginPhase.WAIT_MANUAL_LOGOUT
                )
            return self.phase


        if self.phase == AccountLoginPhase.LOGGING_OUT:
            assert self.current
            self.runtime.mark_current_task(self.current.id, "LOGOUT")
            LOGGER = __import__("logging").getLogger("dc3q")
            LOGGER.info("Bắt đầu tự động đăng xuất tài khoản: %s", self.current.id)
            try:
                if self.config.save_knb_balance and self.config.knb_icon:
                    from app.vision.balance import read_balance_near_icon
                    if save_optional_knb(
                        read_balance_near_icon, self._screen(), self.config.knb_icon,
                        self.config.save_knb_balance, self.current.id,
                    ):
                        LOGGER.info("HOME | đã lưu KNB trước đăng xuất")
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
                self._home_target_done = False
                self.home_action.reset()
            except Exception as exc:
                LOGGER.error("Lỗi khi đăng xuất tài khoản %s: %s -> force restart game để chuyển tài khoản tiếp theo", self.current.id, exc)
                self.runtime.mark_error(self.current.id, self.device.serial, f"logout error: {exc}")
                try:
                    self.accounts.skip_current(self.current.id)
                except Exception:
                    pass
                try:
                    self.input.shell("am", "force-stop", "com.daichien.mobile")
                    sleep(2.0)
                    self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
                    sleep(3.0)
                except Exception as recovery_err:
                    LOGGER.warning("Lỗi khi force restart sau logout: %s", recovery_err)
                self.current = None
                self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                self._profile_update_closed = 0
                self._home_hits = 0
                self._home_target_done = False
                self.home_action.reset()
                return self.phase
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
        self.ensure_game_active()
        deadline = monotonic() + self.config.login_timeout_seconds
        while not (stop_event and stop_event.is_set()):
            if in_daily_cutoff(datetime.now(TIMEZONE), self.config.cutoff_hour, self.config.cutoff_minute):
                self._drain_daily_cutoff()
                continue
            before = self.phase
            try:
                self.poll_once()
            except DailyCutoff:
                self._drain_daily_cutoff()
                continue
            except Exception as fatal_poll_exc:
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.error("CỰC KỲ QUAN TRỌNG: Lỗi không mong muốn trong poll_once: %s", fatal_poll_exc, exc_info=True)
                if self.current:
                    self.runtime.mark_error(self.current.id, self.device.serial, f"fatal poll error: {fatal_poll_exc}")
                    try:
                        self.accounts.skip_current(self.current.id)
                    except Exception:
                        pass
                try:
                    self.input.shell("am", "force-stop", "com.daichien.mobile")
                    sleep(2.0)
                    self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
                    sleep(3.0)
                except Exception as r_err:
                    LOGGER.warning("Lỗi phục hồi app sau crash: %s", r_err)
                self.current = None
                self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                self._profile_update_closed = 0
                self._home_hits = 0
                self._home_target_done = False
                self.home_action.reset()
                deadline = monotonic() + self.config.login_timeout_seconds
                sleep(self.config.poll_seconds)
                continue
            if self.phase == AccountLoginPhase.EXHAUSTED:
                if not self.config.persistent_daily:
                    return
                sleep(self.config.poll_seconds)
                now = datetime.now(TIMEZONE)
                game_day = self.runtime.game_day(now, self.runtime.reset_hour)
                if game_day != self._active_game_day:
                    self.runtime.maybe_rollover(now)
                    loaded = self.accounts.reload(self.runtime.statuses())
                    self._active_game_day = game_day
                    if loaded:
                        self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                continue
            if before == AccountLoginPhase.LOGGING_IN and self.phase == AccountLoginPhase.LOGGING_IN and monotonic() > deadline:
                LOGGER = __import__("logging").getLogger("dc3q")
                LOGGER.error("Hết thời gian chờ đăng nhập tài khoản: %s -> Bỏ qua và chuyển tài khoản tiếp theo", self.current.id if self.current else "None")
                if self.current:
                    self.runtime.mark_error(self.current.id, self.device.serial, "login timeout")
                    try:
                        self.accounts.skip_current(self.current.id)
                    except Exception:
                        pass
                try:
                    self.input.shell("am", "force-stop", "com.daichien.mobile")
                    sleep(2.0)
                    self.input.shell("monkey", "-p", "com.daichien.mobile", "1")
                    sleep(3.0)
                except Exception as r_err:
                    LOGGER.warning("Lỗi phục hồi app sau login timeout: %s", r_err)
                self.current = None
                self.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
                self._profile_update_closed = 0
                self._home_hits = 0
                self._home_target_done = False
                self.home_action.reset()
                deadline = monotonic() + self.config.login_timeout_seconds
                sleep(self.config.poll_seconds)
                continue
            if self.phase not in (AccountLoginPhase.LOGGING_IN, AccountLoginPhase.LOGGING_OUT):
                deadline = monotonic() + self.config.login_timeout_seconds
                self._logged_in_hits = 0
            sleep(self.config.poll_seconds)
