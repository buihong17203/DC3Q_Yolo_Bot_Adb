from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(confidence=1.0):
    return SimpleNamespace(found=True, confidence=confidence, x=1, y=2, width=4, height=6)


def test_a7_uses_flow_specific_close_threshold():
    runner = object.__new__(module.TruongThanhRunner)
    seen = []
    runner._first = lambda screen, templates, threshold=None: seen.append(threshold) or hit()
    runner._wait_first = lambda templates, attempts=6, threshold=None: (seen.append(threshold) or object(), hit())
    runner._tap = lambda match: None
    flow = module.SubFlow("A7", [], [], ["spent"], ["close"], close_threshold=.65)

    assert runner._finish_flow(flow, object()) is True
    assert .65 in seen


def test_repeat_flow_keeps_claiming_only_clear_free_states():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace()
    flow = module.SubFlow("A6", [], ["free"], ["reward"], ["back"], repeat_free=True)
    taps = []
    states = iter([hit(), hit(), None])
    runner._first = lambda screen, templates, threshold=None: next(states) if templates == ["free"] else (hit() if templates == ["reward"] else None)
    runner._tap = taps.append
    runner._wait_first = lambda templates, attempts=6: (object(), hit())
    runner._finish_flow = lambda flow, screen: True
    runner.screen_provider = lambda: object()

    runner._run_flow(flow)

    assert len(taps) == 2
