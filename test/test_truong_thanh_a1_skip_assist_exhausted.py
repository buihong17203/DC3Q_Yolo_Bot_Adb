from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=1, x=1, y=1, width=2, height=2)


def test_assistance_exhausted_goes_back_and_tries_next_mission():
    value = object.__new__(module.TruongThanhRunner)
    value.config = SimpleNamespace(
        a1_entry="entry", a1_reward="reward", a1_view="view", a1_running=["running"],
        a1_plus_slot="plus", a1_back_point=(85, 77),
        a1_board_swipe=(700, 440, 700, 180, 450), a1_max_board_swipes=2,
        a1_close_point=(932, 28), hub_markers=["hub"],
        a1_execution_count_roi=(1, 2, 3, 4), wait_seconds=0,
    )
    value._open_home_entry = lambda: None
    value.screen_provider = lambda: "board"
    value._match = lambda *args, **kwargs: hit()
    value._wait_first = lambda *args, **kwargs: ("board", hit())
    value._a1_claim_rewards = lambda screen: screen
    opened = iter([("detail1", 5), ("detail2", 5), None])
    value._a1_open_next_mission = lambda screen: next(opened)
    outcomes = iter([False, True])
    value._a1_fill_and_execute = lambda screen: next(outcomes)
    value._read_roi_number = lambda screen, roi: 4
    taps, swipes = [], []
    value.input = SimpleNamespace(
        tap=lambda *point: taps.append(point),
        swipe=lambda *args: swipes.append(args),
    )
    value.sleep = lambda _: None

    value._run_a1()

    assert (85, 77) in taps
    assert swipes == []  # _a1_open_next_mission owns each bounded search sweep.


def test_each_search_swipes_slowly_then_clicks_first_view_found():
    value = object.__new__(module.TruongThanhRunner)
    value.config = SimpleNamespace(
        a1_view="view", a1_execution_count_roi=(1, 2, 3, 4),
        a1_board_swipe=(700, 440, 700, 180, 900),
        a1_max_board_swipes=2, wait_seconds=0,
    )
    value._read_roi_number = lambda screen, roi: 5
    matches = iter([
        SimpleNamespace(found=False),
        SimpleNamespace(found=True, x=800, y=380, width=100, height=40),
    ])
    value._match = lambda *args, **kwargs: next(matches)
    screens = iter(["after_slow_swipe", "detail"])
    value.screen_provider = lambda: next(screens)
    taps, swipes = [], []
    value._tap = lambda match: taps.append(match)
    value.input = SimpleNamespace(swipe=lambda *args: swipes.append(args))
    value.sleep = lambda _: None

    assert value._a1_open_next_mission("four_speedup_rows") == ("detail", 5)
    assert swipes == [(700, 440, 700, 180, 900)]
    assert len(taps) == 1
