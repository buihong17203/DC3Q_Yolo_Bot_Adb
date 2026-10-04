from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).parents[1]
module = import_module("app.actions.dc3q.targets.04_quan-doan")


def match(found, confidence=1.0, x=0, y=0):
    return SimpleNamespace(found=found, confidence=confidence, x=x, y=y, width=20, height=20)


def anchored_runner():
    runner = object.__new__(module.QuanDoanRunner)
    runner.config = SimpleNamespace(
        entry_templates=[Path("screen_quan-doan_01.png"), Path("screen_quan-doan_02.png")],
        home_anchor=Path("screen_truong-thanh_01.png"), threshold=0.65,
        home_control_threshold=0.28,
    )
    runner._screen_size = lambda screen: (960, 540)
    runner._match = lambda screen, template, threshold=None: match(True, .99, 0, 264)
    return runner


def test_quan_doan_uses_truong_thanh_anchor_then_taps_02_at_right_edge():
    runner = anchored_runner()
    calls = []
    runner._match_roi = lambda screen, template, roi, threshold=None: (
        calls.append((template.name, roi, threshold)) or
        (match(True, .319, 934, 220) if template.name == "screen_quan-doan_02.png" else match(False))
    )

    state, control = runner._home_entry_state(object())

    assert state == "closed"
    assert control.x == 934
    assert calls[0][0] == "screen_quan-doan_01.png"
    assert calls[1][0] == "screen_quan-doan_02.png"
    assert calls[1][1][0] >= 780
    assert calls[1][1][1] >= 204
    assert calls[1][2] == .28


def test_quan_doan_uses_truong_thanh_anchor_then_finds_01_near_center():
    runner = anchored_runner()
    calls = []
    runner._match_roi = lambda screen, template, roi, threshold=None: (
        calls.append((template.name, roi)) or
        (match(True, .95, 426, 218) if template.name == "screen_quan-doan_01.png" else match(False))
    )

    state, control = runner._home_entry_state(object())

    assert state == "open"
    assert control.x == 426
    assert calls[0][0] == "screen_quan-doan_01.png"
    assert calls[0][1][0] < 480 < calls[0][1][2]


def test_quan_doan_open_01_wins_over_false_positive_02():
    runner = anchored_runner()
    runner._match_roi = lambda screen, template, roi, threshold=None: (
        match(True, .443, 433, 174)
        if template.name == "screen_quan-doan_01.png"
        else match(True, .321, 885, 221)
    )

    state, control = runner._home_entry_state(object())

    assert state == "open"
    assert control.x == 433


def test_quan_doan_does_not_tap_open_toggle_again():
    runner = object.__new__(module.QuanDoanRunner)
    opened_toggle = match(True, 1.0, 426, 218)
    prayer_close = match(True, 1.0, 10, 10)
    panel_close = match(True, 1.0, 20, 20)
    runner.config = SimpleNamespace(
        prayer_close=Path("prayer-close"), close_template=Path("panel-close"),
    )
    runner._open_home_entry = lambda screen: ("route-loading", opened_toggle)
    runner.screen_provider = lambda: "fresh"
    runner._enter_real_guild = lambda: "guild"
    runner._register = lambda screen: None
    runner._open_prayer = lambda screen: "prayer"
    runner._run_prayer = lambda screen: None
    route_closed = []
    runner._close_home_route = lambda: route_closed.append(True)
    runner._match = lambda screen, template, threshold=None: (
        prayer_close if template.name == "prayer-close" else panel_close
    )
    taps = []
    runner._tap = taps.append
    runner.recover_home = lambda: True

    assert runner.run() is True
    assert opened_toggle not in taps
    assert taps == [prayer_close, panel_close]
    assert route_closed == [True]


def test_quan_doan_clicks_enter_button_before_waiting_for_real_panel():
    runner = object.__new__(module.QuanDoanRunner)
    enter = Path("screen_home_button_open_quandoan.png")
    panel = Path("real-panel.png")
    runner.config = SimpleNamespace(
        entrance_templates=[enter], panel_markers=[panel], entrance_wait_attempts=24,
        wait_seconds=0,
    )
    button_match = match(True, 1.0, 300, 200)
    panel_match = match(True, 1.0, 10, 10)
    calls = []
    runner._wait_for = lambda templates, attempts=8: (
        calls.append((list(templates), attempts)) or
        (("route-screen", button_match) if templates == [enter] else ("guild-screen", panel_match))
    )
    runner._tap = lambda found: calls.append(("tap", found))

    screen = runner._enter_real_guild()

    assert screen == "guild-screen"
    assert calls == [([enter], 24), ("tap", button_match), ([panel], 8)]


def test_quan_doan_route_accepts_enter_button_as_open_postcondition():
    runner = anchored_runner()
    runner.config.entrance_templates = [Path("screen_home_button_open_quandoan.png")]
    runner.config.entrance_wait_attempts = 24
    runner.config.wait_seconds = 0
    closed = match(True, .95, 927, 213)
    entrance = match(True, .99, 628, 472)
    states = iter([("closed", closed), ("closed", closed)])
    runner._home_entry_state = lambda screen: next(states)
    runner._first = lambda screen, templates, threshold=None: entrance
    runner.screen_provider = lambda: "route"
    runner.sleep = lambda _: None
    tapped = []
    runner._tap = tapped.append

    screen, proof = runner._open_home_entry("home")

    assert screen == "route"
    assert proof is entrance
    assert tapped == [closed]


def test_quan_doan_recovery_closes_open_route_after_panel_close():
    runner = object.__new__(module.QuanDoanRunner)
    runner.config = SimpleNamespace(
        prayer_close=Path("prayer-close"), panel_markers=[Path("panel")],
        close_template=Path("panel-close"), home_markers=[Path("home")],
        wait_seconds=0,
    )
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: "open-route"
    runner._match = lambda screen, template, threshold=None: match(False)
    runner._first = lambda screen, templates, threshold=None: None
    runner._home_entry_state = lambda screen: ("open", match(True, .99, 430, 220))
    closed = []
    runner._close_home_route = lambda: closed.append(True)

    assert runner.recover_home() is True
    assert closed == [True]


def test_enabled_event_menu_targets_use_distinct_closed_and_open_images():
    for name in ["01_tam-quoc-lenh", "02_hoat-dong", "03_cua-hang", "06_xa-giao"]:
        data = yaml.safe_load((ROOT / f"config/dc3q/targets/{name}.yaml").read_text(encoding="utf-8"))
        cfg = data[next(iter(data))]
        assert [Path(p).name for p in cfg["home"]["menu"]] == [
            "screen_home_menu_sukien_dangdong.png",
            "screen_home_menu_sukien_dangmo.png",
        ]
