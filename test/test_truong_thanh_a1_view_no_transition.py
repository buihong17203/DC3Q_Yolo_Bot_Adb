from importlib import import_module
from types import SimpleNamespace


module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(found=True):
    return SimpleNamespace(found=found, x=790, y=335, width=123, height=51)


def test_a1_view_without_detail_transition_stops_boundedly():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a1_view="view", a1_plus_slot="plus",
        a1_execution_count_roi=(1, 2, 3, 4),
        a1_board_swipe=(1, 2, 3, 4, 5), a1_max_board_swipes=2,
        wait_seconds=0,
    )
    runner._read_roi_number = lambda screen, roi: 1
    runner._a1_board_verified = lambda screen: True
    runner._match = lambda screen, template, threshold=None: hit(template == "view")
    taps = []
    runner._tap = lambda match: taps.append((match.x, match.y))
    runner.screen_provider = lambda: "still-board"
    runner.sleep = lambda _: None

    assert runner._a1_open_next_mission("board") is None
    assert taps == [(790, 335)]


def test_a1_never_taps_speedup_false_match_as_view():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a1_view="view", a1_reward="reward", a1_running=["running"],
        a1_execution_count_roi=(1, 2, 3, 4),
        a1_board_swipe=(1, 2, 3, 4, 5), a1_max_board_swipes=0,
        wait_seconds=0,
    )
    runner._read_roi_number = lambda screen, roi: 2
    runner._a1_board_verified = lambda screen: True
    thresholds = []
    runner._match = lambda screen, template, threshold=None: (
        thresholds.append(threshold) or hit(False)
    )
    taps = []
    runner._tap = lambda match: taps.append(match)

    assert runner._a1_open_next_mission("speedup-only-board") is None
    assert thresholds == [0.95]
    assert taps == []


def test_a1_does_not_swipe_without_verified_mission_board():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a1_view="view", a1_reward="reward", a1_running=["running"],
        a1_execution_count_roi=(1, 2, 3, 4),
        a1_board_swipe=(700, 440, 700, 180, 900), a1_max_board_swipes=2,
        wait_seconds=0,
    )
    runner._read_roi_number = lambda screen, roi: 2
    runner._match = lambda screen, template, threshold=None: hit(False)
    runner._first = lambda screen, templates, threshold=None: None
    swipes = []
    runner.input = SimpleNamespace(swipe=lambda *args: swipes.append(args))

    assert runner._a1_open_next_mission("unknown-screen") is None
    assert swipes == []


def test_recovery_closes_verified_a1_board_with_configured_x():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        bonus_continue_templates=[], a4_return_templates=[], hub_markers=[],
        home_markers=["home"], close_templates=[], entry_templates=[],
        a1_view="view", a1_reward="reward", a1_close_point=(932, 28),
        wait_seconds=0,
    )
    frames = iter(["board", "home"])
    runner.screen_provider = lambda: next(frames)
    runner._first = lambda screen, templates, threshold=None: (
        hit() if screen == "home" and templates == ["home"] else None
    )
    runner._match = lambda screen, template, threshold=None: hit(screen == "board" and template == "view")
    taps = []
    runner.input = SimpleNamespace(
        tap=lambda x, y: taps.append((x, y)), recover_anr_wait=lambda: False,
    )
    runner.sleep = lambda _: None

    assert runner.recover_home() is True
    assert taps == [(932, 28)]