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
            "tam_quoc_lenh": self._tam_quoc_lenh,
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
            reward_name: str,
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
                if reward_name not in task["rewards"]:
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

            # If we initiated the free action in this run, the reward is known even
            # when the popup is skipped by the server/UI.
            if reward_name not in task["rewards"]:
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
