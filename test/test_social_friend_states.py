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


def test_home_social_and_friend_icons_include_both_variants():
    cfg = yaml.safe_load((ROOT / "config/dc3q/targets/06_xa-giao.yaml").read_text(encoding="utf-8"))["xa_giao"]
    assert [Path(p).name for p in cfg["home"]["entry"]] == [
        "screen_xa-giao_01.png", "screen_xa-giao_02.png",
    ]
    assert [Path(p).name for p in cfg["friends"]["entry"]] == [
        "screen_ban-be_01.png", "screen_ban-be_02.png",
    ]
    assert all((ROOT / p).is_file() for p in cfg["home"]["entry"] + cfg["friends"]["entry"])


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


def test_run_closes_social_menu_after_friend_panel():
    value = runner()
    social = match(True, .99)
    panel_close = match(True, .99)
    value.config = SimpleNamespace(
        close_template=Path("panel-close"),
        entry_templates=[Path("social-01"), Path("social-02")],
        social_control_threshold=.55,
    )
    value._open_panel = lambda: "friends"
    value._give_hearts = lambda screen: "already_given"
    frames = iter(["panel", "home-menu-open"])
    value.screen_provider = lambda: next(frames)
    value._match = lambda screen, template, threshold=None: panel_close
    value._first = lambda screen, templates, threshold=None: social
    tapped = []
    value._tap = tapped.append
    value.recover_home = lambda: True

    assert value.run() is True
    assert tapped == [panel_close, social]


def test_recover_home_uses_home_threshold_not_social_state_threshold():
    value = runner()
    value.config = SimpleNamespace(
        home_markers=[Path("home.png")], panel_markers=[Path("panel.png")],
        close_template=Path("close.png"), home_threshold=.65,
        wait_seconds=0,
    )
    value.screen_provider = lambda: "home"
    calls = []
    value._first = lambda screen, templates, threshold=None: (
        calls.append((templates, threshold)) or
        (match(True, .656) if templates == value.config.home_markers else None)
    )

    assert value.recover_home() is True
    assert calls[0][1] == .65


def test_open_panel_uses_visible_friend_without_reopening_social_menu():
    value = runner()
    friend = match(True, .973)
    value.config = SimpleNamespace(
        panel_markers=[Path("panel")], friend_templates=[Path("friend")],
        entry_templates=[Path("social")], menu_templates=[Path("closed"), Path("open")],
    )
    value.screen_provider = lambda: "home-social-open"
    value._first = lambda screen, templates, threshold=None: (
        friend if templates == value.config.friend_templates else None
    )
    taps = []
    value._tap = taps.append
    value._prove = lambda templates, message: "friends-panel"

    assert value._open_panel() == "friends-panel"
    assert taps == [friend]


def test_run_finds_social_close_icon_with_dedicated_threshold():
    value = runner()
    social = match(True, .590)
    panel_close = match(True, .996)
    value.config = SimpleNamespace(
        close_template=Path("panel-close"),
        entry_templates=[Path("social-01"), Path("social-02")],
        social_control_threshold=.55,
    )
    value._open_panel = lambda: "friends"
    value._give_hearts = lambda screen: "already_given"
    value.screen_provider = iter(["panel", "home-menu-open"]).__next__
    value._match = lambda screen, template, threshold=None: panel_close
    calls = []
    value._first = lambda screen, templates, threshold=None: (
        calls.append(threshold) or social
    )
    value._tap = lambda match: None
    value.recover_home = lambda: True

    assert value.run() is True
    assert calls == [.55]
