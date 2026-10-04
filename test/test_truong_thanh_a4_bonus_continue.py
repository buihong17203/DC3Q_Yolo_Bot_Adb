from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=1.0, x=10, y=20, width=20, height=10)


def test_a4_full_guard_reward_taps_continue_once_then_waits_for_normal_result():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow(
        "A4", [], ["free"], ["spent"], ["close"],
        bonus_continue=["continue"], bonus_tap_point=(480, 360),
    )
    first, bonus, result = object(), object(), object()
    runner.screen_provider = lambda: first
    runner._first = lambda screen, templates, threshold=None: (
        hit() if (screen is first and templates == ["free"])
        or (screen is bonus and templates == ["continue"])
        or (screen is result and templates == ["spent"])
        or (screen is result and templates == ["close"]) else None
    )
    waits = iter([(bonus, hit()), (result, hit()), (result, hit())])
    runner._wait_first = lambda templates, attempts=6, threshold=None: next(waits)
    taps = []
    runner._tap = lambda match: taps.append("control")
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))
    runner.sleep = lambda _: None
    runner.config = SimpleNamespace(wait_seconds=0)

    runner._run_flow(flow)

    assert taps == ["control", (480, 360), "control"]


def test_a4_taps_free_at_most_once_even_when_stale_frame_still_matches_free():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow("A4", [], ["free"], ["spent"], ["close"], free_threshold=.95)
    initial, result = object(), object()
    runner.screen_provider = lambda: initial

    def first(screen, templates, threshold=None):
        if screen is initial and templates == ["free"]:
            return hit()
        if screen is result and templates in (["free"], ["spent"], ["close"]):
            return hit()
        return None

    runner._first = first
    waits = iter([(result, hit()), (result, hit())])
    runner._wait_first = lambda templates, attempts=6, threshold=None: next(waits)
    taps = []
    runner._tap = lambda match: taps.append("control")
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))
    runner.sleep = lambda _: None
    runner.config = SimpleNamespace(wait_seconds=0)

    runner._run_flow(flow)

    assert taps == ["control", "control"]  # FREE một lần, sau đó Trở về.
