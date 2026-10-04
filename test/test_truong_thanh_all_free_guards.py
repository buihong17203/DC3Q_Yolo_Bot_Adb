from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=1.0, x=10, y=20, width=20, height=10)


def test_a6_rechecks_free_marker_before_every_tap_then_closes():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow("A6", [], ["free"], ["reward"], ["close"], repeat_free=True)
    initial, reward1, reward2, final_reward = object(), object(), object(), object()
    runner.screen_provider = lambda: initial

    def first(screen, templates, threshold=None):
        if templates == ["free"] and screen in (initial, reward1, reward2):
            return hit()
        if templates == ["reward"] and screen in (reward1, reward2, final_reward):
            return hit()
        return None

    runner._first = first
    waits = iter([
        (reward1, hit()), (reward2, hit()), (final_reward, hit()),
        (final_reward, hit()),
    ])
    runner._wait_first = lambda templates, attempts=6, threshold=None: next(waits)
    taps = []
    runner._tap = lambda match: taps.append("tap")
    runner.config = SimpleNamespace()

    runner._run_flow(flow)

    assert taps == ["tap", "tap", "tap", "tap"]  # 3 FREE + Trở về.


def test_non_repeat_flow_never_taps_without_free():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow("A7", [], ["free"], ["spent"], ["close"])
    paid = object()
    runner.screen_provider = lambda: paid
    runner._first = lambda screen, templates, threshold=None: hit() if templates == ["close"] else None
    taps = []
    runner._tap = lambda match: taps.append("close")
    runner.config = SimpleNamespace()

    runner._run_flow(flow)

    assert taps == ["close"]
