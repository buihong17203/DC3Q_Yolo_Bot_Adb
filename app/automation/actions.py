from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from app.core.game_day import RUNTIME_FILE_LOCK

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


def _next_checkin_day(last_marker_day: int, total_days: int = 30) -> int | None:
    """Return the next cell to click from the last recognized check-in marker."""
    total = max(1, int(total_days))
    last = int(last_marker_day)
    if last <= 0:
        return 1
    if last >= total:
        return None
    return last + 1


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
            "recover_to_home": self._recover_to_home,
            "tam_quoc_lenh": self._tam_quoc_lenh,
            "hoat_dong": self._hoat_dong,
            "phuc_loi": self._phuc_loi,
            "cua_hang": self._cua_hang,
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
        # LOGIN -> TAM_QUOC_LENH -> PHUC_LOI -> CUA_HANG -> LOGOUT.
        # Phúc lợi tự mở Hoạt động và đóng panel về HOME; Cửa hàng chỉ mở từ HOME.
        cua_hang = tasks.get("cua_hang") if isinstance(tasks.get("cua_hang"), dict) else {}
        if tam_quoc.get("status") != "DONE":
            return "TAM_QUOC_LENH"
        if phuc_loi.get("status") not in {"DONE_FOR_NOW", "DONE"}:
            return "PHUC_LOI"

        # Phúc lợi có Trưng thu thuế theo 3 khung giờ/ngày. Nếu account đã
        # hoàn tất một lần nhưng đang bước vào khung chưa claim, phải quay lại
        # Phúc lợi trước khi bỏ qua account.
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
            minute = now.hour * 60 + now.minute
            tax_start = None
            if 12 * 60 <= minute < 14 * 60:
                tax_start = "12:00"
            elif 18 * 60 <= minute < 20 * 60:
                tax_start = "18:00"
            elif 21 * 60 <= minute < 23 * 60:
                tax_start = "21:00"
            claimed = phuc_loi.get("trung_thu_thue_claimed_slots", [])
            slot_key = f"{now.date().isoformat()}@{tax_start}" if tax_start else None
            if slot_key and slot_key not in (claimed if isinstance(claimed, list) else []):
                return "PHUC_LOI"
        except Exception:
            pass

        if cua_hang.get("status") != "DONE":
            return "CUA_HANG"
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
        if seen("dc3q/targets/Cửa-Hàng/Cửa-Hàng-Gợi-Ý/screen/cua_hang_goi_y_tab_selected_alert.png", 0.76):
            return "CUA_HANG"
        if seen("dc3q/targets/Cửa-Hàng/Cửa-Hàng-Thời-Hạn/screen/button_cua_hang_thoi_han_alert.png", 0.76):
            return "CUA_HANG"
        if seen("dc3q/targets/Cửa-Hàng/Tiệm-Thần-Bí/screen/tiem_than_bi_selected.png", 0.76):
            return "CUA_HANG"
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
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            ZoneInfo = None

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
            import os
            with RUNTIME_FILE_LOCK:
                for attempt in range(20):
                    temporary = runtime_file.with_name(
                        f"{runtime_file.name}.{os.getpid()}.{id(raw)}.{attempt}.tmp"
                    )
                    try:
                        with temporary.open("w", encoding="utf-8") as handle:
                            json.dump(raw, handle, ensure_ascii=False, indent=2)
                            handle.write("\n")
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, runtime_file)
                        return
                    except PermissionError:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                        if attempt >= 19:
                            raise
                        time.sleep(min(1.0, 0.08 * (attempt + 1)))
                    except Exception:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise

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
    def _hoat_dong(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Open and verify Hoạt động before the HOME-based Cửa hàng step."""
        import json
        from pathlib import Path

        account_id = str(params.get("account_id", ""))
        runtime_file = Path(str(params.get("runtime_file", ""))) if params.get("runtime_file") else None
        threshold = float(params.get("threshold", 0.82))
        timeout = max(2.0, float(params.get("timeout", 12.0)))
        interval = max(0.05, float(params.get("interval", 0.5)))
        home_marker = "dc3q/common/home_marker_noi_chinh.png"
        home_entry = "dc3q/targets/Hoạt-Động/screen/home_hoat_dong_entry.png"
        panel_close = "dc3q/targets/Hoạt-Động/screen/event_panel_close_button.png"

        def persist(status: str, error: str | None = None) -> None:
            if runtime_file is None or not account_id or not runtime_file.is_file():
                return
            raw = json.loads(runtime_file.read_text(encoding="utf-8"))
            for row in raw.get("accounts", []):
                if isinstance(row, dict) and str(row.get("id")) == account_id:
                    task = row.setdefault("tasks", {}).setdefault("hoat_dong", {})
                    task["status"] = status
                    task["error"] = error
                    break
            tmp = runtime_file.with_suffix(runtime_file.suffix + ".tmp")
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(runtime_file)

        def find(path, score=threshold, roi=None):
            try:
                return context.vision.find_template(path, threshold=score, roi=roi, refresh=True)
            except TypeError:
                return context.vision.find_template(path, threshold=score, roi=roi)

        def wait(paths, score=threshold, timeout_value=12.0, roi=None):
            paths = (paths,) if isinstance(paths, str) else tuple(paths)
            deadline = time.monotonic() + timeout_value
            while time.monotonic() <= deadline:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")
                for path in paths:
                    m = find(path, score=score, roi=roi)
                    if m is not None:
                        return m
                _wait_interruptibly(context, interval)
            return None

        try:
            if find(panel_close, score=0.80, roi=(850, 0, 960, 120)) is not None:
                persist("DONE")
                return ActionResult(True, "hoat_dong", "Hoạt động đã mở", {"status": "DONE"})
            if find(home_marker, score=0.72) is None:
                raise RuntimeError("Hoạt động: không xác nhận được HOME trước khi mở")
            entry = wait(home_entry, score=float(params.get("entry_threshold", 0.80)), timeout_value=timeout, roi=(0, 300, 180, 540))
            if entry is None:
                raise RuntimeError("Hoạt động: không nhận diện được nút Hoạt động trên HOME")
            context.device.tap(*entry.center)
            _wait_interruptibly(context, interval)
            if wait(panel_close, score=float(params.get("close_threshold", 0.84)), timeout_value=timeout, roi=(850, 0, 960, 120)) is None:
                raise RuntimeError("Hoạt động: không xác nhận được panel đã mở")
            persist("DONE")
            return ActionResult(True, "hoat_dong", "Đã mở và xác nhận Hoạt động", {"status": "DONE"})
        except ActionStopRequested:
            persist("PARTIAL", "Stop requested")
            raise
        except Exception as exc:
            persist("FAILED", str(exc))
            return ActionResult(False, "hoat_dong", str(exc), {"status": "FAILED"})

    @staticmethod
    def _cua_hang(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Run the requested Thương thành purchases/checks without spending unintended currency.

        Scope requested by the operator:
        1. Cửa hàng gợi ý -> Quà hay hàng ngày -> claim the FREE button only.
        2. Cửa hàng thời hạn -> inspect Ngày/Tuần/Tháng and claim a FREE button when
           the game exposes one. Never click a paid price in this section.
        3. Tiệm thần bí -> buy the bundle "Chiêu hiền lệnh x3" priced at 180 Tướng Hồn,
           exactly once when it is available and not already purchased.
        """
        import json
        from pathlib import Path

        account_id = str(_require(params, "account_id"))
        runtime_file = Path(str(_require(params, "runtime_file")))
        package = str(params.get("package", "com.daichien.mobile"))
        threshold = float(params.get("threshold", 0.82))
        state_threshold = float(params.get("state_threshold", 0.82))
        timeout = max(2.0, float(params.get("timeout", 20.0)))
        interval = max(0.05, float(params.get("interval", 0.5)))
        entry_timeout = max(2.0, float(params.get("entry_timeout", 12.0)))
        required = bool(params.get("required", True))

        def load_runtime() -> tuple[dict[str, Any], dict[str, Any]]:
            raw = json.loads(runtime_file.read_text(encoding="utf-8"))
            for row in raw.get("accounts", []):
                if isinstance(row, dict) and str(row.get("id")) == account_id:
                    tasks = row.setdefault("tasks", {})
                    task = tasks.setdefault("cua_hang", {})
                    defaults = {
                        "status": "NOT_STARTED",
                        "cua_hang_goi_y": "NOT_STARTED",
                        "cua_hang_goi_y_reason": None,
                        "cua_hang_thoi_han": "NOT_STARTED",
                        "cua_hang_thoi_han_tabs": {},
                        "cua_hang_thoi_han_reason": None,
                        "tiem_than_bi": "NOT_STARTED",
                        "tiem_than_bi_reason": None,
                        "chieu_hien_lenh_bought": 0,
                        "error": None,
                    }
                    changed = False
                    for key, value in defaults.items():
                        if key not in task:
                            task[key] = value
                            changed = True
                    if not isinstance(task.get("cua_hang_thoi_han_tabs"), dict):
                        task["cua_hang_thoi_han_tabs"] = {}
                        changed = True
                    if changed:
                        save_runtime(raw)
                    return raw, task
            raise KeyError(f"Runtime account not found: {account_id}")

        def save_runtime(raw: dict[str, Any]) -> None:
            import os
            with RUNTIME_FILE_LOCK:
                for attempt in range(20):
                    temporary = runtime_file.with_name(
                        f"{runtime_file.name}.{os.getpid()}.{id(raw)}.{attempt}.tmp"
                    )
                    try:
                        with temporary.open("w", encoding="utf-8") as handle:
                            json.dump(raw, handle, ensure_ascii=False, indent=2)
                            handle.write("\n")
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, runtime_file)
                        return
                    except PermissionError:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                        if attempt >= 19:
                            raise
                        time.sleep(min(1.0, 0.08 * (attempt + 1)))
                    except Exception:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise

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

        def roi(ref: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            x1, y1, x2, y2 = ref
            return (
                max(0, int(round(x1 * scale_x))),
                max(0, int(round(y1 * scale_y))),
                min(screen_width, int(round(x2 * scale_x))),
                min(screen_height, int(round(y2 * scale_y))),
            )

        def point(ref: tuple[int, int]) -> tuple[int, int]:
            return int(round(ref[0] * scale_x)), int(round(ref[1] * scale_y))

        def find(path: str, *, area=None, score: float = threshold):
            kwargs = {"threshold": score, "roi": area, "scales": match_scales, "refresh": True}
            try:
                return context.vision.find_template(path, **kwargs)
            except TypeError:
                kwargs.pop("scales", None)
                return context.vision.find_template(path, **kwargs)

        def wait(path_or_paths, *, area=None, score: float = threshold, wait_timeout: float = timeout):
            paths = (path_or_paths,) if isinstance(path_or_paths, str) else tuple(path_or_paths)
            deadline = time.monotonic() + max(0.0, float(wait_timeout))
            while time.monotonic() <= deadline:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")
                for path in paths:
                    match = find(path, area=area, score=score)
                    if match is not None:
                        return path, match
                _wait_interruptibly(context, interval)
            return None

        def absent(path: str, *, area=None, score: float = threshold, wait_timeout: float = 4.0) -> bool:
            deadline = time.monotonic() + max(0.0, float(wait_timeout))
            while time.monotonic() <= deadline:
                if _stop_requested(context):
                    raise ActionStopRequested("Stop requested")
                if find(path, area=area, score=score) is None:
                    return True
                _wait_interruptibly(context, interval)
            return False

        def tap_match(match) -> None:
            context.device.tap(*match.center)
            _wait_interruptibly(context, interval)

        root = "dc3q/targets/Cửa-Hàng/"
        goi_y = root + "Cửa-Hàng-Gợi-Ý/"
        thoi_han = root + "Cửa-Hàng-Thời-Hạn/"
        than_bi = root + "Tiệm-Thần-Bí/"
        store_selected = goi_y + "screen/cua_hang_goi_y_tab_selected_alert.png"
        # Entry chính xác của Cửa hàng nằm ở HOME; crop này được lấy trực tiếp
        # từ full_screen_base_main_hall.png trong RAR tổng. Nếu badge alert thay
        # đổi làm template không match, chỉ dùng tọa độ này sau khi HOME đã được
        # xác nhận, không click tọa độ mù từ một màn hình lạ.
        store_entry = "dc3q/start/screen/home_cua_hang_entry.png"
        store_close = "dc3q/targets/Cửa-Hàng/screen_panel_close.png"
        activity_close = "dc3q/targets/Hoạt-Động/screen/event_panel_close_button.png"

        goi_y_free = goi_y + "screen/mien_phi_button_enabled.png"
        goi_y_claimed = goi_y + "screen/da_mua_button_disabled.png"
        goi_y_reward = goi_y + "screen/chuc_mung_nhan_duoc_banner.png"

        thoi_han_entry = thoi_han + "screen/button_cua_hang_thoi_han_alert.png"
        thoi_han_entry_plain = thoi_han + "screen/button_cua_hang_thoi_han.png"
        tab_day = thoi_han + "screen/tab_ngay_selected.png"
        tab_week = thoi_han + "screen/tab_tuan_selected.png"
        tab_week_unselected = thoi_han + "screen/tab_tuan_unselected.png"
        tab_month = thoi_han + "screen/tab_thang_selected.png"
        tab_month_unselected = thoi_han + "screen/tab_thang_unselected.png"
        thoi_han_free = thoi_han + "screen/button_mien_phi.png"
        thoi_han_claimed = thoi_han + "screen/button_da_mua_disabled.png"
        thoi_han_reward = thoi_han + "screen/banner_chuc_mung_nhan_duoc.png"

        than_bi_selected = than_bi + "screen/tiem_than_bi_selected.png"
        mystery_unbought = tuple(
            than_bi + f"full screen/Chưa-Mua/full_screen_chua_mua_shop_tuong_hon_{i:02d}.png"
            for i in range(1, 9)
        )
        mystery_bought = tuple(
            than_bi + "full screen/Đã-Mua/" + name
            for name in (
                "full_screen_da_mua_shop_tang_tinh_bach_huong_dan_chien_hon_lenh.png",
                "full_screen_da_mua_shop_tang_tinh_bi_kip_thien_thu_tang_exp_tui_qua.png",
                "full_screen_da_mua_shop_tang_tinh_hop_da_co_phieu_chieu_mo_kiem_do.png",
                "full_screen_da_mua_shop_tang_tinh_manh_bao_vat_lenh_bai_son_ha_lenh.png",
                "full_screen_da_mua_shop_tang_tinh_manh_bao_vat_son_ha_lenh_ngoc_dong.png",
                "full_screen_da_mua_shop_tang_tinh_ngoc_dong_sach_kinh_nghiem_manh_bao_vat.png",
                "full_screen_da_mua_shop_tang_tinh_tang_exp_hon_thach_bach_huong_dan.png",
                "full_screen_da_mua_shop_tang_tinh_than_thao_da_tinh_luyen_tui_qua.png",
            )
        )
        chieu_hien_cards = (
            than_bi + "screen/shop_chieu_hien_lenh_top_right.png",
            than_bi + "screen/shop_chieu_hien_lenh_bottom_right.png",
        )
        buy_dialog_header = than_bi + "screen/mua_dialog_header.png"
        buy_confirm_button = than_bi + "screen/mua_confirm_button.png"

        raw, task = load_runtime()
        if task.get("status") == "DONE":
            return ActionResult(True, "cua_hang", "Cửa hàng đã hoàn thành trong runtime", dict(task))

        task["status"] = "IN_PROGRESS"
        task["error"] = None
        save_runtime(raw)

        try:
            # Hoạt động được mở ngay trước Cửa hàng theo luồng account mới.
            # Vì entry Cửa hàng nằm trên HOME trong RAR tổng, phải đóng panel
            # Hoạt động bằng nút X đã nhận diện, sau đó mới tìm entry Cửa hàng.
            activity_panel = find(activity_close, area=roi((800, 0, 960, 120)), score=0.80)
            if activity_panel is not None:
                tap_match(activity_panel)
                if wait("dc3q/common/home_marker_noi_chinh.png", area=None, score=0.72, wait_timeout=entry_timeout) is None:
                    raise RuntimeError("Cửa hàng: không trở về HOME sau khi đóng Hoạt động")

            # Resume if the store is already open. Otherwise use the verified
            # HOME entry from the base archive + supplied crop.
            already_open = (
                find(store_selected, area=roi((0, 80, 950, 210)), score=0.74) is not None
                or find(thoi_han_entry, area=roi((0, 80, 220, 220)), score=0.74) is not None
                or find(than_bi_selected, area=roi((0, 0, 180, 420)), score=0.74) is not None
            )
            if not already_open:
                entry = wait(store_entry, area=roi((70, 430, 220, 540)), score=float(params.get("entry_threshold", 0.80)), wait_timeout=entry_timeout)
                if entry is not None:
                    tap_match(entry[1])
                else:
                    home = find("dc3q/common/home_marker_noi_chinh.png", score=0.72)
                    if home is None:
                        message = "Cửa hàng: không nhận diện được entry và cũng không chứng minh được HOME"
                        if required:
                            raise RuntimeError(message)
                        task["status"] = "SKIPPED"
                        task["error"] = message
                        save_runtime(raw)
                        return ActionResult(True, "cua_hang", message, dict(task))
                    context.device.tap(*point(tuple(params.get("home_store_entry_point", (140, 495)))))
                    _wait_interruptibly(context, interval)
                if wait((store_selected, thoi_han_entry, than_bi_selected), area=roi((0, 60, 950, 540)), score=0.70, wait_timeout=entry_timeout) is None:
                    raise RuntimeError("Cửa hàng: đã mở entry nhưng không xác nhận được màn Thương thành")

            # 1) Cửa hàng gợi ý -> chỉ lấy Quà hay hàng ngày khi nút thật sự là Miễn phí.
            # Gợi ý là tab đầu tiên. Không để template selected làm blocker;
            # nếu chưa ở tab này thì click đúng vị trí rồi chờ chuyển màn ngắn.
            if find(store_selected, area=roi((0, 50, 180, 190)), score=0.62) is None:
                context.device.tap(*point((70, 90)))
                _wait_interruptibly(context, 0.8)

            free = find(goi_y_free, area=roi((700, 80, 950, 230)), score=state_threshold)
            if free is None:
                if find(goi_y_claimed, area=roi((700, 80, 950, 230)), score=state_threshold) is not None:
                    task["cua_hang_goi_y"] = "CLAIMED"
                    task["cua_hang_goi_y_reason"] = "ALREADY_CLAIMED"
                else:
                    task["cua_hang_goi_y"] = "CHECKED"
                    task["cua_hang_goi_y_reason"] = "FREE_BUTTON_NOT_PRESENT"
            else:
                tap_match(free)
                reward = wait(goi_y_reward, area=roi((250, 80, 800, 500)), score=0.76, wait_timeout=timeout)
                claimed = find(goi_y_claimed, area=roi((700, 80, 950, 230)), score=0.78) is not None
                if reward is None and not claimed:
                    raise RuntimeError("Cửa hàng gợi ý: đã bấm Miễn phí nhưng không xác nhận được nhận quà/Đã mua")
                task["cua_hang_goi_y"] = "CLAIMED"
                task["cua_hang_goi_y_reason"] = None
            save_runtime(raw)

            # 2) Cửa hàng thời hạn -> mở và kiểm tra Ngày/Tuần/Tháng.
            # Không dùng selected-template làm điều kiện chặn; các tab được bấm trực tiếp.
            context.device.tap(*point((70, 145)))
            _wait_interruptibly(context, 0.8)

            tab_specs = (
                ("ngay", (250, 80)),
                ("tuan", (380, 80)),
                ("thang", (520, 80)),
            )
            for tab_name, tab_point in tab_specs:
                context.device.tap(*point(tab_point))
                _wait_interruptibly(context, 0.8)
                free = find(thoi_han_free, area=roi((120, 250, 360, 440)), score=0.64)
                claimed = find(thoi_han_claimed, area=roi((120, 250, 360, 440)), score=0.64)
                if free is not None:
                    tap_match(free)
                    _wait_interruptibly(context, 0.8)
                    tab_state = "CLAIMED"
                elif claimed is not None:
                    tab_state = "ALREADY_CLAIMED"
                else:
                    # Không có Miễn phí: tuyệt đối không bấm vật phẩm có giá.
                    tab_state = "CHECKED"
                task.setdefault("cua_hang_thoi_han_tabs", {})[tab_name] = tab_state
                save_runtime(raw)

            task["cua_hang_thoi_han"] = "DONE"
            task["cua_hang_thoi_han_reason"] = None

            # 3) Tiệm thần bí -> kéo lên một đoạn, tìm đúng Chiêu hiền lệnh x3 / 180.
            if find(than_bi_selected, area=roi((0, 250, 190, 400)), score=0.62) is None:
                context.device.tap(*point((70, 310)))
                _wait_interruptibly(context, 0.8)

            # Người dùng yêu cầu kéo lên một chút để hiện đầy đủ khu vực mua.
            context.device.swipe(*point((850, 455)), *point((850, 335)), 450)
            _wait_interruptibly(context, 1.0)

            if int(task.get("chieu_hien_lenh_bought", 0) or 0) >= 3:
                task["tiem_than_bi"] = "CLAIMED"
                task["tiem_than_bi_reason"] = "ALREADY_BOUGHT_3"
            else:
                card_match = None
                for card_template in chieu_hien_cards:
                    card_match = find(card_template, area=roi((600, 80, 960, 535)), score=0.62)
                    if card_match is not None:
                        break
                if card_match is None:
                    # Một lần kéo nhỏ thứ hai nếu card vẫn bị che.
                    context.device.swipe(*point((850, 420)), *point((850, 350)), 350)
                    _wait_interruptibly(context, 0.8)
                    for card_template in chieu_hien_cards:
                        card_match = find(card_template, area=roi((600, 80, 960, 535)), score=0.62)
                        if card_match is not None:
                            break

                if card_match is None:
                    task["tiem_than_bi"] = "CHECKED"
                    task["tiem_than_bi_reason"] = "CHIEU_HIEN_180_NOT_VISIBLE"
                else:
                    tap_match(card_match)
                    dialog = wait(buy_dialog_header, area=roi((350, 130, 650, 240)), score=0.62, wait_timeout=5.0)
                    if dialog is None:
                        raise RuntimeError("Tiệm thần bí: bấm Chiêu hiền lệnh nhưng không mở khung Mua")
                    # Đây chính là nút giá 180 dùng để mua, không phải nút item khác.
                    price = wait(buy_confirm_button, area=roi((380, 320, 620, 395)), score=0.62, wait_timeout=5.0)
                    if price is None:
                        raise RuntimeError("Tiệm thần bí: không tìm thấy nút giá 180 trong khung Mua")
                    tap_match(price)
                    _wait_interruptibly(context, 1.0)
                    if find(buy_dialog_header, area=roi((350, 130, 650, 240)), score=0.62) is not None:
                        raise RuntimeError("Tiệm thần bí: bấm giá nhưng khung Mua vẫn còn")
                    # Sau khi mua, card được đổi sang trạng thái Đã mua. Khi template
                    # xám không match vì animation, việc dialog biến mất vẫn là hậu kiểm
                    # an toàn hơn là mua thêm vật phẩm khác.
                    task["chieu_hien_lenh_bought"] = 3
                    task["tiem_than_bi"] = "CLAIMED"
                    task["tiem_than_bi_reason"] = "BOUGHT_3_FOR_180_TUONG_HON"
            save_runtime(raw)

            task["status"] = "DONE"
            task["error"] = None
            save_runtime(raw)

            # Close only after the store page has been verified. Reuse the known
            # diamond-X template; never tap an unverified corner.
            close = find(store_close, area=roi((850, 0, 970, 90)), score=0.62)
            if close is not None:
                tap_match(close)
            else:
                context.device.tap(*point((930, 35)))
                _wait_interruptibly(context, interval)
            if wait("dc3q/common/home_marker_noi_chinh.png", area=None, score=0.66, wait_timeout=entry_timeout) is None:
                raise RuntimeError("Cửa hàng: đã bấm X nhưng chưa xác nhận quay về HOME")

            return ActionResult(True, "cua_hang", "Đã hoàn thành Cửa hàng", dict(task))
        except ActionStopRequested:
            task["status"] = "PARTIAL"
            task["error"] = "Stop requested"
            save_runtime(raw)
            raise
        except Exception as exc:
            task["status"] = "PARTIAL"
            task["error"] = str(exc)
            save_runtime(raw)
            return ActionResult(False, "cua_hang", str(exc), dict(task))

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
        # Logic Điểm danh v4:
        # Không đo quầng sáng của ô "?" nữa. Xác định tiến độ bằng các marker
        # đã nhận thực tế trong từng ô:
        #   1) "Được báo bù" (template hiện có);
        #   2) dấu tick xanh (mask template mới).
        # Sau đó luôn bấm ô NGAY SAU marker cuối cùng theo thứ tự trái -> phải,
        # trên -> dưới. Nếu không có marker nào thì bấm ô ngày 1.
        checkin_badge_threshold = float(
            params.get("checkin_badge_threshold", params.get("checkin_claim_threshold", 0.62))
        )
        checkin_tick_threshold = float(params.get("checkin_tick_threshold", 0.80))
        checkin_days = max(1, int(params.get("checkin_days", 30)))
        checkin_grid_x = int(params.get("checkin_grid_x", 238))
        checkin_grid_y = int(params.get("checkin_grid_y", 201))
        checkin_cell_width = int(params.get("checkin_cell_width", 75))
        checkin_cell_height = int(params.get("checkin_cell_height", 75))
        checkin_grid_columns = max(1, int(params.get("checkin_grid_columns", 9)))
        checkin_click_retries = max(1, int(params.get("checkin_click_retries", 3)))

        # Giữ tham số cũ để tương thích YAML/runtime từ các bản trước.
        checkin_claim_threshold = float(params.get("checkin_claim_threshold", 0.68))
        checkin_cell_threshold = float(params.get("checkin_cell_threshold", 0.80))
        checkin_cell_margin = float(params.get("checkin_cell_margin", 0.05))
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

        tax_timezone_name = str(params.get("tax_timezone", "Asia/Ho_Chi_Minh")).strip()
        if ZoneInfo is not None:
            try:
                tax_timezone = ZoneInfo(tax_timezone_name)
            except Exception:
                LOGGER.warning(
                    "Phúc lợi/Trưng thu thuế: timezone %s không khả dụng; dùng timezone hệ thống",
                    tax_timezone_name,
                )
                tax_timezone = None
        else:
            tax_timezone = None

        def tax_now():
            return datetime.now(tax_timezone) if tax_timezone is not None else datetime.now().astimezone()

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

        parsed_tax_windows: list[tuple[int, int, str]] = []
        for raw_window in tax_windows:
            try:
                start_text, end_text = str(raw_window).split("-", 1)
            except ValueError as exc:
                raise ValueError(f"Invalid welfare tax window: {raw_window!r}") from exc
            start_text = start_text.strip()
            end_text = end_text.strip()
            start_minute = parse_clock(start_text)
            end_minute = parse_clock(end_text)
            if end_minute <= start_minute:
                raise ValueError(
                    f"Welfare tax window must end after start on the same day: {raw_window!r}"
                )
            parsed_tax_windows.append((start_minute, end_minute, start_text))

        def current_tax_window(now=None):
            current = now or tax_now()
            minute_of_day = current.hour * 60 + current.minute
            for start, end, start_text in parsed_tax_windows:
                if start <= minute_of_day < end:
                    return start, end, start_text, current
            return None

        def tax_window_open(now=None) -> bool:
            return current_tax_window(now) is not None

        def tax_slot_key(now=None) -> str | None:
            window = current_tax_window(now)
            if window is None:
                return None
            _, _, start_text, current = window
            return f"{current.date().isoformat()}@{start_text}"

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
                    "trung_thu_thue_claimed_slots": [],
                    "trung_thu_thue_last_attempt_at": None,
                    "error": None,
                }
                for key, value in defaults.items():
                    task.setdefault(key, value)
                # Xóa dữ liệu rewards fix cứng từ runtime cũ nếu còn tồn tại.
                task.pop("rewards", None)
                return raw, task
            raise KeyError(f"Runtime account not found: {account_id}")

        def save_runtime(raw: dict[str, Any]) -> None:
            import os
            with RUNTIME_FILE_LOCK:
                for attempt in range(20):
                    temporary = runtime_file.with_name(
                        f"{runtime_file.name}.{os.getpid()}.{id(raw)}.{attempt}.tmp"
                    )
                    try:
                        with temporary.open("w", encoding="utf-8") as handle:
                            json.dump(raw, handle, ensure_ascii=False, indent=2)
                            handle.write("\n")
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, runtime_file)
                        return
                    except PermissionError:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                        if attempt >= 19:
                            raise
                        time.sleep(min(1.0, 0.08 * (attempt + 1)))
                    except Exception:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise

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
            # Quy tắc bắt buộc: sau khi mở Hoạt động, việc đầu tiên là kiểm tra
            # tab Phúc lợi. Nếu đã được chọn thì tuyệt đối không tap lại. Nếu chưa
            # chọn thì chỉ tap đúng vị trí Phúc lợi một lần rồi xác nhận selected.
            # Không kiểm tra selected trước khi chứng minh panel Hoạt động đang mở,
            # tránh match nhầm trên HOME/khung chuyển cảnh.
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

            selected = find_best(welfare_selected, roi=welfare_nav_roi, score=tab_threshold)
            if selected is not None:
                LOGGER.info("Phúc lợi: tab Phúc lợi đã được chọn, không tap lại")
                return

            # Chỉ chọn Phúc lợi. Hai tab Ngày lễ/Hoạt động không được thao tác.
            context.device.tap(*scaled_point(65, 180))
            _wait_interruptibly(context, interval)
            if wait_best(welfare_selected, roi=welfare_nav_roi, score=tab_threshold, wait_timeout=open_timeout) is None:
                raise RuntimeError("Phúc lợi: đã tap tab nhưng không xác nhận được Phúc lợi đã được chọn")

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

        def load_checkin_tick_mask():
            """
            Load the green check-mask used to recognize already-claimed cells.

            The mask is intentionally separate from the reward artwork: the item
            under the tick changes from day to day, while the green check shape is
            stable.
            """
            try:
                import cv2
                import numpy as np
            except Exception:
                LOGGER.exception("Phúc lợi/Điểm danh: OpenCV/numpy không khả dụng cho tick detector")
                return None

            tick_file = (
                Path(__file__).resolve().parents[2]
                / "assets"
                / "templates"
                / "dc3q"
                / "targets"
                / "Hoạt-Động"
                / "Phúc-Lợi"
                / "screen"
                / "Điểm-Danh"
                / "screen_diem_danh_claimed_tick_mask.png"
            )
            mask = cv2.imread(str(tick_file), cv2.IMREAD_GRAYSCALE)
            if mask is None or mask.size == 0:
                LOGGER.error("Phúc lợi/Điểm danh: không đọc được tick mask: %s", tick_file)
                return None
            return mask

        checkin_tick_mask_cache = None
        checkin_tick_mask_scaled = None
        checkin_tick_mask_scale = None

        def get_checkin_tick_mask():
            nonlocal checkin_tick_mask_cache
            nonlocal checkin_tick_mask_scaled
            nonlocal checkin_tick_mask_scale

            if checkin_tick_mask_cache is None:
                checkin_tick_mask_cache = load_checkin_tick_mask()
            if checkin_tick_mask_cache is None:
                return None

            # The project reference frame is 960x540. Use the smaller scale so
            # the tick remains fully inside a cell even if the emulator stretches.
            current_scale = round(float(ui_scale), 4)
            if (
                checkin_tick_mask_scaled is None
                or checkin_tick_mask_scale != current_scale
            ):
                import cv2

                if abs(current_scale - 1.0) < 0.001:
                    scaled = checkin_tick_mask_cache
                else:
                    scaled = cv2.resize(
                        checkin_tick_mask_cache,
                        None,
                        fx=current_scale,
                        fy=current_scale,
                        interpolation=cv2.INTER_NEAREST,
                    )
                checkin_tick_mask_scaled = scaled
                checkin_tick_mask_scale = current_scale

            return checkin_tick_mask_scaled

        def checkin_cell_roi(day: int) -> tuple[int, int, int, int]:
            if day < 1 or day > checkin_days:
                raise ValueError(f"Điểm danh: ngày ngoài phạm vi 1..{checkin_days}: {day}")
            index = day - 1
            row, column = divmod(index, checkin_grid_columns)
            return scaled_roi(
                (
                    checkin_grid_x + column * checkin_cell_width,
                    checkin_grid_y + row * checkin_cell_height,
                    checkin_grid_x + (column + 1) * checkin_cell_width,
                    checkin_grid_y + (row + 1) * checkin_cell_height,
                )
            )

        def checkin_cell_center(day: int) -> tuple[int, int]:
            index = day - 1
            row, column = divmod(index, checkin_grid_columns)
            return scaled_point(
                checkin_grid_x + column * checkin_cell_width + checkin_cell_width // 2,
                checkin_grid_y + row * checkin_cell_height + checkin_cell_height // 2,
            )

        def checkin_tick_score(day: int, frame=None) -> float:
            """
            Return how closely the cell contains the green check shape.

            We threshold HSV first, then compare the binary green mask. This makes
            the detector independent of the reward artwork underneath the tick.
            """
            tick_mask = get_checkin_tick_mask()
            if tick_mask is None:
                return 0.0

            try:
                import cv2
                import numpy as np
            except Exception:
                return 0.0

            current = frame if frame is not None else capture_frame()
            image = getattr(current, "image", current)
            if not isinstance(image, np.ndarray) or image.ndim < 2:
                return 0.0

            x1, y1, x2, y2 = checkin_cell_roi(day)
            x1 = max(0, min(int(x1), int(image.shape[1])))
            x2 = max(0, min(int(x2), int(image.shape[1])))
            y1 = max(0, min(int(y1), int(image.shape[0])))
            y2 = max(0, min(int(y2), int(image.shape[0])))
            if x2 <= x1 or y2 <= y1:
                return 0.0

            cell = image[y1:y2, x1:x2]
            if cell.ndim == 2:
                hsv = cv2.cvtColor(cell, cv2.COLOR_GRAY2BGR)
                hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
            elif cell.shape[2] == 4:
                hsv = cv2.cvtColor(cell, cv2.COLOR_BGRA2HSV)
            elif cell.shape[2] == 3:
                hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            else:
                return 0.0

            # OpenCV H is 0..179. The green tick in the reference captures is
            # concentrated in this range; saturation/value filters remove most
            # yellow reward artwork.
            green = (
                (hsv[:, :, 0] >= 35)
                & (hsv[:, :, 0] <= 90)
                & (hsv[:, :, 1] >= 80)
                & (hsv[:, :, 2] >= 60)
            ).astype(np.uint8) * 255

            if (
                green.shape[0] < tick_mask.shape[0]
                or green.shape[1] < tick_mask.shape[1]
            ):
                return 0.0

            result = cv2.matchTemplate(
                green,
                tick_mask,
                cv2.TM_CCOEFF_NORMED,
            )
            return float(result.max()) if result.size else 0.0

        def checkin_badge_match(day: int, frame=None):
            """
            Match the existing "Được báo bù" badge only inside one cell.

            Per-cell matching is deliberate: find_all_templates() is capped at a
            small number of results and can miss the final marker when many cells
            contain the same badge.
            """
            current = frame if frame is not None else capture_frame()
            kwargs = {
                "threshold": checkin_badge_threshold,
                "roi": checkin_cell_roi(day),
                "scales": match_scales,
            }
            if current is not None:
                kwargs["frame"] = current
                kwargs["refresh"] = False
            else:
                kwargs["refresh"] = True

            return context.vision.find_template(checkin_claimable, **kwargs)

        def checkin_cell_marker(day: int, frame=None) -> tuple[bool, str | None, float]:
            badge = checkin_badge_match(day, frame=frame)
            if badge is not None:
                return True, "ĐƯỢC_BÁO_BÙ", float(getattr(badge, "confidence", 0.0))

            tick_score = checkin_tick_score(day, frame=frame)
            if tick_score >= checkin_tick_threshold:
                return True, "TICK", tick_score

            return False, None, max(
                float(getattr(badge, "confidence", 0.0)) if badge is not None else 0.0,
                tick_score,
            )

        def scan_checkin_markers(frame=None) -> list[tuple[int, str, float]]:
            current = frame if frame is not None else capture_frame()
            markers: list[tuple[int, str, float]] = []

            for day in range(1, checkin_days + 1):
                marked, marker_type, confidence = checkin_cell_marker(day, frame=current)
                if marked and marker_type is not None:
                    markers.append((day, marker_type, confidence))

            LOGGER.info(
                "Phúc lợi/Điểm danh marker scan: %s",
                [
                    {
                        "day": day,
                        "type": marker_type,
                        "confidence": round(float(confidence), 4),
                    }
                    for day, marker_type, confidence in markers
                ],
            )
            return markers

        def run_checkin(task: dict[str, Any]) -> None:
            """
            Điểm danh v4 - chọn ô theo marker đã nhận.

            Quy tắc:
            - Không có tick và không có "Được báo bù" -> click ô ngày 1.
            - Có marker -> tìm marker CUỐI CÙNG theo thứ tự ngày và click ô kế tiếp.
            - Đã có marker ở ngày cuối -> không click nữa.
            """
            logic_version = int(task.get("diem_danh_logic_version", 0) or 0)
            if logic_version < 4:
                task["diem_danh_logic_version"] = 4
                task["diem_danh_error"] = None
                if task.get("diem_danh") in {
                    "CLAIMED",
                    "ALREADY_DONE",
                    "DONE",
                    "CHECKED",
                    "OPENED",
                    "FAILED",
                }:
                    task["diem_danh"] = "NOT_STARTED"
                task["diem_danh_reason"] = None

            title = wait_best(
                checkin_titles,
                roi=checkin_title_roi,
                score=tab_threshold,
            )
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

            # Scan the whole 30-day grid from the current frame. This is the
            # authoritative decision point for the click; do not infer the target
            # from reward artwork, glow, or the current reward amount.
            markers = scan_checkin_markers()
            last_marker_day = markers[-1][0] if markers else 0

            if last_marker_day >= checkin_days:
                task["diem_danh"] = "ALREADY_DONE"
                task["diem_danh_error"] = None
                LOGGER.info(
                    "Phúc lợi/Điểm danh: marker cuối ở ngày %d/%d, không còn ô để nhận",
                    last_marker_day,
                    checkin_days,
                )
                return

            target_day = _next_checkin_day(last_marker_day, checkin_days)
            if target_day is None:
                task["diem_danh"] = "ALREADY_DONE"
                task["diem_danh_error"] = None
                return
            target_center = checkin_cell_center(target_day)

            LOGGER.info(
                "Phúc lợi/Điểm danh: markers=%s -> click ngày %d tại %s",
                [day for day, _, _ in markers],
                target_day,
                target_center,
            )

            for attempt in range(1, checkin_click_retries + 1):
                context.device.tap(*target_center)
                _wait_interruptibly(context, max(interval, 0.7))

                deadline = time.monotonic() + state_timeout
                while time.monotonic() <= deadline:
                    if _stop_requested(context):
                        raise ActionStopRequested("Stop requested")

                    # Reward popup is a direct success signal.
                    if dismiss_reward(checkin_reward):
                        task["diem_danh"] = "CLAIMED"
                        task["diem_danh_error"] = None
                        LOGGER.info(
                            "Phúc lợi/Điểm danh: ngày %d nhận thành công qua reward popup",
                            target_day,
                        )
                        return

                    # Otherwise the clicked cell must become one of the two
                    # recognized markers. This prevents a blind repeated click
                    # when the emulator did not register the tap.
                    frame = capture_frame()
                    marked, marker_type, confidence = checkin_cell_marker(
                        target_day,
                        frame=frame,
                    )
                    if marked:
                        task["diem_danh"] = "CLAIMED"
                        task["diem_danh_error"] = None
                        LOGGER.info(
                            "Phúc lợi/Điểm danh: ngày %d chuyển sang %s confidence=%.4f",
                            target_day,
                            marker_type,
                            confidence,
                        )
                        return

                    _wait_interruptibly(context, interval)

                # Trường hợp đặc biệt của game: marker cuối (ví dụ ngày 25) đã
                # tồn tại, nhưng ô kế tiếp (ngày 26) không đổi sau khi chạm.
                # Theo quy tắc vận hành của bot, đây được xem là đã hoàn tất
                # nhiệm vụ Điểm danh trong ngày và phải chuyển sang task kế tiếp,
                # không được biến thành FAILED rồi chặn Phúc lợi.
                fresh_frame = capture_frame()
                fresh_markers = scan_checkin_markers(frame=fresh_frame)
                fresh_last_marker = fresh_markers[-1][0] if fresh_markers else 0
                target_marked, target_marker_type, target_confidence = checkin_cell_marker(
                    target_day,
                    frame=fresh_frame,
                )
                if not target_marked and fresh_last_marker == last_marker_day:
                    task["diem_danh"] = "ALREADY_DONE"
                    task["diem_danh_error"] = None
                    task["diem_danh_reason"] = "NEXT_DAY_NOT_CHANGED"
                    LOGGER.info(
                        "Phúc lợi/Điểm danh: ngày %d không thay đổi sau click; "
                        "xác định nhiệm vụ hôm nay đã hoàn tất (marker cuối vẫn là ngày %d)",
                        target_day,
                        last_marker_day,
                    )
                    return

                LOGGER.warning(
                    "Phúc lợi/Điểm danh: ngày %d chưa có marker sau click lần %d/%d "
                    "(last_marker=%d, target_marked=%s, target_type=%s, confidence=%.4f)",
                    target_day,
                    attempt,
                    checkin_click_retries,
                    fresh_last_marker,
                    target_marked,
                    target_marker_type,
                    target_confidence,
                )

            raise RuntimeError(
                "Phúc lợi/Điểm danh: không xác nhận được ô kế tiếp sau "
                f"{checkin_click_retries} lần click (target_day={target_day}, "
                f"last_marker_day={last_marker_day})"
            )

        def run_tax(task: dict[str, Any]) -> None:
            # Game có đúng 3 lượt/ngày: 12-14, 18-20, 21-23.
            # Không dùng trạng thái DONE_FOR_NOW để khóa task này: mỗi khung giờ
            # là một slot độc lập và phải được kiểm tra lại.
            window = current_tax_window()
            slot_key = tax_slot_key()
            if window is None or slot_key is None:
                task["trung_thu_thue"] = "SKIPPED"
                task["trung_thu_thue_reason"] = "OUTSIDE_TIME_WINDOW"
                LOGGER.info(
                    "Phúc lợi/Trưng thu thuế: ngoài khung giờ, giờ hiện tại=%s, windows=%s",
                    tax_now().strftime("%Y-%m-%d %H:%M:%S %Z"),
                    ", ".join(str(item) for item in tax_windows),
                )
                return

            # Chỉ coi slot hiện tại đã xong nếu game/runtime đã xác nhận đúng slot đó.
            claimed_slots = task.get("trung_thu_thue_claimed_slots", [])
            if not isinstance(claimed_slots, list):
                claimed_slots = []
            today_prefix = tax_now().date().isoformat() + "@"
            claimed_slots = [str(item) for item in claimed_slots if str(item).startswith(today_prefix)]
            task["trung_thu_thue_claimed_slots"] = claimed_slots

            if slot_key in claimed_slots:
                task["trung_thu_thue"] = "CLAIMED"
                task["trung_thu_thue_reason"] = "ALREADY_CLAIMED_CURRENT_WINDOW"
                LOGGER.info("Phúc lợi/Trưng thu thuế: slot %s đã nhận, bỏ qua", slot_key)
                return

            task["trung_thu_thue"] = "RUNNING"
            task["trung_thu_thue_reason"] = None
            task["trung_thu_thue_last_attempt_at"] = tax_now().isoformat(timespec="seconds")

            # Không xác định khả dụng chỉ bằng đồng hồ PC. Sau khi vào đúng mục,
            # UI của game mới là nguồn sự thật: nút Trưng thu / Đã trưng thu /
            # Chưa mở. Điều này tránh lỗi lệch timezone hoặc chạy sát biên phút.
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
                # Retry nhẹ với ngưỡng thấp hơn vì nút bị animation/ánh sáng có thể
                # làm confidence tụt ở đúng thời điểm chuyển tab.
                retry_score = max(0.72, state_threshold - 0.08)
                state = wait_best(
                    (tax_claim, tax_claimed, tax_not_ready),
                    roi=tax_action_roi,
                    score=retry_score,
                    wait_timeout=max(2.0, state_timeout / 2.0),
                )
            if state is None:
                raise RuntimeError(
                    "Phúc lợi/Trưng thu thuế: không xác định được trạng thái nút "
                    f"trong slot {slot_key}"
                )

            if state[0] == tax_claim:
                tap_match(state[1])
                deadline = time.monotonic() + timeout
                claimed_seen = False
                while time.monotonic() <= deadline:
                    if dismiss_reward(tax_reward):
                        claimed_seen = True
                        break
                    if find_best(tax_claimed, roi=tax_action_roi, score=state_threshold) is not None:
                        claimed_seen = True
                        break
                    _wait_interruptibly(context, interval)

                if not claimed_seen:
                    # Có thể popup đã đóng nhưng nút đổi chậm; xác nhận lần cuối.
                    claimed_seen = wait_best(
                        tax_claimed,
                        roi=tax_action_roi,
                        score=max(0.72, state_threshold - 0.08),
                        wait_timeout=max(2.0, state_timeout / 2.0),
                    ) is not None

                if not claimed_seen:
                    raise RuntimeError(
                        "Phúc lợi/Trưng thu thuế: bấm Trưng thu nhưng không xác nhận được Đã trưng thu"
                    )

                claimed_slots.append(slot_key)
                task["trung_thu_thue_claimed_slots"] = sorted(set(claimed_slots))
                task["trung_thu_thue"] = "CLAIMED"
                task["trung_thu_thue_reason"] = None
                LOGGER.info(
                    "Phúc lợi/Trưng thu thuế: đã nhận slot %s (%d/3)",
                    slot_key,
                    len(task["trung_thu_thue_claimed_slots"]),
                )
            elif state[0] == tax_claimed:
                claimed_slots.append(slot_key)
                task["trung_thu_thue_claimed_slots"] = sorted(set(claimed_slots))
                task["trung_thu_thue"] = "CLAIMED"
                task["trung_thu_thue_reason"] = "ALREADY_CLAIMED_CURRENT_WINDOW"
            else:
                # Đang ở khung giờ nhưng game chưa mở lượt nhận. Không coi đây là lỗi;
                # lần chạy tiếp theo trong cùng slot sẽ kiểm tra lại.
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

        def tax_needs_retry_for_current_window(task_state: dict[str, Any]) -> bool:
            slot = tax_slot_key()
            if slot is None:
                return False
            slots = task_state.get("trung_thu_thue_claimed_slots", [])
            if not isinstance(slots, list):
                return True
            return slot not in {str(item) for item in slots}

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
        if (
            not checkin_only
            and task.get("status") == "DONE_FOR_NOW"
            and not tax_needs_retry_for_current_window(task)
        ):
            return ActionResult(
                True,
                "phuc_loi",
                "Phúc lợi đã hoàn thành trong runtime; không có slot Trưng thu thuế mới cần xử lý",
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
    def _recover_to_home(context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Normalize a running game session back to HOME without logging out.

        This action exists because some recovery scenarios referenced
        ``recover_to_home`` although the action was not registered in v4.1.
        It first proves HOME, then closes an open event panel when possible, and
        finally falls back to restarting the game and using finish_login to prove
        a stable HOME screen. It never presses Back blindly.
        """
        package = str(params.get("package", "com.daichien.mobile"))
        activity = str(params.get("activity", "com.qtz.game.main.Logo"))
        login_activity = str(params.get(
            "login_activity",
            "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity",
        ))
        timeout = max(2.0, float(params.get("timeout", 60.0)))
        interval = max(0.1, float(params.get("interval", 0.5)))
        home_threshold = float(params.get("home_threshold", 0.75))
        close_threshold = float(params.get("close_threshold", 0.90))
        max_close_taps = max(1, int(params.get("max_close_taps", 4)))

        home_marker = str(params.get(
            "home_marker", "dc3q/common/home_marker_noi_chinh.png"
        ))
        panel_close = str(params.get(
            "panel_close", "dc3q/targets/Hoạt-Động/screen/event_panel_close_button.png"
        ))

        def find(path: str, threshold: float):
            try:
                return ActionRegistry._template(context, path, threshold)
            except Exception:
                return None

        # Already HOME: do nothing.
        if find(home_marker, home_threshold) is not None:
            return ActionResult(True, "recover_to_home", "Already at HOME", {"normalized_to_home": True})

        # Close an open event panel only when its close button is actually visible.
        for attempt in range(max_close_taps):
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            if find(home_marker, home_threshold) is not None:
                return ActionResult(True, "recover_to_home", "Returned to HOME", {"normalized_to_home": True})
            match = find(panel_close, close_threshold)
            if match is None:
                break
            context.device.tap(*match.center)
            _wait_interruptibly(context, interval)

        deadline = time.monotonic() + timeout
        while time.monotonic() <= deadline:
            if _stop_requested(context):
                raise ActionStopRequested("Stop requested")
            if find(home_marker, home_threshold) is not None:
                return ActionResult(True, "recover_to_home", "Returned to HOME", {"normalized_to_home": True})
            _wait_interruptibly(context, interval)

        # Last resort: restart the app, preserving the current session, then use
        # the existing login-finalization routine to verify a stable HOME screen.
        LOGGER.warning("recover_to_home: restart fallback after UI recovery timeout")
        _call_first(context.device, ("stop_app", "force_stop"), package)
        _wait_interruptibly(context, max(0.2, float(params.get("restart_delay", 1.0))))
        _call_first(context.device, ("start_app", "launch_app"), package, activity)
        _wait_interruptibly(context, interval)

        if context.device.get_current_activity() == login_activity:
            return ActionResult(False, "recover_to_home", "Session expired; authentication screen is visible")

        result = ActionRegistry._finish_login(context, {
            "timeout": timeout,
            "interval": interval,
            "stable_frames": max(2, int(params.get("stable_frames", 2))),
            "home_threshold": home_threshold,
        })
        return ActionResult(
            result.success,
            "recover_to_home",
            result.message,
            {**result.data, "normalized_to_home": bool(result.success)},
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
