from __future__ import annotations

from unittest.mock import patch

from app.accounts import Account
from app.automation import AutomationEngine


class FakeDevice:
    serial = "fake-1"

    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.taps: list[tuple[int, int]] = []
        self.shell_outputs: list[str] = []

    def shell(self, *args, **kwargs) -> str:
        return self.shell_outputs.pop(0) if self.shell_outputs else ""

    def input_text(self, text: str) -> None:
        self.inputs.append(text)

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def clear_text(self, max_characters: int = 128) -> None:
        self.inputs.append(f"<clear:{max_characters}>")

    def get_current_activity(self) -> str:
        return "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"

    def get_screen_size(self) -> tuple[int, int]:
        return 960, 540


class FakeVision:
    pass


class Match:
    def __init__(self, center: tuple[int, int]) -> None:
        self.center = center
        self.confidence = 0.99


class SequenceVision:
    def __init__(self, visible: list[set[str]]) -> None:
        self.visible = visible
        self.frame = 0

    def find_template(self, template, **kwargs):
        found = template in self.visible[min(self.frame, len(self.visible) - 1)]
        return Match((480, 270)) if found else None

    def advance(self) -> None:
        self.frame += 1


def test_account_variables_are_available_in_scenario() -> None:
    device = FakeDevice()
    engine = AutomationEngine(device, FakeVision())
    account = Account(id="7", username="alice", password="secret")

    result = engine.run(
        {
            "name": "account-variable-test",
            "steps": [
                {"action": "input_text", "text": "${account.username}"},
                {"action": "set_variable", "key": "copied", "value": "${account.id}"},
            ],
        },
        account=account,
    )

    assert result.success
    assert device.inputs == ["alice"]


def test_clear_text_action_is_available_for_login_forms() -> None:
    device = FakeDevice()
    engine = AutomationEngine(device, FakeVision())
    context = engine.create_context()

    result = engine.execute_action(context, {"action": "clear_text", "max_characters": 64})

    assert result.success
    assert device.inputs == ["<clear:64>"]


def test_login_credentials_uses_real_adb_device_methods() -> None:
    device = FakeDevice()
    engine = AutomationEngine(device, FakeVision())
    context = engine.create_context(
        variables={"account": {"username": "real-user", "password": "real-pass"}}
    )

    with patch("app.automation.actions.time.sleep", return_value=None):
        result = engine.execute_action(
            context,
            {
                "action": "login_credentials",
                "username": "${account.username}",
                "password": "${account.password}",
                "timeout": 1,
            },
        )

    assert result.success
    assert device.taps == [(480, 190), (480, 237), (480, 306)]
    assert device.inputs == ["<clear:128>", "real-user", "<clear:128>", "real-pass"]


def test_ensure_login_screen_does_not_reopen_app_when_auth_is_visible() -> None:
    device = FakeDevice()
    engine = AutomationEngine(device, FakeVision())

    result = engine.execute_action(engine.create_context(), {
        "action": "ensure_login_screen",
        "package": "com.daichien.mobile",
        "activity": "com.qtz.game.main.Logo",
        "timeout": 1,
    })

    assert result.success
    assert not hasattr(device, "started_apps")


def test_ensure_login_screen_opens_app_once_when_not_running() -> None:
    device = FakeDevice()
    device.activity = "com.ldmnq.launcher3/com.android.launcher3.Launcher"
    device.started_apps = []

    def current_activity() -> str:
        return device.activity

    def start_app(package: str, activity: str) -> None:
        device.started_apps.append((package, activity))
        device.activity = "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"

    device.get_current_activity = current_activity
    device.start_app = start_app
    engine = AutomationEngine(device, FakeVision())
    with patch("app.automation.actions.time.sleep", return_value=None):
        result = engine.execute_action(engine.create_context(), {
            "action": "ensure_login_screen",
            "package": "com.daichien.mobile",
            "activity": "com.qtz.game.main.Logo",
            "timeout": 1,
        })

    assert result.success
    assert device.started_apps == [("com.daichien.mobile", "com.qtz.game.main.Logo")]


def test_finish_login_closes_only_verified_profile_update_popup() -> None:
    home = "dc3q/common/home_marker_noi_chinh.png"
    device = FakeDevice()
    device.shell_outputs = [
        "",
        "UI hierchary dumped to: /sdcard/__dc3q_profile_update.xml",
        '<?xml version="1.0"?><hierarchy><node text="Cập nhật thông tin cá nhân" bounds="[100,100][700,450]"/><node content-desc="Đóng" bounds="[770,175][808,213]"/></hierarchy>',
    ]
    vision = SequenceVision([set(), {home}, {home}, {home}])
    original_tap = device.tap

    def tap_and_advance(x: int, y: int) -> None:
        original_tap(x, y)
        vision.advance()

    device.tap = tap_and_advance
    engine = AutomationEngine(device, vision)
    with patch("app.automation.actions.time.sleep", side_effect=lambda _: vision.advance()):
        result = engine.execute_action(engine.create_context(), {
            "action": "finish_login",
            "timeout": 2,
            "interval": 0,
            "stable_frames": 3,
        })

    assert result.success
    assert device.taps == [(789, 194)]


def test_logout_account_uses_verified_states_then_confirms() -> None:
    profile = "dc3q/targets/Đăng-Xuất/screen/screen_my_info_title_bar.png"
    options = "dc3q/targets/Đăng-Xuất/screen/screen_options_title_bar.png"
    confirm = "dc3q/targets/Đăng-Xuất/screen/screen_change_account_title_bar.png"
    options_icon = "dc3q/targets/Đăng-Xuất/screen/screen_options_icon.png"
    settings_button = "dc3q/targets/Đăng-Xuất/screen/screen_user_settings_button.png"
    change_account = "dc3q/targets/Đăng-Xuất/screen/screen_change_account_button.png"
    confirm_button = "dc3q/targets/Đăng-Xuất/screen/screen_confirm_button.png"
    vision = SequenceVision([
        {profile, options_icon},
        {options, settings_button},
        {change_account},
        {confirm, confirm_button},
    ])
    device = FakeDevice()
    device.activity = "com.daichien.mobile/com.qtz.game.main.Q2"
    device.get_current_activity = lambda: device.activity
    original_tap = device.tap

    def tap_and_advance(x: int, y: int) -> None:
        original_tap(x, y)
        vision.advance()
        if vision.frame >= 4:
            device.activity = "com.daichien.mobile/com.vtcmobile.gamesdk.AuthenActivity"

    device.tap = tap_and_advance
    engine = AutomationEngine(device, vision)
    with patch("app.automation.actions.time.sleep", return_value=None):
        result = engine.execute_action(engine.create_context(), {
            "action": "logout_account",
            "timeout": 2,
            "interval": 0,
        })

    assert result.success
    assert device.taps == [(480, 270), (480, 270), (480, 270), (480, 270)]


def test_random_server_events_are_optional() -> None:
    device = FakeDevice()
    vision = SequenceVision([set()])
    engine = AutomationEngine(device, vision)
    with patch("app.automation.actions.time.sleep", return_value=None):
        result = engine.execute_action(engine.create_context(), {
            "action": "handle_random_server_events",
            "timeout": 1,
            "quiet_frames": 1,
        })

    assert result.success
    assert device.taps == []


def test_random_server_events_open_and_close_red_envelope() -> None:
    open_button = "dc3q/random-events/red-envelope/screen/screen_open_button.png"
    close_prompt = "dc3q/random-events/red-envelope/screen/screen_close_prompt.png"
    reward_items = "dc3q/random-events/red-envelope/screen/screen_tap_blank_to_close.png"
    home = "dc3q/common/home_marker_noi_chinh.png"
    device = FakeDevice()
    vision = SequenceVision([{open_button}, {close_prompt}, {reward_items}, {home}, {home}])
    engine = AutomationEngine(device, vision)
    with patch("app.automation.actions.time.sleep", side_effect=lambda _: vision.advance()):
        result = engine.execute_action(engine.create_context(), {
            "action": "handle_random_server_events",
            "timeout": 2,
            "quiet_frames": 2,
        })

    assert result.success
    assert device.taps == [(480, 270), (480, 270), (480, 270)]


def test_random_server_events_close_verified_enemy_raid() -> None:
    dialog = "dc3q/random-events/enemy-raid/full_screen_enemy_raid_event_dialog.png"
    close = "dc3q/random-events/enemy-raid/screen_enemy_raid_close_button.png"
    device = FakeDevice()
    vision = SequenceVision([{dialog, close}, set(), set()])
    engine = AutomationEngine(device, vision)

    with patch("app.automation.actions.time.sleep", side_effect=lambda _: vision.advance()):
        result = engine.execute_action(engine.create_context(), {
            "action": "handle_random_server_events",
            "timeout": 2,
            "quiet_frames": 2,
        })

    assert result.success
    assert device.taps == [(480, 270)]


def test_finish_login_handles_server_event_that_appears_late() -> None:
    open_button = "dc3q/random-events/red-envelope/screen/screen_open_button.png"
    close_prompt = "dc3q/random-events/red-envelope/screen/screen_close_prompt.png"
    reward_items = "dc3q/random-events/red-envelope/screen/screen_tap_blank_to_close.png"
    home = "dc3q/common/home_marker_noi_chinh.png"
    device = FakeDevice()
    device.get_current_activity = lambda: "com.daichien.mobile/com.qtz.game.main.Q2"
    vision = SequenceVision([set(), {open_button}, {close_prompt}, {reward_items}, {home}, {home}])
    engine = AutomationEngine(device, vision)

    with patch("app.automation.actions.time.sleep", side_effect=lambda _: vision.advance()):
        result = engine.execute_action(engine.create_context(), {
            "action": "finish_login",
            "timeout": 2,
            "interval": 0,
            "stable_frames": 2,
        })

    assert result.success
    assert device.taps == [(480, 270), (480, 270), (480, 270)]
