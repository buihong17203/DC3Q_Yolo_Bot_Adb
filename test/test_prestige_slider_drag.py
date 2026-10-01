from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.03_cua-hang")


def match(found):
    return SimpleNamespace(found=found)


def test_prestige_slider_drag_starts_on_round_knob():
    runner = object.__new__(module.CuaHangRunner)
    swipes = []
    runner.input = SimpleNamespace(swipe=lambda *args: swipes.append(args))
    runner.sleep = lambda _: None
    runner.config = SimpleNamespace(slider_end_ratio=0.82, wait_seconds=0)
    slider = SimpleNamespace(x=300, y=200, width=200, height=40)

    runner._drag_prestige_slider_to_max(slider, 0.37)

    assert swipes == [(374, 220, 464, 220, 700)]


def test_prestige_slider_spams_plus_until_max_after_drag_fails():
    runner = object.__new__(module.CuaHangRunner)
    taps = []
    checks = iter([False, False, True])
    runner.input = SimpleNamespace(
        swipe=lambda *_: None,
        tap=lambda x, y: taps.append((x, y)),
    )
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    runner._wait_for_paid = lambda *_args, **_kwargs: (object(), None)
    runner._match_popup = lambda *_args, **_kwargs: match(True)
    runner._match = lambda *_args, **_kwargs: match(next(checks))
    runner.config = SimpleNamespace(
        slider_end_ratio=0.82,
        wait_seconds=0,
        paid_threshold=0.9,
        prestige_popup="popup",
        prestige_slider_max="5/5",
    )
    slider = SimpleNamespace(x=300, y=200, width=200, height=40)

    _screen, maximum = runner._maximize_prestige_quantity(slider, 0.37)

    assert maximum.found
    assert taps == [(484, 220), (484, 220), (484, 220)]
