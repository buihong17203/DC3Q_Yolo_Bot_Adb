from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=1.0, x=1, y=2, width=3, height=4)


def test_free_action_wins_over_panel_close():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace()
    flow = module.SubFlow("A7", [], ["free"], ["spent"], ["close"])
    taps = []
    initial, terminal = object(), object()
    runner._first = lambda screen, templates, threshold=None: (
        hit() if (screen is initial and templates == ["free"])
        or (screen is terminal and templates in (["spent"], ["close"])) else None
    )
    runner._tap = lambda match: taps.append(match)
    runner._wait_first = lambda templates, attempts=6, threshold=None: (terminal, hit())
    runner.screen_provider = lambda: initial

    runner._run_flow(flow)

    assert len(taps) == 2
