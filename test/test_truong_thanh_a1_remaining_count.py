from importlib import import_module
from types import SimpleNamespace

import pytest

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=1.0, x=1, y=1, width=2, height=2)


def make_runner(after_count):
    value = object.__new__(module.TruongThanhRunner)
    value.config = SimpleNamespace(
        a1_entry="entry", a1_reward="reward", a1_view="view",
        a1_running=["running"], a1_plus_slot="plus", a1_execute=["execute"],
        a1_execution_count_roi=(1, 2, 3, 4), a1_close_point=(9, 9),
        hub_markers=["hub"], wait_seconds=0,
    )
    value._open_home_entry = lambda: None
    value.screen_provider = lambda: "board"
    value._match = lambda screen, template, threshold=None: hit()
    value._wait_first = lambda templates, attempts=6, threshold=None: ("board", hit())
    value._a1_claim_rewards = lambda screen: screen
    calls = iter(after_count if isinstance(after_count, list) else [after_count])
    value._read_roi_number = lambda screen, roi: next(calls)
    opened = [False]
    value._a1_open_next_mission = lambda screen: (
        ("detail", 7) if not opened[0] and not opened.__setitem__(0, True) else None
    )
    value._a1_fill_and_execute = lambda screen: True
    value.input = SimpleNamespace(tap=lambda *args: None)
    value.sleep = lambda _: None
    return value


def test_a1_accepts_execution_count_decreasing_exactly_one():
    make_runner(6)._run_a1()


def test_a1_rejects_execution_count_that_does_not_decrease():
    with pytest.raises(RuntimeError, match="không giảm đúng 1"):
        make_runner([7] * 8)._run_a1()


def test_a1_waits_for_delayed_execution_count_update():
    make_runner([7, 7, 6])._run_a1()
