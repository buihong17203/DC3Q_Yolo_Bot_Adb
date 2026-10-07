from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(name, confidence=1.0):
    return SimpleNamespace(found=True, confidence=confidence, name=name, x=0, y=0, width=20, height=10)


def miss(name, confidence=0.0):
    return SimpleNamespace(found=False, confidence=confidence, name=name, x=0, y=0, width=20, height=10)


def test_a2_handles_reward_chest_2000_then_stops_before_paid_probe():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a2_free="free", a2_paid="paid", a2_rewards=["reward"],
        a2_reward_close="reward_close", a2_chest_glowing="chest_glowing",
        a2_chest_popup="chest_popup", a2_chest_popup_close="chest_close",
        a2_chest_popup_close_point=(481, 456),
        a2_reset_2000="reset_2000", state_threshold=.80, state_margin=.05,
        wait_seconds=0,
    )
    runner.sleep = lambda _: None
    screens = iter([
        "reward_screen", "land_after_reward", "chest_popup_screen",
        "land_after_chest", "land_after_reset", "paid_screen",
    ])
    runner.screen_provider = lambda: next(screens)
    taps = []
    runner._tap = lambda match: taps.append(match.name)
    runner.input = SimpleNamespace(tap=lambda x, y: taps.append("coordinate_tap"))
    runner._a2_state = lambda screen: (
        (hit("free"), miss("paid", .2))
        if screen in {"initial_land", "land_after_reset"}
        else (miss("free", .2), hit("paid"))
    )

    def first(screen, templates, threshold=None):
        found = {
            ("reward_screen", ("reward",)): "reward",
            ("reward_screen", ("reward_close",)): "reward_close",
            ("land_after_reward", ("chest_glowing",)): "chest_glowing",
            ("chest_popup_screen", ("chest_popup",)): "chest_popup",
            ("chest_popup_screen", ("chest_close",)): "chest_close",
            ("land_after_chest", ("reset_2000",)): "reset_2000",
        }.get((screen, tuple(templates)))
        return hit(found) if found else None

    runner._first = first
    runner._match = lambda screen, template, threshold=None: (
        first(screen, [template], threshold) or miss(str(template))
    )

    runner._a2_claim_free("initial_land")

    assert taps == ["free", "reward_close", "chest_glowing", "coordinate_tap", "reset_2000", "free"]


def test_a2_opens_tuong_tinh_dai_tab_before_exploration():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a2_entry="a2_entry", a2_main=["legacy_main"],
        a2_tab_closed=["tab_closed"], a2_tab_open=["tab_open"],
        a2_open=["explore_entry"], a2_free="free", a2_paid="paid",
        threshold=.70, state_margin=.05,
    )
    runner._open_home_entry = lambda: None
    runner.screen_provider = lambda: "hub"
    taps = []
    runner._tap = lambda match: taps.append(match.name)
    runner._match = lambda screen, template, threshold=None: (
        hit("a2_entry") if template == "a2_entry" else
        hit("tab_closed", 1.0) if template == "tab_closed" else
        hit("tab_open", .80)
    )
    waits = iter([
        ("tuong_an", hit("tab_closed")),
        ("tuong_tinh_dai", hit("tab_open")),
        ("explore_land", hit("free")),
    ])
    runner._wait_first = lambda templates, attempts=6, threshold=None: next(waits)
    runner._first = lambda screen, templates, threshold=None: (
        hit("tab_closed") if screen == "tuong_an" and templates == ["tab_closed"] else
        hit("explore_entry") if screen == "tuong_tinh_dai" and templates == ["explore_entry"] else None
    )
    runner._a2_claim_free = lambda screen: taps.append("claim_loop")

    runner._run_a2()

    assert taps == ["a2_entry", "tab_closed", "explore_entry", "claim_loop"]


def test_a2_opens_ready_chest_before_any_free_probe():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a2_free="free", a2_paid="paid", a2_rewards=["reward"],
        a2_reward_close="reward_close", a2_chest_glowing="chest",
        a2_chest_popup="popup", a2_chest_popup_close="close",
        a2_chest_popup_close_point=(481, 456),
        a2_reset_2000="reset", state_threshold=.80, state_margin=.05,
        wait_seconds=0,
    )
    runner.sleep = lambda _: None
    screens = iter(["popup_screen", "after_chest", "paid"])
    runner.screen_provider = lambda: next(screens)
    taps = []
    runner._tap = lambda match: taps.append(match.name)
    runner.input = SimpleNamespace(tap=lambda x, y: taps.append("coordinate_tap"))
    runner._a2_state = lambda screen: (
        (hit("free"), miss("paid")) if screen == "chest_and_free"
        else (miss("free"), hit("paid"))
    )
    states = {
        ("chest_and_free", "chest"): hit("chest"),
        ("popup_screen", "popup"): hit("popup"),
        ("popup_screen", "close"): hit("close"),
    }
    runner._match = lambda screen, template, threshold=None: states.get(
        (screen, template), miss(str(template)),
    )
    runner._first = lambda screen, templates, threshold=None: next(
        (states[(screen, template)] for template in templates if (screen, template) in states), None,
    )

    runner._a2_claim_free("chest_and_free")

    assert taps == ["chest", "coordinate_tap"]


def test_a2_closes_proven_chest_popup_by_fixed_point_until_popup_disappears():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a2_chest_popup="popup", a2_chest_popup_close_point=(481, 456), wait_seconds=0,
    )
    runner.sleep = lambda _: None
    frames = iter(["popup_still_open", "land"])
    runner.screen_provider = lambda: next(frames)
    runner._match = lambda screen, template, threshold=None: (
        hit("popup") if screen != "land" else miss("popup")
    )
    taps = []
    runner.input = SimpleNamespace(tap=lambda x, y: taps.append((x, y)))

    screen = runner._close_a2_chest_popup("popup")

    assert screen == "land"
    assert taps == [(481, 456), (481, 456)]
