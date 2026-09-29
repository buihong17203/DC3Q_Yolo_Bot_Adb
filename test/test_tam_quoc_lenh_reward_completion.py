from importlib import import_module
from pathlib import Path
from types import SimpleNamespace


class Match:
    def __init__(self, found=False, confidence=0.0):
        self.found, self.confidence = found, confidence
        self.x = self.y = 10
        self.width = self.height = 20


class Vision:
    def find_template(self, screen, _group, template, _threshold):
        name = Path(template).name
        confidence = screen.get(name, 0.0)
        return SimpleNamespace(match=Match(confidence >= 0.85, confidence))


class Input:
    def __init__(self): self.taps = []
    def tap(self, x, y): self.taps.append((x, y))


def test_reward_popup_completes_free_que_then_advances_to_diem(tmp_path):
    module = import_module("app.actions.dc3q.targets.01_tam-quoc-lenh")
    p = lambda name: tmp_path / name
    cfg = module.TamQuocLenhConfig(
        [p("entry")], [], [p("close")], p("close"), p("reward"), p("dismiss"),
        [p("que_tab")], [p("que_open")], p("que_free"), p("que_paid"),
        [p("diem_tab")], [p("diem_open")], p("diem_free"), p("diem_paid"),
        (0, 0, 100, 100), [p("home")], action_threshold=.85, max_steps=8, wait_seconds=0,
    )
    frames = iter([
        {"entry": 1}, {"que_tab": 1}, {"que_open": 1},
        {"close": 1, "que_free": 1, "que_paid": .4},
        {"reward": 1, "dismiss": 1},
        {"close": 1, "diem_tab": 1}, {"diem_open": 1},
        {"close": 1, "diem_paid": 1}, {"close": 1}, {"home": 1},
    ])
    runner = module.TamQuocLenhRunner(lambda: next(frames), Input(), Vision(), cfg, sleep=lambda _: None)
    assert runner.run() is True
    assert runner._last_completed_action == "que"
