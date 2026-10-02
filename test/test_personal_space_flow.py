from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import yaml

module = import_module("app.actions.dc3q.targets.05_khong-gian-ca-nhan")
ROOT = Path(__file__).parents[1]


class Match:
    found = True
    confidence = 1.0
    x = 10
    y = 20
    width = 20
    height = 10


class Input:
    def __init__(self):
        self.actions = []

    def tap(self, x, y):
        self.actions.append((x, y))


def test_info_uses_new_dedicated_marker_not_full_screen():
    config = yaml.safe_load((ROOT / "config/dc3q/targets/05_khong-gian-ca-nhan.yaml").read_text(encoding="utf-8"))
    markers = config["khong_gian_ca_nhan"]["info"]["markers"]
    assert markers == [
        "data/img/templates/targets/05_khong-gian-ca-nhan/screen/screen_thongtincuatoi.png"
    ]


def test_personal_flow_orders_share_then_open_then_like_all():
    runner = object.__new__(module.KhongGianCaNhanRunner)
    runner.input = Input()
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    runner.home_entry = lambda screen: (1, 2)
    runner.config = SimpleNamespace(
        info_markers=[Path("info.png")], personal_markers=[Path("personal.png")],
        entry_templates=[Path("entry.png")], close_template=Path("close.png"),
        home_markers=[Path("home.png")], wait_seconds=0, state_wait_attempts=24,
    )
    calls = []
    first_calls = iter([None, None, Match()])
    runner._first = lambda screen, templates, threshold=None: next(first_calls)
    runner._prove = lambda templates, message, attempts=8: calls.append(("prove", templates)) or object()
    runner._share_once = lambda screen: calls.append(("share",)) or object()
    runner._like_all = lambda screen: calls.append(("like_all",)) or object()
    runner._match = lambda screen, template, threshold=None: Match()
    runner.recover_home = lambda: True

    assert runner.run()
    assert runner.input.actions == [(1, 2), (20, 25), (20, 25)]
    assert calls[1][0] == "share"
    assert calls[2][0] == "prove"
    assert calls[3][0] == "like_all"


def test_like_all_waits_for_loaded_state_before_tapping():
    runner = object.__new__(module.KhongGianCaNhanRunner)
    runner.config = SimpleNamespace(
        like_all=Path("like-all.png"), like_after=Path("liked.png"),
        state_threshold=.80, wait_seconds=0, state_wait_attempts=24,
    )
    runner.sleep = lambda _: None
    states = iter([
        SimpleNamespace(found=False, confidence=.25),
        SimpleNamespace(found=True, confidence=.99, x=10, y=20, width=20, height=10),
    ])
    runner._match = lambda screen, template, threshold=None: next(states)
    runner.screen_provider = lambda: "loaded"
    taps = []
    runner._tap = taps.append
    runner._prove = lambda templates, message, attempts=8: "liked"

    assert runner._like_all("loading") == "liked"
    assert len(taps) == 1


def test_personal_panel_uses_long_state_wait_after_entry_tap():
    runner = object.__new__(module.KhongGianCaNhanRunner)
    runner.input = Input()
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    runner.home_entry = None
    runner.config = SimpleNamespace(
        info_markers=[Path("info.png")], personal_markers=[Path("personal.png")],
        entry_templates=[Path("entry.png")], close_template=Path("close.png"),
        home_markers=[Path("home.png")], wait_seconds=0, state_wait_attempts=24,
    )
    calls = []
    first_calls = iter([None, Match(), Match()])
    runner._first = lambda screen, templates, threshold=None: next(first_calls)
    runner._share_once = lambda screen: screen
    runner._prove = lambda templates, message, attempts=8: calls.append(attempts) or object()
    runner._like_all = lambda screen: screen
    runner._match = lambda screen, template, threshold=None: Match()
    runner.recover_home = lambda: True

    assert runner.run() is True
    assert calls == [24]
