from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

LOGGER = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")


class ActionContext(Protocol):
    device: Any
    vision: Any
    variables: dict[str, Any]
    stop_event: Any


class ActionStopRequested(RuntimeError):
    """Raised when Ctrl+C/worker shutdown interrupts an action wait."""


@dataclass(slots=True)
class ActionResult:
    success: bool
    action: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success


ActionHandler = Callable[[ActionContext, dict[str, Any]], ActionResult]


def _lookup_variable(variables: Mapping[str, Any], path: str) -> Any:
    current: Any = variables
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def resolve_value(value: Any, variables: Mapping[str, Any]) -> Any:
    """Resolve ${variable} placeholders recursively while preserving native types."""
    if isinstance(value, str):
        full = _VAR_PATTERN.fullmatch(value)
        if full:
            try:
                return _lookup_variable(variables, full.group(1))
            except KeyError:
                return value

        def repl(match: re.Match[str]) -> str:
            try:
                resolved = _lookup_variable(variables, match.group(1))
            except KeyError:
                return match.group(0)
            return str(resolved)

        return _VAR_PATTERN.sub(repl, value)

    if isinstance(value, list):
        return [resolve_value(item, variables) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve_value(item, variables) for item in value)
    if isinstance(value, dict):
        return {key: resolve_value(item, variables) for key, item in value.items()}
    return value


def _require(params: dict[str, Any], key: str) -> Any:
    if key not in params:
        raise ValueError(f"Missing required action parameter: {key}")
    return params[key]


def _call_first(obj: Any, method_names: tuple[str, ...], *args, **kwargs) -> Any:
    last_type_error: TypeError | None = None
    for name in method_names:
        method = getattr(obj, name, None)
        if not callable(method):
            continue
        try:
            return method(*args, **kwargs)
        except TypeError as exc:
            last_type_error = exc
    if last_type_error is not None:
        raise last_type_error
    raise AttributeError(f"None of these methods exist: {', '.join(method_names)}")


def _stop_requested(context: ActionContext) -> bool:
    event = getattr(context, "stop_event", None)
    return bool(event is not None and callable(getattr(event, "is_set", None)) and event.is_set())


def _wait_interruptibly(context: ActionContext, seconds: float) -> None:
    """Sleep without making Ctrl+C wait for the full action delay."""
    delay = max(0.0, float(seconds))
    event = getattr(context, "stop_event", None)
    if event is not None and callable(getattr(event, "wait", None)):
        if event.wait(delay):
            raise ActionStopRequested("Stop requested")
        return
    time.sleep(delay)


class ActionRegistry:
    """Registry of automation actions. No subprocess/OpenCV logic belongs here."""

    def __init__(self, register_defaults: bool = True) -> None:
        self._handlers: dict[str, ActionHandler] = {}
        if register_defaults:
            self._register_defaults()

    def register(self, name: str, handler: ActionHandler, *, replace: bool = False) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("Action name cannot be empty")
        if key in self._handlers and not replace:
            raise KeyError(f"Action already registered: {name}")
        self._handlers[key] = handler

    def has(self, name: str) -> bool:
        return name.strip().lower() in self._handlers

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def execute(self, context: ActionContext, spec: str | Mapping[str, Any]) -> ActionResult:
        if _stop_requested(context):
            raise ActionStopRequested("Stop requested")
        if isinstance(spec, str):
            name = spec
            params: dict[str, Any] = {}
        elif isinstance(spec, Mapping):
            raw = dict(spec)
            name = str(raw.pop("action", raw.pop("type", raw.pop("name", "")))).strip()
            if not name:
                raise ValueError(f"Action specification has no action/type/name: {spec!r}")
            params = raw
        else:
            raise TypeError(f"Unsupported action specification: {type(spec)!r}")

        key = name.lower()
        handler = self._handlers.get(key)
        if handler is None:
            raise KeyError(f"Unknown action: {name}")

        params = resolve_value(params, context.variables)
        result = handler(context, params)
        if not isinstance(result, ActionResult):
            raise TypeError(f"Action handler {name} returned {type(result)!r}, expected ActionResult")
        return result

    def _register_defaults(self) -> None:
        defaults: dict[str, ActionHandler] = {
            "tap": self._tap,
            "click": self._tap,
            "swipe": self._swipe,
            "input_text": self._input_text,
            "clear_text": self._clear_text,
            "ensure_login_screen": self._ensure_login_screen,
            "login_credentials": self._login_credentials,
            "finish_login": self._finish_login,
            "handle_random_server_events": self._handle_random_server_events,
            "logout_account": self._logout_account,
            "reset_day_logout": self._reset_day_logout,
            "prepare_account_session": self._prepare_account_session,
            "set_workflow_step": self._set_workflow_step,
            "complete_account_flow": self._complete_account_flow,
            "tam_quoc_lenh": self._tam_quoc_lenh,
            "phuc_loi": self._phuc_loi,
            "keyevent": self._keyevent,
            "back": self._back,
            "home": self._home,
            "sleep": self._sleep,
            "wait": self._sleep,
            "start_app": self._start_app,
            "stop_app": self._stop_app,
            "tap_template": self._tap_template,
            "tap_yolo": self._tap_yolo,
            "set_variable": self._set_variable,
            "delete_variable": self._delete_variable,
            "log": self._log,
        }
        for name, handler in defaults.items():
            self.register(name, handler)

    @staticmethod
    def _tap(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        x = int(_require(params, "x"))
        y = int(_require(params, "y"))
        context.device.tap(x, y)
        return ActionResult(True, "tap", data={"x": x, "y": y})

    @staticmethod
    def _swipe(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        x1 = int(_require(params, "x1"))
        y1 = int(_require(params, "y1"))
        x2 = int(_require(params, "x2"))
        y2 = int(_require(params, "y2"))
        duration_ms = int(params.get("duration_ms", params.get("duration", 300)))
        context.device.swipe(x1, y1, x2, y2, duration_ms)
        return ActionResult(
            True,
            "swipe",
            data={"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration_ms": duration_ms},
        )

    @staticmethod
    def _input_text(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        text = str(_require(params, "text"))
        context.device.input_text(text)
        return ActionResult(True, "input_text", data={"text_length": len(text)})

    @staticmethod
    def _clear_text(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        max_characters = int(params.get("max_characters", 128))
        context.device.clear_text(max_characters=max_characters)
        return ActionResult(True, "clear_text", data={"max_characters": max_characters})

    @staticmethod
    def _ensure_login_screen(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Reuse AuthenActivity; launch once only when the game is not running."""
        package = str(_require(params, "package"))
        activity = str(params.get("activity", "com.qtz.game.main.Logo"))
        login_activity = str(params.get(
            "login_activity", "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"
        ))
        timeout = max(1.0, float(params.get("timeout", 120.0)))
        interval = max(0.05, float(params.get("interval", 1.0)))
        current = context.device.get_current_activity()
        if current == login_activity:
            return ActionResult(True, "ensure_login_screen", "Authentication Activity already visible")

        if not current.startswith(package + "/"):
            _call_first(context.device, ("start_app", "launch_app"), package, activity)

        deadline = time.monotonic() + timeout
        while time.monotonic() <= deadline:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            if context.device.get_current_activity() == login_activity:
                return ActionResult(True, "ensure_login_screen", "Authentication Activity ready")
            time.sleep(interval)
        return ActionResult(False, "ensure_login_screen", "Authentication Activity did not appear")

    @staticmethod
    def _login_credentials(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Wait for the real SDK auth Activity, then type and submit via ADB."""
        username = str(_require(params, "username"))
        password = str(_require(params, "password"))
        if not username or not password:
            raise ValueError("login_credentials requires non-empty username/password")

        timeout = max(1.0, float(params.get("timeout", 120.0)))
        interval = max(0.2, float(params.get("interval", 1.0)))
        deadline = time.monotonic() + timeout
        expected_activity = str(
            params.get("activity", "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity")
        )
        while time.monotonic() <= deadline:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            if context.device.get_current_activity() == expected_activity:
                break
            time.sleep(interval)
        else:
            return ActionResult(False, "login_credentials", "Authentication Activity did not appear")

        width, height = context.device.get_screen_size()
        ratios = (
            (float(params.get("username_x_ratio", 0.500)), float(params.get("username_y_ratio", 0.352))),
            (float(params.get("password_x_ratio", 0.500)), float(params.get("password_y_ratio", 0.439))),
            (float(params.get("submit_x_ratio", 0.500)), float(params.get("submit_y_ratio", 0.567))),
        )
        if any(not 0.0 <= value <= 1.0 for pair in ratios for value in pair):
            raise ValueError("login coordinate ratios must be between 0 and 1")

        points = [(int(round(x * width)), int(round(y * height))) for x, y in ratios]
        max_characters = int(params.get("max_characters", 128))
        field_delay = max(0.0, float(params.get("field_delay", 0.5)))

        context.device.tap(*points[0])
        time.sleep(field_delay)
        context.device.clear_text(max_characters=max_characters)
        context.device.input_text(username)
        context.device.tap(*points[1])
        time.sleep(field_delay)
        context.device.clear_text(max_characters=max_characters)
        context.device.input_text(password)
        context.device.tap(*points[2])
        return ActionResult(True, "login_credentials", "Credentials submitted")

    @staticmethod
    def _template(context: ActionContext, path: str, threshold: float = 0.80):
        return context.vision.find_template(path, threshold=threshold, refresh=True)

    @staticmethod
    def _profile_update_close_center(context: ActionContext) -> tuple[int, int] | None:
        """Read only a fresh SDK accessibility dump; reject stale/error output."""
        remote = "/sdcard/__dc3q_profile_update.xml"
        try:
            context.device.shell("rm", "-f", remote, check=False)
            output = context.device.shell("uiautomator", "dump", remote, timeout=15, check=False)
            if "dumped to" not in output.lower() or "error:" in output.lower():
                return None
            xml = context.device.shell("cat", remote, timeout=10)
            root = ET.fromstring(xml)
        except Exception:
            return None

        nodes = list(root.iter("node"))
        texts = " ".join(
            (node.attrib.get("text", "") + " " + node.attrib.get("content-desc", "")).casefold()
            for node in nodes
        )
        if "cập nhật thông tin" not in texts:
            return None
        candidates = [
            node for node in nodes
            if node.attrib.get("text", "").strip().casefold() in {"x", "×", "đóng", "thoát"}
            or node.attrib.get("content-desc", "").strip().casefold() in {"x", "×", "đóng", "thoát", "close"}
        ]
        for node in candidates:
            values = [int(value) for value in re.findall(r"\d+", node.attrib.get("bounds", ""))]
            if len(values) == 4:
                return (values[0] + values[2]) // 2, (values[1] + values[3]) // 2
        return None

    @staticmethod
    def _finish_login(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Close only a freshly verified SDK profile-update X; require stable HOME."""
        timeout = max(1.0, float(params.get("timeout", 180.0)))
        interval = max(0.05, float(params.get("interval", 1.0)))
        stable_required = max(1, int(params.get("stable_frames", 3)))
        home = str(params.get("home_template", "dc3q/common/home_marker_noi_chinh.png"))
        stable = 0
        closed = 0
        deadline = time.monotonic() + timeout

        event_templates = (
            "dc3q/random-events/red-envelope/screen/screen_open_button.png",
            "dc3q/random-events/red-envelope/screen/screen_close_prompt.png",
            "dc3q/random-events/red-envelope/screen/screen_tap_blank_to_close.png",
        )
        handled_events = 0
        enemy_dialog = "dc3q/random-events/enemy-raid/full_screen_enemy_raid_event_dialog.png"
        enemy_close = "dc3q/random-events/enemy-raid/screen_enemy_raid_close_button.png"
        while time.monotonic() <= deadline:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            close_center = ActionRegistry._profile_update_close_center(context)
            if close_center is not None:
                context.device.tap(*close_center)
                closed += 1
                stable = 0
                time.sleep(interval)
                continue
            profile_title = ActionRegistry._template(
                context,
                "dc3q/random-events/profile-update/screen_profile_update_title.png",
                0.92,
            )
            if profile_title is not None:
                profile_close = ActionRegistry._template(
                    context,
                    "dc3q/random-events/profile-update/screen_profile_update_close.png",
                    0.92,
                )
                if profile_close is None:
                    return ActionResult(False, "finish_login", "Profile update visible but close X not verified")
                context.device.tap(*profile_close.center)
                closed += 1
                stable = 0
                time.sleep(interval)
                continue
            if ActionRegistry._template(context, enemy_dialog, 0.82) is not None:
                close_match = ActionRegistry._template(context, enemy_close, 0.82)
                if close_match is None:
                    return ActionResult(False, "finish_login", "Enemy raid visible but close button not verified")
                context.device.tap(*close_match.center)
                handled_events += 1
                stable = 0
                time.sleep(interval)
                continue
            event_match = next(
                (
                    match
                    for template in event_templates
                    if (match := ActionRegistry._template(context, template, 0.82)) is not None
                ),
                None,
            )
            if event_match is not None:
                context.device.tap(*event_match.center)
                handled_events += 1
                stable = 0
                time.sleep(interval)
                continue
            if ActionRegistry._template(context, home, float(params.get("home_threshold", 0.75))) is not None:
                stable += 1
                if stable >= stable_required:
                    return ActionResult(
                        True,
                        "finish_login",
                        "Stable HOME",
                        {"profile_update_closed": closed, "server_events_handled": handled_events},
                    )
            else:
                stable = 0
            time.sleep(interval)
        return ActionResult(False, "finish_login", "HOME not reached; unknown overlay left untouched")

    @staticmethod
    def _handle_random_server_events(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Handle known optional server events; absence is normal."""
        timeout = max(0.0, float(params.get("timeout", 20.0)))
        interval = max(0.05, float(params.get("interval", 0.5)))
        quiet_required = max(1, int(params.get("quiet_frames", 2)))
        threshold = float(params.get("threshold", 0.82))
        handlers = (
            "dc3q/random-events/red-envelope/screen/screen_open_button.png",
            "dc3q/random-events/red-envelope/screen/screen_close_prompt.png",
            "dc3q/random-events/red-envelope/screen/screen_tap_blank_to_close.png",
        )
        handled = 0
        quiet = 0
        deadline = time.monotonic() + timeout

        enemy_dialog = "dc3q/random-events/enemy-raid/full_screen_enemy_raid_event_dialog.png"
        enemy_close = "dc3q/random-events/enemy-raid/screen_enemy_raid_close_button.png"
        while time.monotonic() <= deadline:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            dialog_match = ActionRegistry._template(context, enemy_dialog, threshold)
            if dialog_match is not None:
                close_match = ActionRegistry._template(context, enemy_close, threshold)
                if close_match is None:
                    return ActionResult(False, "handle_random_server_events", "Enemy raid visible but close button not verified")
                context.device.tap(*close_match.center)
                handled += 1
                quiet = 0
                time.sleep(interval)
                continue
            for template in handlers:
                match = ActionRegistry._template(context, template, threshold)
                if match is not None:
                    context.device.tap(*match.center)
                    handled += 1
                    quiet = 0
                    time.sleep(interval)
                    break
            else:
                quiet += 1
                if quiet >= quiet_required:
                    return ActionResult(True, "handle_random_server_events", data={"handled": handled})
                time.sleep(interval)
        return ActionResult(False, "handle_random_server_events", "Known event did not settle before timeout")

    @staticmethod
    def _logout_account(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Verified HOME/profile/settings/change-account logout at 960x540 ratios."""
        login_activity = str(params.get(
            "login_activity", "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"
        ))
        if context.device.get_current_activity() == login_activity:
            return ActionResult(True, "logout_account", "Already logged out")

        timeout = max(1.0, float(params.get("timeout", 30.0)))
        interval = max(0.05, float(params.get("interval", 0.5)))
        threshold = float(params.get("threshold", 0.75))
        width, height = context.device.get_screen_size()

        def point(x: int, y: int) -> tuple[int, int]:
            return int(round(x / 960 * width)), int(round(y / 540 * height))

        transitions = (
            (
                "dc3q/targets/Đăng-Xuất/screen/screen_my_info_title_bar.png",
                "dc3q/targets/Đăng-Xuất/screen/screen_options_icon.png",
                None,
            ),
            (
                "dc3q/targets/Đăng-Xuất/screen/screen_options_title_bar.png",
                "dc3q/targets/Đăng-Xuất/screen/screen_user_settings_button.png",
                None,
            ),
            (
                "dc3q/targets/Đăng-Xuất/screen/screen_change_account_button.png",
                "dc3q/targets/Đăng-Xuất/screen/screen_change_account_button.png",
                None,
            ),
            (
                "dc3q/targets/Đăng-Xuất/screen/screen_change_account_title_bar.png",
                "dc3q/targets/Đăng-Xuất/screen/screen_confirm_button.png",
                None,
            ),
        )

        for index, (marker, target, coordinate) in enumerate(transitions):
            deadline = time.monotonic() + timeout
            match = None
            while time.monotonic() <= deadline:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")
                match = ActionRegistry._template(context, marker, threshold)
                if match is not None:
                    break
                if index == 0:
                    context.device.tap(*point(29, 37))
                time.sleep(interval)
            if match is None:
                return ActionResult(False, "logout_account", f"Logout state not verified: {marker}")

            if target:
                target_match = ActionRegistry._template(context, target, threshold)
                if target_match is None:
                    return ActionResult(False, "logout_account", f"Logout control not verified: {target}")
                context.device.tap(*target_match.center)
            else:
                assert coordinate is not None
                context.device.tap(*coordinate)
        deadline = time.monotonic() + max(timeout, 60.0)
        while time.monotonic() <= deadline:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            if context.device.get_current_activity() == login_activity:
                return ActionResult(True, "logout_account", "Returned to authentication Activity")
            time.sleep(interval)
        return ActionResult(False, "logout_account", "Confirmed change account but login Activity did not appear")

    @staticmethod
    def _workflow_defaults() -> dict[str, Any]:
        return {
            "status": "NOT_STARTED",
            "current_step": "LOGIN",
            "session_state": "LOGGED_OUT",
            "device_serial": None,
            "last_screen": None,
            "resume_count": 0,
            "last_error": None,
            "updated_at": None,
        }

    @staticmethod
    def _read_workflow_runtime(runtime_file, account_id: str):
        import json
        from pathlib import Path

        path = Path(runtime_file)
        if not path.is_file():
            raise FileNotFoundError(f"Runtime file not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        for row in raw.get("accounts", []):
            if isinstance(row, dict) and str(row.get("id")) == str(account_id):
                tasks = row.setdefault("tasks", {})
                workflow = tasks.setdefault("workflow", {})
                for key, value in ActionRegistry._workflow_defaults().items():
                    workflow.setdefault(key, value)
                return path, raw, row, workflow
        raise KeyError(f"Runtime account not found: {account_id}")

    @staticmethod
    def _write_workflow_runtime(path, raw: dict[str, Any]) -> None:
        import json

        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _derive_next_workflow_step(row: dict[str, Any]) -> str:
        tasks = row.get("tasks") if isinstance(row.get("tasks"), dict) else {}
        phuc_loi = tasks.get("phuc_loi") if isinstance(tasks.get("phuc_loi"), dict) else {}
        tam_quoc = tasks.get("tam_quoc_lenh") if isinstance(tasks.get("tam_quoc_lenh"), dict) else {}

        # Luồng cấp account cố định:
        # LOGIN -> TAM_QUOC_LENH -> PHUC_LOI -> LOGOUT.
        # Điểm danh chỉ là một task con bên trong PHUC_LOI, không phải bước
        # workflow độc lập. Tiến độ diem_danh vẫn được lưu để resume nội bộ
        # khi Phúc lợi bị gián đoạn.
        if tam_quoc.get("status") != "DONE":
            return "TAM_QUOC_LENH"
        if phuc_loi.get("status") != "DONE_FOR_NOW":
            return "PHUC_LOI"
        return "LOGOUT"

    @staticmethod
    def _detect_account_screen(context: ActionContext, *, package: str, login_activity: str) -> str:
        try:
            activity = str(context.device.get_current_activity() or "")
        except Exception:
            activity = ""

        if activity == login_activity:
            return "AUTH"

        def seen(path: str, threshold: float) -> bool:
            try:
                return ActionRegistry._template(context, path, threshold) is not None
            except Exception:
                return False

        # Marker đặc thù được kiểm tra trước marker chung để log đúng màn hình nhất.
        if seen(
            "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/Điểm-Danh/screen_diem_danh_page_marker.png",
            0.78,
        ):
            return "DIEM_DANH"
        if seen("dc3q/targets/Tam-Quốc-Lệnh/screen/tam_quoc_lenh_close_button.png", 0.82):
            return "TAM_QUOC_LENH"
        if seen("dc3q/targets/Hoạt-Động/screen/phuc_loi_selected.png", 0.76):
            return "PHUC_LOI"
        if seen("dc3q/common/home_marker_noi_chinh.png", 0.72):
            return "HOME"
        if seen("dc3q/targets/Hoạt-Động/screen/event_panel_close_button.png", 0.84):
            return "ACTIVITY_PANEL"
        if activity.startswith(package + "/"):
            return "IN_GAME_UNKNOWN"
        return "OTHER"

    @staticmethod
    def _prepare_account_session(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """
        Tự xác định có thể resume account đang đăng nhập hay phải đăng nhập lại.

        Nguyên tắc an toàn:
        - chỉ resume khi runtime chứng minh session ACTIVE thuộc đúng device hiện tại;
        - nếu session hiện tại không được chứng minh thuộc account đang claim, bot tự
          đưa game về HOME -> đăng xuất -> đăng nhập đúng account, không yêu cầu người dùng;
        - nếu lần trước dừng giữa màn hình lạ/popup, force-stop/start chính app để
          chuẩn hóa lại HOME nhưng không đăng xuất session hợp lệ;
        - bước tiếp theo luôn được suy ra lại từ runtime task, không tin mù current_task.
        """
        from datetime import datetime

        account_id = str(_require(params, "account_id"))
        username = str(_require(params, "username"))
        password = str(_require(params, "password"))
        runtime_file = str(_require(params, "runtime_file"))
        package = str(params.get("package", "com.daichien.mobile"))
        activity = str(params.get("activity", "com.qtz.game.main.Logo"))
        login_activity = str(params.get(
            "login_activity", "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"
        ))
        interval = max(0.1, float(params.get("interval", 1.0)))
        restart_delay = max(0.2, float(params.get("restart_delay", 1.0)))
        home_timeout = max(10.0, float(params.get("home_timeout", 180.0)))
        logout_timeout = max(10.0, float(params.get("logout_timeout", 60.0)))

        path, raw, row, workflow = ActionRegistry._read_workflow_runtime(runtime_file, account_id)
        next_step = ActionRegistry._derive_next_workflow_step(row)
        serial = str(getattr(context.device, "serial", "") or "")
        detected = ActionRegistry._detect_account_screen(
            context, package=package, login_activity=login_activity
        )

        def persist(*, error: str | None = None) -> None:
            workflow["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            workflow["last_error"] = error
            workflow["current_step"] = next_step
            row["current_task"] = None if next_step == "DONE" else next_step
            row["last_run"] = workflow["updated_at"]
            ActionRegistry._write_workflow_runtime(path, raw)

        def login_current_account() -> tuple[bool, str]:
            current = str(context.device.get_current_activity() or "")
            if current != login_activity:
                normalized = ActionRegistry._reset_day_logout(context, {
                    "package": package,
                    "activity": activity,
                    "login_activity": login_activity,
                    "restart_delay": restart_delay,
                    "home_timeout": home_timeout,
                    "logout_timeout": logout_timeout,
                    "interval": interval,
                })
                if not normalized.success:
                    return False, normalized.message

            submitted = ActionRegistry._login_credentials(context, {
                "username": username,
                "password": password,
                "activity": login_activity,
                "timeout": max(30.0, float(params.get("login_timeout", 120.0))),
                "interval": interval,
            })
            if not submitted.success:
                return False, submitted.message

            ready = ActionRegistry._finish_login(context, {
                "timeout": home_timeout,
                "interval": interval,
                "stable_frames": int(params.get("stable_frames", 2)),
                "home_threshold": float(params.get("home_threshold", 0.75)),
            })
            if not ready.success:
                return False, ready.message
            return True, "Logged in and reached stable HOME"

        def normalize_active_session() -> tuple[bool, str]:
            nonlocal detected
            if detected == "HOME":
                return True, "Already at HOME"

            # Không bấm Back mù từ popup/màn hình dở. Khởi động lại app chỉ để
            # quay về bề mặt ổn định; session game vẫn được giữ nếu còn hợp lệ.
            context.device.stop_app(package)
            _wait_interruptibly(context, restart_delay)
            context.device.start_app(package, activity)
            _wait_interruptibly(context, interval)

            if str(context.device.get_current_activity() or "") == login_activity:
                return False, "SESSION_EXPIRED"

            ready = ActionRegistry._finish_login(context, {
                "timeout": home_timeout,
                "interval": interval,
                "stable_frames": int(params.get("stable_frames", 2)),
                "home_threshold": float(params.get("home_threshold", 0.75)),
            })
            if not ready.success:
                return False, ready.message
            detected = "HOME"
            return True, "Resumed session and normalized to HOME"

        same_session = (
            workflow.get("session_state") == "ACTIVE"
            and bool(serial)
            and str(workflow.get("device_serial") or "") == serial
            and workflow.get("status") != "DONE"
        )

        workflow["status"] = "IN_PROGRESS"
        workflow["last_screen"] = detected
        workflow["current_step"] = next_step
        persist(error=None)

        try:
            mode = "LOGIN"
            if detected == "AUTH":
                ok, detail = login_current_account()
            elif same_session:
                mode = "RESUME"
                workflow["resume_count"] = int(workflow.get("resume_count", 0) or 0) + 1
                ok, detail = normalize_active_session()
                if not ok and detail == "SESSION_EXPIRED":
                    mode = "RELOGIN"
                    ok, detail = login_current_account()
            else:
                # Có game đang đăng nhập nhưng runtime không chứng minh đó là đúng
                # account/device. Tự đăng xuất session cũ rồi đăng nhập account claim.
                mode = "RELOGIN" if detected != "AUTH" else "LOGIN"
                ok, detail = login_current_account()

            if not ok:
                workflow["status"] = "PARTIAL"
                workflow["session_state"] = "UNKNOWN"
                workflow["last_screen"] = ActionRegistry._detect_account_screen(
                    context, package=package, login_activity=login_activity
                )
                persist(error=detail)
                return ActionResult(False, "prepare_account_session", detail, dict(workflow))

            workflow["session_state"] = "ACTIVE"
            workflow["device_serial"] = serial or workflow.get("device_serial")
            workflow["last_screen"] = "HOME"
            workflow["status"] = "IN_PROGRESS"
            persist(error=None)
            context.variables["workflow_mode"] = mode
            context.variables["workflow_next_step"] = next_step
            LOGGER.info(
                "[%s] session prepared: mode=%s detected=%s next_step=%s device=%s",
                account_id, mode, detected, next_step, serial or "unknown",
            )
            return ActionResult(
                True,
                "prepare_account_session",
                f"{mode}: next={next_step}",
                {"mode": mode, "next_step": next_step, "screen": detected},
            )
        except ActionStopRequested:
            workflow["status"] = "PARTIAL"
            workflow["session_state"] = "UNKNOWN"
            persist(error="Stop requested")
            raise
        except Exception as exc:
            workflow["status"] = "PARTIAL"
            workflow["session_state"] = "UNKNOWN"
            workflow["last_screen"] = ActionRegistry._detect_account_screen(
                context, package=package, login_activity=login_activity
            )
            persist(error=str(exc))
            return ActionResult(False, "prepare_account_session", str(exc), dict(workflow))

    @staticmethod
    def _set_workflow_step(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        from datetime import datetime

        account_id = str(_require(params, "account_id"))
        runtime_file = str(_require(params, "runtime_file"))
        requested_step = str(_require(params, "step")).strip().upper()
        path, raw, row, workflow = ActionRegistry._read_workflow_runtime(runtime_file, account_id)

        # Không tin mù bước được manager yêu cầu. Bước workflow thực tế luôn
        # được suy ra từ runtime để khi process khởi động lại có thể tiếp tục
        # đúng tại TAM_QUOC_LENH / PHUC_LOI / LOGOUT mà không chạy lùi.
        derived_step = ActionRegistry._derive_next_workflow_step(row)
        effective_step = derived_step
        workflow["status"] = "IN_PROGRESS"
        workflow["current_step"] = effective_step
        workflow["last_error"] = None
        workflow["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        row["current_task"] = effective_step
        row["last_run"] = workflow["updated_at"]
        ActionRegistry._write_workflow_runtime(path, raw)
        context.variables["workflow_next_step"] = effective_step
        return ActionResult(
            True,
            "set_workflow_step",
            f"Current workflow step: {effective_step} (requested={requested_step})",
            dict(workflow),
        )

    @staticmethod
    def _complete_account_flow(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        from datetime import datetime

        account_id = str(_require(params, "account_id"))
        runtime_file = str(_require(params, "runtime_file"))
        login_activity = str(params.get(
            "login_activity", "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"
        ))
        path, raw, row, workflow = ActionRegistry._read_workflow_runtime(runtime_file, account_id)

        current_activity = str(context.device.get_current_activity() or "")
        if current_activity != login_activity:
            workflow["status"] = "PARTIAL"
            workflow["current_step"] = "LOGOUT"
            workflow["session_state"] = "UNKNOWN"
            workflow["last_screen"] = "IN_GAME_UNKNOWN"
            workflow["last_error"] = "Logout postcondition not verified"
            workflow["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            row["current_task"] = "LOGOUT"
            ActionRegistry._write_workflow_runtime(path, raw)
            return ActionResult(False, "complete_account_flow", "Logout postcondition not verified")

        workflow["status"] = "DONE"
        workflow["current_step"] = "DONE"
        workflow["session_state"] = "LOGGED_OUT"
        workflow["last_screen"] = "AUTH"
        workflow["last_error"] = None
        workflow["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        row["current_task"] = None
        row["last_run"] = workflow["updated_at"]
        ActionRegistry._write_workflow_runtime(path, raw)
        return ActionResult(True, "complete_account_flow", "Workflow completed and account logged out", dict(workflow))

    @staticmethod
    def _tam_quoc_lenh(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """
        Complete the two daily free Tam Quốc Lệnh actions robustly.

        Design goals:
        - tolerate the HOME event icon moving horizontally between accounts;
        - tolerate normal/alert/active/inactive tab variants;
        - wait for UI transitions instead of sampling only one frame;
        - use the existing real screenshots/templates as state markers;
        - resume safely after partial progress or an interrupted reward popup;
        - never tap the paid 99/100 buttons;
        - preserve Ctrl+C responsiveness through interruptible waits.
        """
        import json
        from datetime import datetime
        from pathlib import Path

        account_id = str(_require(params, "account_id"))
        runtime_file = Path(str(_require(params, "runtime_file")))

        # Control/template thresholds. Entry is intentionally a little lower because
        # its appearance varies more between HOME layouts; all important action
        # buttons remain at the stricter threshold.
        threshold = float(params.get("threshold", 0.92))
        entry_threshold = float(params.get("entry_threshold", min(threshold, 0.88)))
        tab_threshold = float(params.get("tab_threshold", min(threshold, 0.90)))
        reward_threshold = float(params.get("reward_threshold", min(threshold, 0.90)))
        close_threshold = float(params.get("close_threshold", min(threshold, 0.90)))
        home_threshold = float(params.get("home_threshold", 0.75))

        timeout = max(1.0, float(params.get("timeout", 30.0)))
        open_timeout = max(2.0, float(params.get("open_timeout", 12.0)))
        state_timeout = max(2.0, float(params.get("state_timeout", 10.0)))
        interval = max(0.05, float(params.get("interval", 0.5)))

        base = "dc3q/targets/Tam-Quốc-Lệnh/screen/"
        home = "dc3q/common/home_marker_noi_chinh.png"

        # Current production templates.
        entry_templates = (
            base + "home_tam_quoc_lenh_entry.png",
            base + "home_tam_quoc_lenh_entry_alert.png",
        )
        que_tabs = (
            base + "que_boi_tab_alert_active.png",
            base + "que_boi_tab_alert_inactive.png",
            base + "que_boi_tab_inactive.png",
        )
        diem_tabs = (
            base + "diem_binh_tab_alert_active.png",
            base + "diem_binh_tab_alert_inactive.png",
            base + "diem_binh_tab_inactive.png",
        )
        all_module_tabs = que_tabs + diem_tabs

        que_free = (
            base + "free_boi_toan_once_button.png",
            base + "free_boi_toan_once_button_alt.png",
        )
        que_paid = (base + "boi_toan_once_99_button.png",)

        diem_free = (base + "free_danh_trong_once_button.png",)
        diem_paid = (base + "danh_trong_once_100_button.png",)

        reward_banner = base + "reward_received_banner.png"
        module_close = base + "tam_quoc_lenh_close_button.png"

        # Reference layout is the actual ADB frame used by the captured live
        # screenshots in this project: 960 x 540.
        try:
            screen_width, screen_height = context.device.get_screen_size()
            screen_width = int(screen_width)
            screen_height = int(screen_height)
        except Exception:
            screen_width, screen_height = 960, 540

        scale_x = screen_width / 960.0
        scale_y = screen_height / 540.0

        def scaled_roi(reference: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            x1, y1, x2, y2 = reference
            return (
                max(0, int(round(x1 * scale_x))),
                max(0, int(round(y1 * scale_y))),
                min(screen_width, int(round(x2 * scale_x))),
                min(screen_height, int(round(y2 * scale_y))),
            )

        # Restrict matching to the real areas where each control exists. This both
        # speeds matching and prevents "99/100" from accidentally matching the x10
        # paid button on the right side.
        entry_roi = scaled_roi((180, 35, 900, 195))
        que_tab_roi = scaled_roi((20, 95, 235, 225))
        diem_tab_roi = scaled_roi((20, 175, 235, 315))
        left_action_roi = scaled_roi((235, 345, 540, 510))
        reward_roi = scaled_roi((170, 35, 810, 210))
        close_roi = scaled_roi((800, 0, 950, 95))

        # If the emulator resolution ever changes proportionally, allow a narrow
        # multi-scale search around that ratio. At the normal 960x540 resolution
        # this stays exactly (1.0,) for speed and maximum precision.
        ui_scale = min(scale_x, scale_y)
        if 0.985 <= ui_scale <= 1.015:
            match_scales = (1.0,)
        else:
            match_scales = tuple(
                scale for scale in (
                    max(0.50, ui_scale * 0.96),
                    max(0.50, ui_scale),
                    max(0.50, ui_scale * 1.04),
                )
                if scale > 0
            )

        def read_runtime() -> tuple[dict[str, Any], dict[str, Any]]:
            raw = json.loads(runtime_file.read_text(encoding="utf-8"))
            for row in raw.get("accounts", []):
                if str(row.get("id")) == account_id:
                    task = row.setdefault("tasks", {}).setdefault(
                        "tam_quoc_lenh",
                        {
                            "status": "NOT_STARTED",
                            "que_boi": "NOT_STARTED",
                            "diem_binh": "NOT_STARTED",
                            "rewards": [],
                            "error": None,
                        },
                    )
                    # Runtime cũ từng lưu tên phần thưởng fix cứng trong `rewards`.
                    # Không dùng dữ liệu suy đoán này nữa; bot chỉ lưu trạng thái nhiệm vụ.
                    task.pop("rewards", None)
                    task.setdefault("rewards", [])
                    task.setdefault("que_boi", "NOT_STARTED")
                    task.setdefault("diem_binh", "NOT_STARTED")
                    task.setdefault("error", None)
                    return raw, task

            raise KeyError(f"Runtime account not found: {account_id}")

        def save_runtime(raw: dict[str, Any]) -> None:
            temporary = runtime_file.with_suffix(runtime_file.suffix + ".tmp")
            temporary.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(runtime_file)

        def capture_frame():
            capture = getattr(context.vision, "capture", None)
            if not callable(capture):
                return None
            try:
                return capture(force=True)
            except TypeError:
                try:
                    return capture()
                except Exception:
                    return None
            except Exception:
                return None

        def find_best(
            paths: str | tuple[str, ...] | list[str],
            *,
            roi: tuple[int, int, int, int] | None = None,
            score: float = threshold,
        ):
            if isinstance(paths, str):
                candidates = (paths,)
            else:
                candidates = tuple(paths)

            frame = capture_frame()
            best_path = None
            best_match = None

            for template_path in candidates:
                kwargs = {
                    "threshold": score,
                    "roi": roi,
                    "scales": match_scales,
                }
                if frame is not None:
                    kwargs["frame"] = frame
                    kwargs["refresh"] = False
                else:
                    kwargs["refresh"] = True

                found = context.vision.find_template(template_path, **kwargs)
                if found is None:
                    continue

                if (
                    best_match is None
                    or float(getattr(found, "confidence", 1.0))
                    > float(getattr(best_match, "confidence", 1.0))
                ):
                    best_path = template_path
                    best_match = found

            if best_match is None:
                return None
            return best_path, best_match

        def probe_best_confidence(
            paths: str | tuple[str, ...] | list[str],
            *,
            roi: tuple[int, int, int, int] | None = None,
        ) -> tuple[str | None, float | None]:
            """
            Diagnostic only: find the best current score even below the normal
            threshold. This never causes a tap.
            """
            try:
                result = find_best(paths, roi=roi, score=0.0)
            except Exception:
                return None, None

            if result is None:
                return None, None

            template_path, found = result
            return template_path, float(getattr(found, "confidence", 0.0))

        def wait_best(
            paths: str | tuple[str, ...] | list[str],
            *,
            roi: tuple[int, int, int, int] | None = None,
            score: float = threshold,
            wait_timeout: float = state_timeout,
            label: str = "template",
        ):
            deadline = time.monotonic() + max(0.0, float(wait_timeout))

            while True:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")

                result = find_best(paths, roi=roi, score=score)
                if result is not None:
                    return result

                if time.monotonic() >= deadline:
                    template_path, confidence = probe_best_confidence(paths, roi=roi)
                    if confidence is None:
                        LOGGER.warning(
                            "%s not verified: no usable match candidate | threshold=%.3f roi=%s",
                            label,
                            score,
                            roi,
                        )
                    else:
                        LOGGER.warning(
                            "%s not verified: best=%s confidence=%.4f threshold=%.3f roi=%s",
                            label,
                            template_path,
                            confidence,
                            score,
                            roi,
                        )
                    return None

                _wait_interruptibly(context, interval)

        def wait_absent(
            path: str,
            *,
            roi: tuple[int, int, int, int] | None = None,
            score: float = threshold,
            wait_timeout: float = state_timeout,
        ) -> bool:
            deadline = time.monotonic() + max(0.0, float(wait_timeout))

            while True:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")

                if find_best(path, roi=roi, score=score) is None:
                    return True

                if time.monotonic() >= deadline:
                    return False

                _wait_interruptibly(context, interval)

        def tap_match(found) -> None:
            context.device.tap(*found.center)
            _wait_interruptibly(context, interval)

        def reward_overlay_visible() -> bool:
            return (
                find_best(
                    reward_banner,
                    roi=reward_roi,
                    score=reward_threshold,
                )
                is not None
            )

        def dismiss_reward_overlay(wait_timeout: float = state_timeout) -> bool:
            """
            Reward popup explicitly says "Ấn vào chỗ trống để thoát".
            Detect it by the unique reward banner, tap a safe lower blank area,
            then prove the banner disappeared.
            """
            reward = find_best(
                reward_banner,
                roi=reward_roi,
                score=reward_threshold,
            )
            if reward is None:
                return False

            LOGGER.info(
                "Tam Quốc Lệnh reward popup detected: confidence=%.4f",
                float(getattr(reward[1], "confidence", 0.0)),
            )

            # 960x540 reference -> approximately (480, 475).
            safe_x = int(round(screen_width * 0.50))
            safe_y = int(round(screen_height * 0.88))
            context.device.tap(safe_x, safe_y)
            _wait_interruptibly(context, interval)

            if not wait_absent(
                reward_banner,
                roi=reward_roi,
                score=reward_threshold,
                wait_timeout=wait_timeout,
            ):
                raise RuntimeError(
                    "Tam Quốc Lệnh reward popup did not close after blank-area tap"
                )

            return True

        def module_is_open() -> bool:
            close_found = find_best(
                module_close,
                roi=close_roi,
                score=close_threshold,
            )
            if close_found is None:
                return False

            tab_found = find_best(
                all_module_tabs,
                roi=scaled_roi((20, 95, 235, 315)),
                score=tab_threshold,
            )
            return tab_found is not None

        def ensure_module_open() -> None:
            # Resume cleanly if the previous run was interrupted on a reward popup.
            if reward_overlay_visible():
                dismiss_reward_overlay()

            if module_is_open():
                LOGGER.info("Tam Quốc Lệnh module already open; resuming current account")
                return

            entry = wait_best(
                entry_templates,
                roi=entry_roi,
                score=entry_threshold,
                wait_timeout=open_timeout,
                label="Tam Quốc Lệnh HOME entry",
            )
            if entry is None:
                raise RuntimeError(
                    "Tam Quốc Lệnh entry not verified on HOME "
                    f"(threshold={entry_threshold:.3f}, roi={entry_roi})"
                )

            entry_path, entry_match = entry
            LOGGER.info(
                "Tam Quốc Lệnh entry detected: template=%s confidence=%.4f center=%s",
                entry_path,
                float(getattr(entry_match, "confidence", 0.0)),
                entry_match.center,
            )
            tap_match(entry_match)

            close_ready = wait_best(
                module_close,
                roi=close_roi,
                score=close_threshold,
                wait_timeout=open_timeout,
                label="Tam Quốc Lệnh close button after opening",
            )
            tabs_ready = wait_best(
                all_module_tabs,
                roi=scaled_roi((20, 95, 235, 315)),
                score=tab_threshold,
                wait_timeout=open_timeout,
                label="Tam Quốc Lệnh left tabs after opening",
            )
            if close_ready is None or tabs_ready is None:
                raise RuntimeError(
                    "Tam Quốc Lệnh window did not finish opening "
                    f"within {open_timeout:.1f}s"
                )

        def run_branch(
            *,
            key: str,
            tab_templates: tuple[str, ...],
            tab_roi: tuple[int, int, int, int],
            free_templates: tuple[str, ...],
            paid_templates: tuple[str, ...],
            reward_name: str = "",
        ) -> None:
            if task.get(key) == "DONE":
                LOGGER.info("Tam Quốc Lệnh %s already DONE in runtime; skipping", key)
                return

            # Clean up an interrupted reward popup before changing tabs.
            if reward_overlay_visible():
                dismiss_reward_overlay()

            tab = wait_best(
                tab_templates,
                roi=tab_roi,
                score=tab_threshold,
                wait_timeout=state_timeout,
                label=f"{key} tab",
            )
            if tab is None:
                raise RuntimeError(
                    f"{key} tab not verified "
                    f"(threshold={tab_threshold:.3f}, roi={tab_roi})"
                )

            tab_path, tab_match = tab
            LOGGER.info(
                "Tam Quốc Lệnh %s tab detected: template=%s confidence=%.4f center=%s",
                key,
                tab_path,
                float(getattr(tab_match, "confidence", 0.0)),
                tab_match.center,
            )

            # It is safe to tap the branch tab even if that tab is already active.
            tap_match(tab_match)

            # Wait until this branch exposes either the free daily button or the
            # paid/used button. This is the actual proof that the branch finished
            # loading; it avoids the old race where one screenshot was taken too soon.
            state = wait_best(
                free_templates + paid_templates,
                roi=left_action_roi,
                score=threshold,
                wait_timeout=state_timeout,
                label=f"{key} action state",
            )
            if state is None:
                raise RuntimeError(
                    f"{key} action state not verified "
                    f"(free/paid control missing, threshold={threshold:.3f})"
                )

            state_path, state_match = state

            if state_path in paid_templates:
                # Already completed earlier today (or by a previous interrupted run).
                task[key] = "DONE"
                task["status"] = "PARTIAL"
                if reward_name and reward_name not in task.setdefault("rewards", []):
                    task["rewards"].append(reward_name)
                save_runtime(raw)
                LOGGER.info(
                    "Tam Quốc Lệnh %s already completed: paid/used control=%s confidence=%.4f",
                    key,
                    state_path,
                    float(getattr(state_match, "confidence", 0.0)),
                )
                return

            # Free daily action is available.
            LOGGER.info(
                "Tam Quốc Lệnh %s free action detected: template=%s confidence=%.4f center=%s",
                key,
                state_path,
                float(getattr(state_match, "confidence", 0.0)),
                state_match.center,
            )
            tap_match(state_match)

            # After the free tap, valid transitions are:
            # 1) reward popup appears -> dismiss it;
            # 2) paid/used state appears directly (server/UI skipped popup).
            deadline = time.monotonic() + timeout
            reward_seen = False
            paid_after = None

            while time.monotonic() <= deadline:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")

                reward = find_best(
                    reward_banner,
                    roi=reward_roi,
                    score=reward_threshold,
                )
                if reward is not None:
                    reward_seen = True
                    dismiss_reward_overlay(wait_timeout=state_timeout)
                    break

                paid_after = find_best(
                    paid_templates,
                    roi=left_action_roi,
                    score=threshold,
                )
                if paid_after is not None:
                    break

                _wait_interruptibly(context, interval)

            if paid_after is None:
                paid_after = wait_best(
                    paid_templates,
                    roi=left_action_roi,
                    score=threshold,
                    wait_timeout=state_timeout,
                    label=f"{key} paid/used postcondition",
                )

            if paid_after is None:
                raise RuntimeError(
                    f"{key} free action postcondition not verified "
                    "(paid/used control did not appear)"
                )

            task[key] = "DONE"
            task["status"] = "PARTIAL"

            # Không ghi tên/số lượng phần thưởng nếu bot không thực sự đọc chúng.
            # Popup chỉ được dùng để xác nhận/đóng luồng nhận thưởng.
            if reward_name and reward_name not in task.setdefault("rewards", []):
                task["rewards"].append(reward_name)

            save_runtime(raw)
            LOGGER.info(
                "Tam Quốc Lệnh %s completed%s",
                key,
                " with reward popup" if reward_seen else "",
            )

        raw, task = read_runtime()

        if task.get("status") == "DONE":
            return ActionResult(
                True,
                "tam_quoc_lenh",
                "Already completed today",
                dict(task),
            )

        task["status"] = "IN_PROGRESS"
        task["error"] = None
        save_runtime(raw)

        try:
            ensure_module_open()

            run_branch(
                key="que_boi",
                tab_templates=que_tabs,
                tab_roi=que_tab_roi,
                free_templates=que_free,
                paid_templates=que_paid,
                reward_name="5 Quẻ lành",
            )

            run_branch(
                key="diem_binh",
                tab_templates=diem_tabs,
                tab_roi=diem_tab_roi,
                free_templates=diem_free,
                paid_templates=diem_paid,
                reward_name="20 Nguyên linh ngọc",
            )

            # Defensive cleanup in case a slow reward popup arrived after the
            # paid-state transition was already observed.
            if reward_overlay_visible():
                dismiss_reward_overlay()

            # If the module somehow already closed, accepting verified HOME is safe.
            current_home = find_best(home, score=home_threshold)
            current_close = find_best(
                module_close,
                roi=close_roi,
                score=close_threshold,
            )

            if current_close is not None:
                _, close_match = current_close
                LOGGER.info(
                    "Tam Quốc Lệnh close button detected: confidence=%.4f center=%s",
                    float(getattr(close_match, "confidence", 0.0)),
                    close_match.center,
                )
                tap_match(close_match)
            elif current_home is None:
                raise RuntimeError(
                    "Tam Quốc Lệnh close button not verified and HOME not visible"
                )

            # Require stable HOME twice. This proves the module actually closed and
            # prevents the account manager from continuing while an overlay remains.
            stable_home = 0
            deadline = time.monotonic() + timeout

            while time.monotonic() <= deadline:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")

                close_still_visible = (
                    find_best(
                        module_close,
                        roi=close_roi,
                        score=close_threshold,
                    )
                    is not None
                )
                home_visible = find_best(home, score=home_threshold) is not None

                if home_visible and not close_still_visible:
                    stable_home += 1
                    if stable_home >= 2:
                        task["status"] = "DONE"
                        task["error"] = None
                        save_runtime(raw)

                        return ActionResult(
                            True,
                            "tam_quoc_lenh",
                            "Completed and returned to stable HOME",
                            dict(task),
                        )
                else:
                    stable_home = 0

                _wait_interruptibly(context, interval)

            raise RuntimeError(
                "Tam Quốc Lệnh did not return to stable HOME after closing"
            )

        except ActionStopRequested:
            done = sum(
                task.get(key) == "DONE"
                for key in ("que_boi", "diem_binh")
            )
            task["status"] = "PARTIAL" if done else "NOT_STARTED"
            task["error"] = "Stop requested"
            save_runtime(raw)
            raise

        except Exception as exc:
            done = sum(
                task.get(key) == "DONE"
                for key in ("que_boi", "diem_binh")
            )
            task["status"] = "PARTIAL" if done else "FAILED"
            task["error"] = str(exc)
            save_runtime(raw)

            return ActionResult(
                False,
                "tam_quoc_lenh",
                str(exc),
                dict(task),
            )

    @staticmethod
    def _phuc_loi(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Xử lý nhóm Hoạt động -> Phúc lợi; không đụng vào Ngày lễ/Hoạt động."""
        import json
        from datetime import datetime
        from pathlib import Path

        account_id = str(_require(params, "account_id"))
        runtime_file = Path(str(_require(params, "runtime_file")))

        mode = str(params.get("mode", "full")).strip().lower()
        checkin_only = mode in {"diem_danh", "checkin", "checkin_only"}
        skip_checkin = bool(params.get("skip_checkin", False)) and not checkin_only
        claim_checkin = bool(params.get("claim_checkin", checkin_only))
        package = str(params.get("package", "com.daichien.mobile"))
        activity = str(params.get("activity", "com.qtz.game.main.Logo"))

        threshold = float(params.get("threshold", 0.90))
        entry_threshold = float(params.get("entry_threshold", 0.82))
        tab_threshold = float(params.get("tab_threshold", 0.80))
        state_threshold = float(params.get("state_threshold", 0.90))
        checkin_claim_threshold = float(params.get("checkin_claim_threshold", 0.68))
        # Logic Điểm danh v3:
        # ô cần nhận hiện tại có cùng biểu tượng "?" với các ô tương lai, nhưng
        # riêng ô hiện tại có quầng sáng mạnh hơn. Template mới bao gồm quầng sáng
        # và dải trạng thái, không phụ thuộc vật phẩm hay số lượng quà bên dưới.
        checkin_cell_threshold = float(params.get("checkin_cell_threshold", 0.80))
        checkin_cell_margin = float(params.get("checkin_cell_margin", 0.05))
        checkin_click_retries = max(1, int(params.get("checkin_click_retries", 3)))
        # Giữ tham số cũ để tương thích file YAML/runtime của các bản trước.
        checkin_glow_threshold = float(params.get("checkin_glow_threshold", 0.55))
        checkin_glow_margin = float(params.get("checkin_glow_margin", 0.06))
        # Lễ Bao Quốc Vận có hiệu ứng sáng/animation nên template "Miễn phí"
        # thường dao động thấp hơn các state tĩnh. Dùng threshold riêng để không
        # làm lỏng toàn bộ các nhận diện khác.
        bao_state_threshold = float(params.get("bao_state_threshold", min(state_threshold, 0.80)))
        reward_threshold = float(params.get("reward_threshold", 0.90))
        close_threshold = float(params.get("close_threshold", 0.90))
        home_threshold = float(params.get("home_threshold", 0.75))
        timeout = max(2.0, float(params.get("timeout", 30.0)))
        open_timeout = max(2.0, float(params.get("open_timeout", 12.0)))
        state_timeout = max(2.0, float(params.get("state_timeout", 8.0)))
        interval = max(0.05, float(params.get("interval", 0.5)))
        max_online_claims = max(1, int(params.get("max_online_claims", 8)))
        max_online_scrolls = max(0, int(params.get("max_online_scrolls", 3)))
        max_menu_scrolls = max(1, int(params.get("max_menu_scrolls", 4)))
        tax_windows = params.get(
            "tax_windows",
            ["12:00-14:00", "18:00-20:00", "21:00-23:00"],
        )
        if not isinstance(tax_windows, (list, tuple)):
            raise ValueError("phuc_loi.tax_windows must be a list of HH:MM-HH:MM strings")

        def parse_clock(value: str) -> int:
            text = str(value).strip()
            try:
                hour_text, minute_text = text.split(":", 1)
                hour, minute = int(hour_text), int(minute_text)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid welfare tax clock: {value!r}") from exc
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"Invalid welfare tax clock: {value!r}")
            return hour * 60 + minute

        parsed_tax_windows: list[tuple[int, int]] = []
        for raw_window in tax_windows:
            try:
                start_text, end_text = str(raw_window).split("-", 1)
            except ValueError as exc:
                raise ValueError(f"Invalid welfare tax window: {raw_window!r}") from exc
            start_minute = parse_clock(start_text)
            end_minute = parse_clock(end_text)
            if end_minute <= start_minute:
                raise ValueError(
                    f"Welfare tax window must end after start on the same day: {raw_window!r}"
                )
            parsed_tax_windows.append((start_minute, end_minute))

        def tax_window_open(now=None) -> bool:
            current = now or datetime.now().astimezone()
            minute_of_day = current.hour * 60 + current.minute
            return any(start <= minute_of_day < end for start, end in parsed_tax_windows)

        root = "dc3q/targets/Hoạt-Động/"
        welfare = root + "Phúc-Lợi/screen/"
        home_marker = "dc3q/common/home_marker_noi_chinh.png"
        home_entry = root + "screen/home_hoat_dong_entry.png"
        welfare_selected = root + "screen/phuc_loi_selected.png"
        panel_close = root + "screen/event_panel_close_button.png"

        bao_base = welfare + "Lễ-Bao-Quốc-Vận/"
        bao_titles = (
            bao_base + "screen_bao_quoc_van_title_alert.png",
            bao_base + "screen_bao_quoc_van_title.png",
            bao_base + "screen_bao_quoc_van_title_inactive.png",
        )
        bao_free = bao_base + "screen_bao_quoc_van_free_chest_button.png"
        bao_claimed = bao_base + "screen_bao_quoc_van_claimed_badge.png"
        bao_reward = bao_base + "screen_bao_quoc_van_reward_received_banner.png"

        online_base = welfare + "Qùa-Online/"
        online_titles = (
            online_base + "screen_qua_online_title_alert.png",
            online_base + "screen_qua_online_title_inactive.png",
        )
        online_claim = online_base + "screen_qua_online_claim_button.png"
        online_claimed = online_base + "screen_qua_online_claimed_badge.png"
        online_not_ready = online_base + "screen_qua_online_not_qualified_button.png"

        checkin_base = welfare + "Điểm-Danh/"
        checkin_titles = (
            checkin_base + "screen_diem_danh_title_alert.png",
            checkin_base + "screen_diem_danh_title_inactive_alert.png",
            checkin_base + "screen_diem_danh_title_inactive.png",
        )
        checkin_marker = checkin_base + "screen_diem_danh_page_marker.png"
        checkin_claimable = checkin_base + "screen_diem_danh_claimable_badge.png"
        checkin_glow_cell = checkin_base + "screen_diem_danh_claimable_glow_cell.png"
        checkin_reward = checkin_base + "screen_diem_danh_reward_received_banner.png"
        checkin_selected_alert = checkin_base + "screen_diem_danh_title_alert.png"

        tax_base = welfare + "Trưng-Thu-Thuế/"
        tax_nav_anchor = welfare + "navigation/screen_hoat_dong_gioi_han_inactive.png"
        tax_titles = (
            tax_base + "screen_trung_thu_thue_title_alert.png",
            tax_base + "screen_trung_thu_thue_title.png",
        )
        tax_claim = tax_base + "screen_trung_thu_tab_button.png"
        tax_claimed = tax_base + "screen_trung_thu_thue_claimed_button.png"
        tax_not_ready = tax_base + "screen_trung_thu_thue_unopened_button.png"
        tax_reward = tax_base + "screen_trung_thu_thue_reward_received_banner.png"

        try:
            screen_width, screen_height = context.device.get_screen_size()
            screen_width, screen_height = int(screen_width), int(screen_height)
        except Exception:
            screen_width, screen_height = 960, 540

        scale_x = screen_width / 960.0
        scale_y = screen_height / 540.0
        ui_scale = min(scale_x, scale_y)
        match_scales = (1.0,) if 0.985 <= ui_scale <= 1.015 else (
            max(0.50, ui_scale * 0.96), max(0.50, ui_scale), max(0.50, ui_scale * 1.04)
        )

        def scaled_roi(ref: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            x1, y1, x2, y2 = ref
            return (
                max(0, int(round(x1 * scale_x))), max(0, int(round(y1 * scale_y))),
                min(screen_width, int(round(x2 * scale_x))), min(screen_height, int(round(y2 * scale_y))),
            )

        def scaled_point(x: int, y: int) -> tuple[int, int]:
            return int(round(x * scale_x)), int(round(y * scale_y))

        home_entry_roi = scaled_roi((0, 330, 130, 455))
        welfare_nav_roi = scaled_roi((0, 115, 110, 230))
        close_roi = scaled_roi((875, 20, 960, 115))
        bao_title_roi = scaled_roi((90, 105, 250, 225))
        online_title_roi = scaled_roi((90, 245, 250, 375))
        checkin_title_roi = scaled_roi((90, 325, 250, 455))
        checkin_marker_roi = scaled_roi((240, 55, 470, 175))
        checkin_grid_roi = scaled_roi((230, 185, 920, 520))
        # ROI cũ dừng ở x=470 nên quá sát với rương đầu tiên và dễ mất match
        # khi UI bị scale/animation. Mở rộng sang toàn khu vực rương đầu.
        bao_action_roi = scaled_roi((235, 40, 650, 275))
        online_actions_roi = scaled_roi((540, 150, 900, 525))
        reward_roi = scaled_roi((160, 20, 800, 190))
        tax_title_roi = scaled_roi((90, 245, 250, 455))
        tax_nav_roi = scaled_roi((90, 40, 250, 525))
        tax_action_roi = scaled_roi((560, 315, 845, 470))

        def read_runtime() -> tuple[dict[str, Any], dict[str, Any]]:
            raw = json.loads(runtime_file.read_text(encoding="utf-8"))
            for row in raw.get("accounts", []):
                if str(row.get("id")) != account_id:
                    continue
                task = row.setdefault("tasks", {}).setdefault("phuc_loi", {})
                defaults = {
                    "status": "NOT_STARTED",
                    "le_bao_quoc_van": "NOT_STARTED",
                    "qua_online": "NOT_STARTED",
                    "qua_online_claims": 0,
                    "qua_online_reason": None,
                    "diem_danh": "NOT_STARTED",
                    "trung_thu_thue": "NOT_STARTED",
                    "trung_thu_thue_reason": None,
                    "error": None,
                }
                for key, value in defaults.items():
                    task.setdefault(key, value)
                # Xóa dữ liệu rewards fix cứng từ runtime cũ nếu còn tồn tại.
                task.pop("rewards", None)
                return raw, task
            raise KeyError(f"Runtime account not found: {account_id}")

        def save_runtime(raw: dict[str, Any]) -> None:
            temporary = runtime_file.with_suffix(runtime_file.suffix + ".tmp")
            temporary.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(runtime_file)

        def capture_frame():
            capture = getattr(context.vision, "capture", None)
            if not callable(capture):
                return None
            try:
                return capture(force=True)
            except TypeError:
                try:
                    return capture()
                except Exception:
                    return None
            except Exception:
                return None

        def find_best(paths, *, roi=None, score=threshold):
            candidates = (paths,) if isinstance(paths, str) else tuple(paths)
            frame = capture_frame()
            best = None
            best_path = None
            for template_path in candidates:
                kwargs = {"threshold": score, "roi": roi, "scales": match_scales}
                if frame is not None:
                    kwargs.update({"frame": frame, "refresh": False})
                else:
                    kwargs["refresh"] = True
                found = context.vision.find_template(template_path, **kwargs)
                if found is not None and (best is None or float(found.confidence) > float(best.confidence)):
                    best_path, best = template_path, found
            return None if best is None else (best_path, best)

        def find_all(path: str, *, roi=None, score=threshold):
            method = getattr(context.vision, "find_all_templates", None)
            if not callable(method):
                one = find_best(path, roi=roi, score=score)
                return [] if one is None else [one[1]]
            frame = capture_frame()
            kwargs = {"threshold": score, "roi": roi, "scales": match_scales, "max_results": 12}
            if frame is not None:
                kwargs.update({"frame": frame, "refresh": False})
            else:
                kwargs["refresh"] = True
            return list(method(path, **kwargs))

        def wait_best(paths, *, roi=None, score=threshold, wait_timeout=state_timeout):
            deadline = time.monotonic() + wait_timeout
            while True:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")
                result = find_best(paths, roi=roi, score=score)
                if result is not None:
                    return result
                if time.monotonic() >= deadline:
                    return None
                _wait_interruptibly(context, interval)

        def wait_absent(path: str, *, roi=None, score=threshold, wait_timeout=state_timeout) -> bool:
            deadline = time.monotonic() + wait_timeout
            while True:
                if find_best(path, roi=roi, score=score) is None:
                    return True
                if time.monotonic() >= deadline:
                    return False
                _wait_interruptibly(context, interval)

        def tap_match(match) -> None:
            context.device.tap(*match.center)
            _wait_interruptibly(context, interval)

        def dismiss_reward(path: str) -> bool:
            reward = find_best(path, roi=reward_roi, score=reward_threshold)
            if reward is None:
                return False
            context.device.tap(*scaled_point(480, 475))
            _wait_interruptibly(context, interval)
            if not wait_absent(path, roi=reward_roi, score=reward_threshold):
                raise RuntimeError("Phúc lợi: popup phần thưởng không đóng sau khi chạm vùng trống")
            return True

        def ensure_welfare_open() -> None:
            if find_best(welfare_selected, roi=welfare_nav_roi, score=tab_threshold) is not None:
                return

            panel_open = find_best(panel_close, roi=close_roi, score=close_threshold)
            if panel_open is None:
                if find_best(home_marker, score=home_threshold) is None:
                    raise RuntimeError("Phúc lợi: không chứng minh được đang ở HOME hoặc cửa sổ Hoạt động")
                entry = wait_best(home_entry, roi=home_entry_roi, score=entry_threshold, wait_timeout=open_timeout)
                if entry is None:
                    raise RuntimeError("Phúc lợi: không nhận diện được nút Hoạt động trên HOME")
                tap_match(entry[1])
                if wait_best(panel_close, roi=close_roi, score=close_threshold, wait_timeout=open_timeout) is None:
                    raise RuntimeError("Phúc lợi: cửa sổ Hoạt động không mở hoàn chỉnh")

            # Chỉ chọn Phúc lợi. Hai nút Ngày lễ/Hoạt động tuyệt đối không được thao tác.
            context.device.tap(*scaled_point(65, 180))
            _wait_interruptibly(context, interval)
            if wait_best(welfare_selected, roi=welfare_nav_roi, score=tab_threshold, wait_timeout=open_timeout) is None:
                raise RuntimeError("Phúc lợi: không xác nhận được tab Phúc lợi đã được chọn")

        def run_bao(task: dict[str, Any]) -> None:
            if task.get("le_bao_quoc_van") == "CLAIMED":
                return

            title = wait_best(bao_titles, roi=bao_title_roi, score=tab_threshold)
            if title is None:
                task["le_bao_quoc_van"] = "NOT_PRESENT"
                return

            # Runtime phải phản ánh rằng bot đã thực sự bắt đầu mục này.
            task["le_bao_quoc_van"] = "RUNNING"
            tap_match(title[1])

            # Template Miễn phí thực tế có thể chỉ đạt ~0.83 do animation/ánh sáng,
            # vì vậy không dùng state_threshold=0.90 chung cho mục này.
            state = wait_best(
                (bao_free, bao_claimed),
                roi=bao_action_roi,
                score=bao_state_threshold,
            )

            # Retry một lần với ngưỡng thấp hơn một chút. Chỉ áp dụng cho đúng
            # hai template của rương đầu, không ảnh hưởng các task khác.
            if state is None:
                retry_score = max(0.72, bao_state_threshold - 0.06)
                state = wait_best(
                    (bao_free, bao_claimed),
                    roi=bao_action_roi,
                    score=retry_score,
                    wait_timeout=max(2.0, state_timeout / 2.0),
                )

            if state is None:
                raise RuntimeError(
                    "Phúc lợi/Lễ Bao Quốc Vận: không xác định được trạng thái rương miễn phí "
                    f"(threshold={bao_state_threshold:.2f})"
                )

            if state[0] == bao_free:
                tap_match(state[1])
                reward_seen = False
                claimed_seen = False
                deadline = time.monotonic() + timeout
                while time.monotonic() <= deadline:
                    if dismiss_reward(bao_reward):
                        reward_seen = True
                        break
                    if find_best(bao_claimed, roi=bao_action_roi, score=bao_state_threshold) is not None:
                        claimed_seen = True
                        break
                    _wait_interruptibly(context, interval)

                # Popup phần thưởng là bằng chứng nhận thành công. Không bắt buộc
                # badge "Đã nhận" phải match ngay sau animation đóng popup.
                if not reward_seen and not claimed_seen:
                    claimed = wait_best(
                        bao_claimed,
                        roi=bao_action_roi,
                        score=bao_state_threshold,
                        wait_timeout=max(2.0, state_timeout / 2.0),
                    )
                    if claimed is None:
                        raise RuntimeError(
                            "Phúc lợi/Lễ Bao Quốc Vận: bấm rương nhưng không xác nhận được phần thưởng/Đã nhận"
                        )

            task["le_bao_quoc_van"] = "CLAIMED"

        def run_online(task: dict[str, Any]) -> None:
            title = wait_best(online_titles, roi=online_title_roi, score=tab_threshold)
            if title is None:
                task["qua_online"] = "NOT_PRESENT"
                task["qua_online_reason"] = "ITEM_NOT_PRESENT"
                return

            tap_match(title[1])
            page_state = wait_best(
                (online_claim, online_claimed, online_not_ready),
                roi=online_actions_roi,
                score=state_threshold,
            )
            if page_state is None:
                raise RuntimeError("Phúc lợi/Quà online: không xác nhận được trang phần thưởng")

            # Quà online chỉ nhận được khi tài khoản đã tích đủ thời gian online
            # (các mốc 1-2 giờ do game quyết định). Bot tuyệt đối không đứng chờ.
            if page_state[0] == online_not_ready:
                task["qua_online"] = "PENDING"
                task["qua_online_reason"] = "ONLINE_TIME_NOT_ENOUGH"
                return

            claimed_now = 0
            scrolls = 0
            pending = False

            while claimed_now < max_online_claims:
                buttons = sorted(
                    find_all(online_claim, roi=online_actions_roi, score=state_threshold),
                    key=lambda m: m.center[1],
                )
                if buttons:
                    target = buttons[0]
                    old_center = target.center
                    tap_match(target)
                    deadline = time.monotonic() + state_timeout
                    transitioned = False
                    while time.monotonic() <= deadline:
                        current = find_all(online_claim, roi=online_actions_roi, score=state_threshold)
                        if not any(
                            abs(m.center[0] - old_center[0]) <= 20
                            and abs(m.center[1] - old_center[1]) <= 20
                            for m in current
                        ):
                            transitioned = True
                            break
                        _wait_interruptibly(context, interval)
                    if not transitioned:
                        raise RuntimeError("Phúc lợi/Quà online: nút Nhận không đổi trạng thái sau khi bấm")
                    claimed_now += 1
                    continue

                # Gặp Chưa đạt nghĩa là mốc kế tiếp cần thêm thời gian online.
                # Đây là trạng thái bình thường, không phải lỗi và không chờ tại chỗ.
                if find_best(online_not_ready, roi=online_actions_roi, score=state_threshold) is not None:
                    pending = True
                    break

                if scrolls >= max_online_scrolls:
                    break

                context.device.swipe(*scaled_point(800, 470), *scaled_point(800, 245), 350)
                scrolls += 1
                _wait_interruptibly(context, interval)

            task["qua_online_claims"] = int(task.get("qua_online_claims", 0) or 0) + claimed_now
            if pending:
                task["qua_online"] = "PENDING"
                task["qua_online_reason"] = "ONLINE_TIME_NOT_ENOUGH"
            else:
                # Đã kiểm tra hết phần nhìn thấy và không còn nút Nhận/Chưa đạt.
                task["qua_online"] = "DONE" if (claimed_now or page_state[0] == online_claimed) else "CHECKED"
                task["qua_online_reason"] = None

        def checkin_glow_score(center: tuple[int, int], frame=None) -> float | None:
            """
            Chấm điểm mức "phát sáng vàng" quanh một ô Điểm danh.

            Badge "Được báo danh" xuất hiện ở nhiều ô, nhưng ô có thể nhận hiện tại
            có quầng/viền vàng sáng quanh cell. Ta đo phần vàng ở vành ngoài cell
            so với phần bên trong, nên không phụ thuộc vật phẩm đang hiển thị.
            """
            try:
                import cv2
                import numpy as np
            except Exception:
                return None

            current = frame if frame is not None else capture_frame()
            image = getattr(current, "image", current)
            if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
                return None

            cx, cy = int(center[0]), int(center[1])
            half_w = max(24, int(round(36 * scale_x)))
            half_h = max(24, int(round(36 * scale_y)))
            x1, x2 = max(0, cx - half_w), min(int(image.shape[1]), cx + half_w)
            y1, y2 = max(0, cy - half_h), min(int(image.shape[0]), cy + half_h)
            if x2 - x1 < 24 or y2 - y1 < 24:
                return None

            patch = image[y1:y2, x1:x2]
            if patch.ndim == 2:
                bgr = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
            elif patch.ndim == 3 and patch.shape[2] == 4:
                bgr = cv2.cvtColor(patch, cv2.COLOR_BGRA2BGR)
            elif patch.ndim == 3 and patch.shape[2] == 3:
                bgr = patch
            else:
                return None

            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            hue = hsv[:, :, 0]
            sat = hsv[:, :, 1]
            val = hsv[:, :, 2]

            # OpenCV H dùng thang 0..179. Khoảng 18..38 tương ứng vàng/gold.
            yellow = (hue >= 18) & (hue <= 38) & (sat >= 110) & (val >= 155)

            h, w = val.shape[:2]
            thickness = max(4, min(h, w) // 7)
            ring = np.zeros((h, w), dtype=bool)
            ring[:thickness, :] = True
            ring[-thickness:, :] = True
            ring[:, :thickness] = True
            ring[:, -thickness:] = True
            inner = ~ring
            if not np.any(ring) or not np.any(inner):
                return None

            ring_yellow = float(np.mean(yellow[ring]))
            inner_yellow = float(np.mean(yellow[inner]))
            ring_value = float(np.mean(val[ring]))
            inner_value = float(np.mean(val[inner]))

            # Quầng sáng thật có vàng tập trung ở vành cell nhiều hơn bên trong.
            yellow_contrast = ring_yellow - inner_yellow
            value_delta = (ring_value - inner_value) / 70.0
            value_term = max(-0.18, min(0.18, value_delta))
            return ring_yellow + max(0.0, yellow_contrast) * 0.65 + value_term

        def select_glowing_checkin(candidates):
            if not candidates:
                return None, []
            frame = capture_frame()
            scored = []
            for candidate in candidates:
                score = checkin_glow_score(candidate.center, frame=frame)
                if score is None:
                    continue
                scored.append((float(score), candidate))
            scored.sort(key=lambda item: item[0], reverse=True)
            if not scored:
                return None, []

            best_score, best_match = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else None
            LOGGER.info(
                "Phúc lợi/Điểm danh glow candidates: %s",
                [
                    {
                        "center": tuple(item[1].center),
                        "template_confidence": round(float(getattr(item[1], "confidence", 0.0)), 4),
                        "glow_score": round(float(item[0]), 4),
                    }
                    for item in scored
                ],
            )

            if best_score < checkin_glow_threshold:
                return None, scored
            if second_score is not None and (best_score - second_score) < checkin_glow_margin:
                # Không click khi hai ô sáng gần như nhau: ưu tiên fail-safe thay vì bấm nhầm.
                return None, scored
            return best_match, scored

        def run_checkin(task: dict[str, Any]) -> None:
            """
            Nhận Điểm danh theo ô đang phát sáng, không phụ thuộc vật phẩm.

            Hai kiểu claimable đã quan sát được:
            1) ô có thẻ xanh "Được báo danh" nhưng chỉ MỘT ô có glow mạnh;
            2) ô "?" có quầng sáng mạnh hơn các ô "?" tương lai.

            Bot ưu tiên detector (1) vì phù hợp ảnh account hiện tại; nếu không đủ
            chắc chắn mới fallback detector (2). Sau click, chỉ cần chứng minh control
            tại đúng ô cũ biến mất 2 frame hoặc xuất hiện popup phần thưởng.
            """
            logic_version = int(task.get("diem_danh_logic_version", 0) or 0)
            if logic_version < 3:
                task["diem_danh_logic_version"] = 3
                task["diem_danh_error"] = None
                if task.get("diem_danh") in {
                    "CLAIMED", "ALREADY_DONE", "DONE", "CHECKED", "OPENED",
                    "FAILED",
                }:
                    task["diem_danh"] = "NOT_STARTED"

            title = wait_best(checkin_titles, roi=checkin_title_roi, score=tab_threshold)
            if title is None:
                task["diem_danh"] = "NOT_PRESENT"
                task["diem_danh_error"] = None
                return

            task["diem_danh"] = "RUNNING"
            task["diem_danh_error"] = None
            tap_match(title[1])

            if wait_best(
                checkin_marker,
                roi=checkin_marker_roi,
                score=state_threshold,
                wait_timeout=open_timeout,
            ) is None:
                raise RuntimeError(
                    "Phúc lợi/Điểm danh: không xác nhận được trang Báo danh tích lũy"
                )

            if not claim_checkin:
                task["diem_danh"] = "CHECKED"
                return

            # Detector A: các badge xanh có thể xuất hiện nhiều nơi; chọn candidate
            # có glow vàng mạnh nhất. Đây là detector phù hợp ảnh user vừa cung cấp.
            badge_candidates = find_all(
                checkin_claimable,
                roi=checkin_grid_roi,
                score=checkin_claim_threshold,
            )
            badge_target, badge_scores = select_glowing_checkin(badge_candidates)

            # Detector B: một số account hiển thị ô hiện tại bằng cell "?".
            def current_question_matches():
                matches = find_all(
                    checkin_glow_cell,
                    roi=checkin_grid_roi,
                    score=checkin_cell_threshold,
                )
                return sorted(
                    matches,
                    key=lambda item: float(getattr(item, "confidence", 0.0)),
                    reverse=True,
                )

            def unique_question_cell():
                matches = current_question_matches()
                if not matches:
                    return None, []
                best = matches[0]
                best_score = float(getattr(best, "confidence", 0.0))
                second_score = (
                    float(getattr(matches[1], "confidence", 0.0))
                    if len(matches) > 1 else 0.0
                )
                LOGGER.info(
                    "Phúc lợi/Điểm danh question-cell candidates: %s",
                    [
                        {
                            "center": tuple(item.center),
                            "confidence": round(float(getattr(item, "confidence", 0.0)), 4),
                        }
                        for item in matches[:8]
                    ],
                )
                if best_score < checkin_cell_threshold:
                    return None, matches
                if len(matches) > 1 and (best_score - second_score) < checkin_cell_margin:
                    return None, matches
                return best, matches

            question_target, question_matches = unique_question_cell()

            if badge_target is not None:
                target = badge_target
                detector = "badge_glow"
                current_detector_matches = lambda: find_all(
                    checkin_claimable,
                    roi=checkin_grid_roi,
                    score=checkin_claim_threshold,
                )
            elif question_target is not None:
                target = question_target
                detector = "question_glow"
                current_detector_matches = current_question_matches
            else:
                # Không xác định được một ô claimable duy nhất. Không dùng badge đỏ
                # của menu làm lỗi vì nó có thể báo ô bù báo danh. Trạng thái này
                # được coi như hôm nay đã nhận để tránh click nhầm.
                task["diem_danh"] = "ALREADY_DONE"
                task["diem_danh_error"] = None
                LOGGER.info(
                    "Phúc lợi/Điểm danh: không có ô phát sáng duy nhất "
                    "(badge_candidates=%d, question_candidates=%d)",
                    len(badge_candidates),
                    len(question_matches),
                )
                return

            old_center = tuple(target.center)
            LOGGER.info(
                "Phúc lợi/Điểm danh: chọn ô phát sáng detector=%s center=%s confidence=%.4f",
                detector,
                old_center,
                float(getattr(target, "confidence", 0.0)),
            )

            for attempt in range(1, checkin_click_retries + 1):
                context.device.tap(*old_center)
                _wait_interruptibly(context, max(interval, 0.7))

                # Popup chung "Chúc mừng nhận được".
                reward = find_best(
                    checkin_reward,
                    roi=reward_roi,
                    score=reward_threshold,
                )
                if reward is not None:
                    LOGGER.info(
                        "Phúc lợi/Điểm danh: reward popup detected confidence=%.4f",
                        float(getattr(reward[1], "confidence", 0.0)),
                    )
                    context.device.tap(*scaled_point(480, 475))
                    _wait_interruptibly(context, interval)
                    wait_absent(
                        checkin_reward,
                        roi=reward_roi,
                        score=reward_threshold,
                        wait_timeout=max(2.0, state_timeout),
                    )
                    task["diem_danh"] = "CLAIMED"
                    task["diem_danh_error"] = None
                    return

                # Bản v2 quá chặt: yêu cầu cả badge VÀ glow cùng biến mất.
                # Bản v3 chỉ yêu cầu control claimable tại ĐÚNG ô cũ biến mất
                # ổn định 2 frame. Đây là post-condition trực tiếp của click.
                stable_changed = 0
                verify_deadline = time.monotonic() + state_timeout
                while time.monotonic() <= verify_deadline:
                    if _stop_requested(context):
                        raise ActionStopRequested("Stop requested")

                    reward = find_best(
                        checkin_reward,
                        roi=reward_roi,
                        score=reward_threshold,
                    )
                    if reward is not None:
                        context.device.tap(*scaled_point(480, 475))
                        _wait_interruptibly(context, interval)
                        wait_absent(
                            checkin_reward,
                            roi=reward_roi,
                            score=reward_threshold,
                            wait_timeout=max(2.0, state_timeout),
                        )
                        task["diem_danh"] = "CLAIMED"
                        task["diem_danh_error"] = None
                        return

                    current = current_detector_matches()
                    old_still_claimable = any(
                        abs(item.center[0] - old_center[0])
                        <= max(28, int(round(38 * scale_x)))
                        and abs(item.center[1] - old_center[1])
                        <= max(24, int(round(34 * scale_y)))
                        for item in current
                    )

                    if not old_still_claimable:
                        stable_changed += 1
                        if stable_changed >= 2:
                            task["diem_danh"] = "CLAIMED"
                            task["diem_danh_error"] = None
                            return
                    else:
                        stable_changed = 0

                    _wait_interruptibly(context, interval)

                LOGGER.warning(
                    "Phúc lợi/Điểm danh: ô chưa đổi sau click lần %d/%d detector=%s",
                    attempt,
                    checkin_click_retries,
                    detector,
                )

            raise RuntimeError(
                "Phúc lợi/Điểm danh: đã click ô phát sáng "
                f"{checkin_click_retries} lần nhưng ô không chuyển trạng thái"
            )

        def run_tax(task: dict[str, Any]) -> None:
            # Trưng thu thuế chỉ khả dụng trong các khung giờ do game quy định.
            # Ngoài giờ: bỏ qua bình thường, không mở mục, không làm scenario FAILED.
            if not tax_window_open():
                task["trung_thu_thue"] = "SKIPPED"
                task["trung_thu_thue_reason"] = "OUTSIDE_TIME_WINDOW"
                LOGGER.info(
                    "Phúc lợi/Trưng thu thuế skipped: outside windows %s",
                    ", ".join(str(item) for item in tax_windows),
                )
                return

            task["trung_thu_thue_reason"] = None

            # Trưng thu thuế nằm thấp hơn viewport ban đầu. Khi nó chưa được chọn,
            # dùng "Hoạt động giới hạn" (item ngay phía trên) làm mốc rồi chạm
            # xuống đúng một hàng; sau đó bắt buộc xác minh tab đã selected.
            selected = find_best(tax_titles, roi=tax_title_roi, score=tab_threshold)
            if selected is None:
                anchor = None
                for _ in range(max_menu_scrolls + 1):
                    anchor = find_best(tax_nav_anchor, roi=tax_nav_roi, score=tab_threshold)
                    if anchor is not None:
                        break
                    context.device.swipe(*scaled_point(170, 470), *scaled_point(170, 245), 350)
                    _wait_interruptibly(context, interval)

                if anchor is None:
                    task["trung_thu_thue"] = "NOT_PRESENT"
                    task["trung_thu_thue_reason"] = "ITEM_NOT_PRESENT"
                    return

                anchor_x, anchor_y = anchor[1].center
                row_step = max(50, int(round(76 * scale_y)))
                target_y = min(screen_height - 20, anchor_y + row_step)
                context.device.tap(anchor_x, target_y)
                _wait_interruptibly(context, interval)

                selected = wait_best(
                    tax_titles,
                    roi=tax_title_roi,
                    score=tab_threshold,
                    wait_timeout=open_timeout,
                )
                if selected is None:
                    raise RuntimeError(
                        "Phúc lợi/Trưng thu thuế: đã chạm theo mốc menu nhưng tab không chuyển sang selected"
                    )

            state = wait_best(
                (tax_claim, tax_claimed, tax_not_ready),
                roi=tax_action_roi,
                score=state_threshold,
            )
            if state is None:
                raise RuntimeError("Phúc lợi/Trưng thu thuế: không xác định được trạng thái nút")

            if state[0] == tax_claim:
                tap_match(state[1])
                deadline = time.monotonic() + timeout
                while time.monotonic() <= deadline:
                    if dismiss_reward(tax_reward):
                        break
                    if find_best(tax_claimed, roi=tax_action_roi, score=state_threshold) is not None:
                        break
                    _wait_interruptibly(context, interval)

                if wait_best(tax_claimed, roi=tax_action_roi, score=state_threshold) is None:
                    raise RuntimeError(
                        "Phúc lợi/Trưng thu thuế: bấm Trưng thu nhưng không xác nhận được Đã trưng thu"
                    )
                task["trung_thu_thue"] = "CLAIMED"
                task["trung_thu_thue_reason"] = None
            elif state[0] == tax_claimed:
                task["trung_thu_thue"] = "CLAIMED"
                task["trung_thu_thue_reason"] = None
            else:
                # Đang đúng khung giờ nhưng UI vẫn báo chưa thể trưng thu.
                # Đây là điều kiện game, không phải lỗi automation.
                task["trung_thu_thue"] = "PENDING"
                task["trung_thu_thue_reason"] = "NOT_AVAILABLE_IN_CURRENT_WINDOW"

        def close_to_home() -> None:
            """Đóng panel Phúc lợi có xác minh; tự phục hồi nếu nút X không ăn tap."""

            def normalize_by_restart(reason: str) -> None:
                # Không bấm Back/tọa độ mù khi trạng thái giao diện không chắc chắn.
                # Restart riêng app không đăng xuất account hiện tại; sau đó dùng
                # finish_login để chứng minh HOME ổn định trước khi tiếp tục.
                LOGGER.warning("Phúc lợi: fallback restart để về HOME (%s)", reason)
                context.device.stop_app(package)
                _wait_interruptibly(
                    context,
                    max(0.2, float(params.get("restart_delay", 1.0))),
                )
                context.device.start_app(package, activity)
                _wait_interruptibly(context, interval)

                login_activity = str(params.get(
                    "login_activity",
                    "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity",
                ))
                if context.device.get_current_activity() == login_activity:
                    raise RuntimeError(
                        "Phúc lợi: session hết hạn khi chuẩn hóa về HOME"
                    )

                ready = ActionRegistry._finish_login(context, {
                    "timeout": float(params.get("home_timeout", 180.0)),
                    "interval": interval,
                    "stable_frames": 2,
                    "home_threshold": home_threshold,
                })
                if not ready.success:
                    raise RuntimeError(
                        "Phúc lợi: không thể chuẩn hóa về HOME sau popup/màn hình dở: "
                        + ready.message
                    )

            # Lỗi thực tế: X được nhận diện và tap một lần nhưng game đôi lúc không
            # nhận tap (animation/frame transition). Code cũ sau đó chỉ chờ HOME đến
            # timeout nên FAIL dù panel vẫn còn mở. Bản này chỉ tap lại khi chính
            # nút X vẫn được nhận diện, tối đa vài lần; nếu vẫn không đóng thì
            # restart app để phục hồi cùng session.
            max_close_taps = max(1, int(params.get("max_close_taps", 4)))
            close_retry_delay = max(
                interval,
                float(params.get("close_retry_delay", 0.8)),
            )
            stable_required = max(2, int(params.get("home_stable_frames", 2)))
            stable = 0
            close_taps = 0
            deadline = time.monotonic() + timeout

            while time.monotonic() <= deadline:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")

                home_ok = (
                    find_best(home_marker, score=home_threshold) is not None
                )
                close_match = find_best(
                    panel_close,
                    roi=close_roi,
                    score=close_threshold,
                )

                if home_ok and close_match is None:
                    stable += 1
                    if stable >= stable_required:
                        return
                    _wait_interruptibly(context, interval)
                    continue

                stable = 0

                if close_match is not None:
                    if close_taps >= max_close_taps:
                        normalize_by_restart(
                            f"nút X vẫn còn sau {close_taps} lần tap"
                        )
                        return

                    close_taps += 1
                    LOGGER.info(
                        "Phúc lợi: tap nút đóng lần %d/%d confidence=%.4f center=%s",
                        close_taps,
                        max_close_taps,
                        float(getattr(close_match[1], "confidence", 0.0)),
                        close_match[1].center,
                    )
                    tap_match(close_match[1])
                    _wait_interruptibly(context, close_retry_delay)
                    continue

                # Không thấy HOME và cũng không thấy nút đóng: có thể reward popup
                # hoặc frame dở đang che panel. Không click mù; thử chờ ngắn trước.
                _wait_interruptibly(context, interval)

            normalize_by_restart("hết thời gian chờ đóng panel")

        raw, task = read_runtime()

        # Chế độ checkin_only được giữ để tương thích với scenario cũ nếu còn file
        # ngoài patch. Luồng chính hiện tại không gọi Điểm danh riêng; Điểm danh
        # được xử lý bên trong PHUC_LOI sau Tam Quốc Lệnh.
        if checkin_only and task.get("diem_danh") in {"CLAIMED", "ALREADY_DONE", "DONE"}:
            return ActionResult(
                True,
                "phuc_loi",
                "Điểm danh đã hoàn thành trong runtime; bỏ qua",
                dict(task),
            )

        # Khi resume sau khi đã hoàn tất toàn bộ Phúc lợi nhưng chưa kịp logout,
        # không mở lại panel và không nhận lặp.
        if not checkin_only and task.get("status") == "DONE_FOR_NOW":
            return ActionResult(
                True,
                "phuc_loi",
                "Phúc lợi đã hoàn thành trong runtime; bỏ qua",
                dict(task),
            )

        task["status"] = "IN_PROGRESS"
        task["error"] = None
        save_runtime(raw)

        try:
            ensure_welfare_open()

            if checkin_only:
                run_checkin(task)
                save_runtime(raw)
                close_to_home()
                task["status"] = "PARTIAL"
                task["error"] = None
                save_runtime(raw)
                return ActionResult(
                    True,
                    "phuc_loi",
                    f"Điểm danh: {task.get('diem_danh')} và đã trở về HOME",
                    dict(task),
                )

            run_bao(task)
            save_runtime(raw)
            run_online(task)
            save_runtime(raw)

            # Điểm danh là task con độc lập. Nếu nhận diện/click Điểm danh vẫn lỗi,
            # không được chặn Trưng thu thuế, đóng panel và Đăng xuất của account.
            checkin_error = None
            if not skip_checkin:
                try:
                    run_checkin(task)
                except ActionStopRequested:
                    raise
                except Exception as exc:
                    checkin_error = str(exc)
                    task["diem_danh"] = "FAILED"
                    task["diem_danh_error"] = checkin_error
                    LOGGER.error("Phúc lợi/Điểm danh non-fatal failure: %s", exc)
                save_runtime(raw)

            run_tax(task)
            save_runtime(raw)
            close_to_home()

            if checkin_error:
                task["status"] = "PARTIAL"
                task["error"] = checkin_error
                save_runtime(raw)
                return ActionResult(
                    True,
                    "phuc_loi",
                    "Phúc lợi hoàn tất các mục còn lại; Điểm danh FAILED nhưng không chặn logout: "
                    + checkin_error,
                    dict(task),
                )

            task["status"] = "DONE_FOR_NOW"
            task["error"] = None
            save_runtime(raw)
            return ActionResult(
                True,
                "phuc_loi",
                "Đã kiểm tra/xử lý Phúc lợi và trở về HOME",
                dict(task),
            )
        except ActionStopRequested:
            task["status"] = "PARTIAL"
            task["error"] = "Stop requested"
            save_runtime(raw)
            raise
        except Exception as exc:
            task["status"] = "PARTIAL" if checkin_only else "FAILED"
            task["error"] = str(exc)
            save_runtime(raw)
            return ActionResult(False, "phuc_loi", str(exc), dict(task))

    @staticmethod
    def _reset_day_logout(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """At game-day rollover, normalize any screen to HOME, then verify logout."""
        package = str(params.get("package", "com.daichien.mobile"))
        activity = str(params.get("activity", "com.qtz.game.main.Logo"))
        login_activity = str(params.get(
            "login_activity", "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"
        ))
        if context.device.get_current_activity() == login_activity:
            return ActionResult(True, "reset_day_logout", "Already at authentication Activity")

        # Arbitrary in-game screens are not safe to unwind with blind Back presses.
        # Restart only the target app, then accept HOME through the normal verified gate.
        context.device.stop_app(package)
        time.sleep(max(0.1, float(params.get("restart_delay", 1.0))))
        context.device.start_app(package, activity)

        # Sau restart có hai trạng thái hợp lệ: session cũ còn sống -> về HOME,
        # hoặc session đã hết -> SDK AuthenActivity xuất hiện. Trước đây nhánh thứ
        # hai bị chờ HOME đến timeout dù thực tế đã ở đúng màn hình đăng nhập.
        probe_timeout = max(2.0, float(params.get("surface_probe_timeout", 15.0)))
        probe_interval = max(0.1, float(params.get("interval", 1.0)))
        probe_deadline = time.monotonic() + probe_timeout
        while time.monotonic() <= probe_deadline:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            if context.device.get_current_activity() == login_activity:
                return ActionResult(
                    True,
                    "reset_day_logout",
                    "Authentication Activity appeared after restart",
                    {"normalized_to_home": False, "already_logged_out": True},
                )
            if ActionRegistry._template(
                context,
                "dc3q/common/home_marker_noi_chinh.png",
                float(params.get("home_threshold", 0.75)),
            ) is not None:
                break
            time.sleep(probe_interval)

        ready = ActionRegistry._finish_login(context, {
            "timeout": float(params.get("home_timeout", 180.0)),
            "interval": float(params.get("interval", 1.0)),
            "stable_frames": 2,
            "home_threshold": float(params.get("home_threshold", 0.75)),
        })
        if not ready.success:
            # Session có thể hết đúng lúc finish_login đang chờ.
            if context.device.get_current_activity() == login_activity:
                return ActionResult(
                    True,
                    "reset_day_logout",
                    "Authentication Activity appeared while normalizing",
                    {"normalized_to_home": False, "already_logged_out": True},
                )
            return ActionResult(False, "reset_day_logout", ready.message)
        logged_out = ActionRegistry._logout_account(context, {
            "timeout": float(params.get("logout_timeout", 60.0)),
            "interval": float(params.get("interval", 1.0)),
        })
        return ActionResult(
            logged_out.success,
            "reset_day_logout",
            logged_out.message,
            {"normalized_to_home": True},
        )

    @staticmethod
    def _keyevent(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        key = params.get("key", params.get("code"))
        if key is None:
            raise ValueError("keyevent requires 'key' or 'code'")
        context.device.keyevent(key)
        return ActionResult(True, "keyevent", data={"key": key})

    @staticmethod
    def _back(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        method = getattr(context.device, "press_back", None)
        if callable(method):
            method()
        else:
            context.device.keyevent(4)
        return ActionResult(True, "back")

    @staticmethod
    def _home(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        method = getattr(context.device, "press_home", None)
        if callable(method):
            method()
        else:
            context.device.keyevent(3)
        return ActionResult(True, "home")

    @staticmethod
    def _sleep(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        seconds = float(params.get("seconds", params.get("duration", params.get("value", 1.0))))
        if seconds < 0:
            raise ValueError("sleep duration cannot be negative")
        _wait_interruptibly(context, seconds)
        return ActionResult(True, "sleep", data={"seconds": seconds})

    @staticmethod
    def _start_app(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        package = str(_require(params, "package"))
        activity = params.get("activity")
        if activity is None:
            _call_first(context.device, ("start_app", "launch_app"), package)
        else:
            try:
                _call_first(context.device, ("start_app", "launch_app"), package, str(activity))
            except TypeError:
                _call_first(context.device, ("start_app", "launch_app"), f"{package}/{activity}")
        return ActionResult(True, "start_app", data={"package": package, "activity": activity})

    @staticmethod
    def _stop_app(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        package = str(_require(params, "package"))
        _call_first(context.device, ("stop_app", "force_stop"), package)
        return ActionResult(True, "stop_app", data={"package": package})

    @staticmethod
    def _tap_template(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        template = params.get("template", params.get("path"))
        if template is None:
            raise ValueError("tap_template requires 'template' or 'path'")

        timeout = max(0.0, float(params.get("timeout", 0.0)))
        interval = max(0.05, float(params.get("interval", 0.25)))
        deadline = time.monotonic() + timeout
        match = None

        while True:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            match = context.vision.find_template(
                template,
                threshold=params.get("threshold"),
                roi=params.get("roi"),
                scales=params.get("scales"),
                refresh=True,
            )
            if match is not None or time.monotonic() >= deadline:
                break
            time.sleep(interval)

        if match is None:
            return ActionResult(False, "tap_template", f"Template not found: {template}")

        offset_x = int(params.get("offset_x", 0))
        offset_y = int(params.get("offset_y", 0))
        x = match.center[0] + offset_x
        y = match.center[1] + offset_y
        context.device.tap(x, y)
        return ActionResult(
            True,
            "tap_template",
            data={"template": str(template), "x": x, "y": y, "confidence": match.confidence},
        )

    @staticmethod
    def _tap_yolo(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        class_name = params.get("class_name", params.get("class", params.get("target")))
        detection = context.vision.detect_one(
            class_name,
            confidence=params.get("confidence"),
            iou=params.get("iou"),
            roi=params.get("roi"),
            refresh=True,
        )
        if detection is None:
            return ActionResult(False, "tap_yolo", f"YOLO target not found: {class_name}")

        offset_x = int(params.get("offset_x", 0))
        offset_y = int(params.get("offset_y", 0))
        x = detection.center[0] + offset_x
        y = detection.center[1] + offset_y
        context.device.tap(x, y)
        return ActionResult(
            True,
            "tap_yolo",
            data={
                "class_id": detection.class_id,
                "class_name": detection.class_name,
                "confidence": detection.confidence,
                "x": x,
                "y": y,
            },
        )

    @staticmethod
    def _set_variable(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        key = str(_require(params, "key"))
        value = params.get("value")
        context.variables[key] = value
        return ActionResult(True, "set_variable", data={"key": key, "value": value})

    @staticmethod
    def _delete_variable(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        key = str(_require(params, "key"))
        existed = key in context.variables
        context.variables.pop(key, None)
        return ActionResult(True, "delete_variable", data={"key": key, "existed": existed})

    @staticmethod
    def _log(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        message = str(params.get("message", ""))
        level = str(params.get("level", "info")).lower()
        log_method = getattr(LOGGER, level, LOGGER.info)
        log_method(message)
        return ActionResult(True, "log", message=message)
