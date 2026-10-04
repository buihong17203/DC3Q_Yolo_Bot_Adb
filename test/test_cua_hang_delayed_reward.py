from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.03_cua-hang")


def test_daily_claim_waits_for_and_dismisses_delayed_reward_before_returning():
    runner = object.__new__(module.CuaHangRunner)
    runner.config = SimpleNamespace(
        daily_unclaimed="free", daily_claimed="claimed",
        reward_marker="reward", reward_dismiss="dismiss",
        wait_seconds=0,
    )
    runner.sleep = lambda _: None
    screens = iter([
        "claimed_before_popup", "reward_popup", "claimed_after_popup_1",
        "claimed_after_popup_2", "claimed_after_popup_3",
    ])
    runner.screen_provider = lambda: next(screens)
    states = iter([
        ("free", object()), ("claimed", object()), ("unknown", None),
        ("claimed", object()), ("claimed", object()), ("claimed", object()),
    ])
    runner._competing_state = lambda *_: next(states)
    dismissed = []
    runner._tap = lambda _: None
    runner._reward = lambda screen: dismissed.append(screen) or screen == "reward_popup"

    screen, done = runner._claim_daily_gift("free_screen")

    assert done is True
    assert screen == "claimed_after_popup_3"
    assert dismissed == [
        "claimed_before_popup", "reward_popup", "claimed_after_popup_1",
        "claimed_after_popup_2", "claimed_after_popup_3",
    ]
