from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=.993, x=363, y=464, width=238, height=32)


def test_recovery_dismisses_delayed_full_guard_reward_before_other_layers():
    runner = object.__new__(module.TruongThanhRunner)
    bonus, home = object(), object()
    screens = iter([bonus, home])
    runner.screen_provider = lambda: next(screens)
    runner.config = SimpleNamespace(
        bonus_continue_templates=["bonus"], bonus_continue_point=(800, 480),
        hub_markers=["hub"], entry_templates=["entry"], home_markers=["home"],
        close_templates=["close"], wait_seconds=0,
    )
    runner._first = lambda screen, templates, threshold=None: (
        hit() if (screen is bonus and templates == ["bonus"])
        or (screen is home and templates == ["home"]) else None
    )
    taps = []
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))
    runner.sleep = lambda _: None
    runner._tap = lambda match: taps.append("control")

    assert runner.recover_home() is True
    assert taps == [(800, 480)]


def test_recovery_a4_return_then_home_route():
    runner = object.__new__(module.TruongThanhRunner)
    reward, map_view, hub, home = object(), object(), object(), object()
    screens = iter([reward, map_view, hub, home])
    runner.screen_provider = lambda: next(screens)
    runner.config = SimpleNamespace(
        bonus_continue_templates=[], bonus_continue_point=(800, 480),
        a4_return_templates=["return"], hub_markers=["hub"],
        entry_templates=["toggle"], home_markers=["home"],
        close_templates=["return_home"], wait_seconds=0,
    )

    def first(screen, templates, threshold=None):
        if screen is reward and templates == ["return"]:
            return hit()
        if screen is map_view and templates == ["return_home"]:
            return hit()
        if screen is hub and templates in (["hub"], ["toggle"]):
            return hit()
        if screen is home and templates == ["home"]:
            return hit()
        return None

    runner._first = first
    taps = []
    runner._tap = lambda match: taps.append("control")
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))
    runner.sleep = lambda _: None

    assert runner.recover_home() is True
    assert taps == ["control", "control", "control"]
