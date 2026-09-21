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
            close_center = ActionRegistry._profile_update_close_center(context)
            if close_center is not None:
                context.device.tap(*close_center)
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
            if context.device.get_current_activity() == login_activity:
                return ActionResult(True, "logout_account", "Returned to authentication Activity")
            time.sleep(interval)
        return ActionResult(False, "logout_account", "Confirmed change account but login Activity did not appear")

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
        ready = ActionRegistry._finish_login(context, {
            "timeout": float(params.get("home_timeout", 180.0)),
            "interval": float(params.get("interval", 1.0)),
            "stable_frames": 2,
        })
        if not ready.success:
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
        time.sleep(seconds)
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
