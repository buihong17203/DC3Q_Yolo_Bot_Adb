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
    assert calls[1][1][1] >= 160
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


def test_quan_doan_khu_2_open_wins_when_khu_1_is_still_visible():
    runner = anchored_runner()
    runner._match_roi = lambda screen, template, roi, threshold=None: (
        match(True, .443, 433, 174)
        if template.name == "screen_quan-doan_01.png"
        else match(True, .321, 885, 221)
    )

    state, control = runner._home_entry_state(object())

    assert state == "open"
    assert control.x == 433


def test_quan_doan_checks_both_areas_without_truong_thanh_anchor():
    runner = anchored_runner()
    runner._match = lambda screen, template, threshold=None: match(False)
    calls = []
    runner._match_roi = lambda screen, template, roi, threshold=None: (
        calls.append((template.name, roi)) or
        (match(True, .95, 426, 218) if template.name == "screen_quan-doan_01.png" else match(False))
    )

    state, control = runner._home_entry_state(object())

    assert state == "open"
    assert control.x == 426
    assert [name for name, _ in calls] == ["screen_quan-doan_01.png"]


def test_quan_doan_rejects_weak_01_collision_on_clean_home():
    runner = anchored_runner()
    thresholds = []

    def match_roi(screen, template, roi, threshold=None):
        thresholds.append((template.name, threshold))
        confidence = .288 if template.name == "screen_quan-doan_01.png" else .227
        return match(confidence >= threshold, confidence, 474, 237)

    runner._match_roi = match_roi
    state, control = runner._home_entry_state(object())

    assert state == "unknown"
    assert control is None
    assert thresholds == [
        ("screen_quan-doan_01.png", .40),
        ("screen_quan-doan_02.png", .28),
    ]


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


def test_quan_doan_uses_visible_enter_button_without_edge_spam():
    runner = anchored_runner()
    runner.config.entrance_templates = [Path("screen_home_button_open_quandoan.png")]
    entrance = match(True, .99, 628, 472)
    runner._home_entry_state = lambda screen: ("closed", match(True, .95, 927, 213))
    runner._first = lambda screen, templates, threshold=None: entrance
    tapped = []
    runner.input = SimpleNamespace(tap=lambda x, y: tapped.append((x, y)))

    screen, proof = runner._open_home_entry("home")

    assert screen == "home"
    assert proof is entrance
    assert tapped == []


def test_quan_doan_spams_right_edge_center_until_enter_button_appears():
    runner = anchored_runner()
    runner.config.entrance_templates = [Path("screen_home_button_open_quandoan.png")]
    runner.config.entrance_wait_attempts = 4
    runner.config.wait_seconds = 0
    runner.screen_provider = lambda: "fresh"
    runner._home_entry_state = lambda screen: ("unknown", None)
    entrance = match(True, .99, 628, 472)
    checks = iter([None, None, entrance])
    runner._first = lambda screen, templates, threshold=None: next(checks)
    taps = []
    runner.input = SimpleNamespace(tap=lambda x, y: taps.append((x, y)))
    runner.sleep = lambda _: None

    screen, proof = runner._open_home_entry("home")

    assert screen == "fresh"
    assert proof is entrance
    assert taps == [(928, 270), (928, 270)]


def test_quan_doan_closes_route_with_quan_chhuc_then_proves_home():
    runner = object.__new__(module.QuanDoanRunner)
    runner.config = SimpleNamespace(
        route_home=Path("screen_quan-chhuc.png"),
        home_markers=[Path("home")], wait_seconds=0,
    )
    frames = iter(["route", "home"])
    runner.screen_provider = lambda: next(frames)
    quan_chhuc = match(True, .99, 100, 200)
    runner._match = lambda screen, template, threshold=None: (
        quan_chhuc if screen == "route" and template.name == "screen_quan-chhuc.png"
        else match(False)
    )
    runner._first = lambda screen, templates, threshold=None: (
        match(True, .99) if screen == "home" and templates == [Path("home")] else None
    )
    tapped = []
    runner._tap = tapped.append
    runner.sleep = lambda _: None

    runner._close_home_route()

    assert tapped == [quan_chhuc]


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
