from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(x):
    return SimpleNamespace(found=True, confidence=1.0, x=x, y=262, width=53, height=35)


def test_a3_entry_is_derived_between_tuong_an_and_ve_tuong():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(a2_entry="tuong_an", a3_right_anchor="ve_tuong", wait_seconds=0)
    runner.sleep = lambda _: None
    taps = []
    runner.input = SimpleNamespace(tap=lambda x, y: taps.append((x, y)))
    runner._match = lambda screen, template: hit(138) if template == "tuong_an" else hit(251)

    runner._tap_a3_entry(object())

    assert taps == [(221, 279)]
