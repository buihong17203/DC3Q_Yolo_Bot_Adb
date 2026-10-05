from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(confidence=1.0):
    return SimpleNamespace(found=True, confidence=confidence, x=10, y=20, width=20, height=10)


def miss(confidence=0.0):
    return SimpleNamespace(found=False, confidence=confidence, x=0, y=0, width=20, height=10)


def test_a2_taps_only_clear_free_state_and_stops_on_paid():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a2_free="free", a2_paid="paid", a2_popup_close="close",
        a2_main=["main"], state_threshold=.80, state_margin=.05, wait_seconds=0,
    )
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    taps = []
    runner._tap = taps.append
    states = iter([(hit(1.0), miss(.72)), (miss(.32), hit(1.0))])
    runner._a2_state = lambda screen: next(states)
    runner._wait_a2_after_free = lambda screen=None: object()
    runner._first = lambda screen, templates: None

    runner._a2_claim_free(object())

    assert len(taps) == 1


def test_a2_unknown_state_never_taps():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(a2_free="free", a2_paid="paid", state_threshold=.80, state_margin=.05)
    runner._a2_state = lambda screen: (miss(.4), miss(.5))
    runner._wait_a2_after_free = lambda screen=None: screen
    taps = []
    runner._tap = taps.append

    runner._a2_claim_free(object())

    assert taps == []
