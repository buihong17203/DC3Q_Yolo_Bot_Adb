from importlib import import_module
from types import SimpleNamespace


module = import_module("app.actions.dc3q.targets.05_khong-gian-ca-nhan")


def hit():
    return SimpleNamespace(found=True, confidence=1.0, x=1, y=1, width=2, height=2)


def test_close_personal_panel_returning_home_reopens_info_before_share():
    runner = object.__new__(module.KhongGianCaNhanRunner)
    runner.config = SimpleNamespace(
        info_markers=["info"], home_markers=["home"], wait_seconds=0,
    )
    runner._first = lambda screen, templates, threshold=None: (
        hit() if (screen == "home" and templates == ["home"])
        or (screen == "info" and templates == ["info"]) else None
    )
    runner.home_entry = lambda screen: (40, 50)
    taps = []
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))
    runner.sleep = lambda _: None
    runner._prove = lambda templates, message, attempts=8: "info"

    assert runner._return_to_info_after_personal_close("home") == "info"
    assert taps == [(40, 50)]
