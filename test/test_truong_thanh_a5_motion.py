from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def test_a5_never_targets_without_running_horse_prompt():
    runner = object.__new__(module.TruongThanhRunner)
    runner._a5_text = lambda screen: "Hay chon Day Bat Ngua"
    runner.sleep = lambda _: None
    runner.config = SimpleNamespace(wait_seconds=0)
    taps = []
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))

    assert runner._a5_tap_moving_horse(object(), object()) is False
    assert taps == []


def test_a5_taps_motion_target_only_with_running_horse_prompt():
    runner = object.__new__(module.TruongThanhRunner)
    runner._a5_text = lambda screen: "Hay an vao thu cuoi dang chay"
    runner._a5_motion_target = lambda before, after: (520, 285)
    runner.sleep = lambda _: None
    runner.config = SimpleNamespace(wait_seconds=0)
    taps = []
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))

    assert runner._a5_tap_moving_horse(object(), object()) is True
    assert taps == [(520, 285)]
