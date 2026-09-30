from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import yaml

module = import_module("app.actions.dc3q.targets.06_xa-giao")
ROOT = Path(__file__).parents[1]


def match(found, confidence=None):
    score = float(found) if confidence is None else confidence
    return SimpleNamespace(found=found, confidence=score, x=10, y=20, width=20, height=10)


def runner():
    value = object.__new__(module.XaGiaoRunner)
    value.config = SimpleNamespace(
        heart_before=Path("heart-before"), heart_after=Path("heart-after"),
        quick_before=Path("quick-before"), quick_after=Path("quick-after"),
        state_threshold=0.8, wait_seconds=0,
    )
    value.sleep = lambda _: None
    value.screen_provider = lambda: object()
    value.input = SimpleNamespace(tap=lambda x, y: None)
    return value


def test_panel_markers_use_quick_button_states_not_full_screens():
    cfg = yaml.safe_load((ROOT / "config/dc3q/targets/06_xa-giao.yaml").read_text(encoding="utf-8"))["xa_giao"]
    assert cfg["panel"]["markers"] == [
        cfg["quick_give"]["before"], cfg["quick_give"]["after"],
    ]


def test_no_friend_skips_when_both_heart_states_absent():
    value = runner()
    value._match = lambda screen, template, threshold=None: match(False)
    tapped = []
    value._tap = tapped.append

    assert value._give_hearts(object()) == "no_friends"
    assert tapped == []


def test_untouched_friends_click_quick_and_require_both_after_states():
    value = runner()
    states = {
        "heart-before": [match(True), match(False)],
        "heart-after": [match(False), match(True)],
        "quick-before": [match(True)],
        "quick-after": [match(False), match(True)],
    }
    value._match = lambda screen, template, threshold=None: states[template.name].pop(0)
    tapped = []
    value._tap = tapped.append

    assert value._give_hearts(object()) == "given"
    assert len(tapped) == 1


def test_already_given_never_clicks_quick_again():
    value = runner()
    answers = {
        "heart-before": match(False), "heart-after": match(True),
        "quick-before": match(False), "quick-after": match(True),
    }
    value._match = lambda screen, template, threshold=None: answers[template.name]
    tapped = []
    value._tap = tapped.append

    assert value._give_hearts(object()) == "already_given"
    assert tapped == []
