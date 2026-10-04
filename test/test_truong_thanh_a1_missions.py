from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(name="hit"):
    return SimpleNamespace(found=True, confidence=1.0, x=10, y=20, width=20, height=10, name=name)


def runner():
    value = object.__new__(module.TruongThanhRunner)
    value.config = SimpleNamespace(
        a1_reward="reward", a1_view="view", a1_execution_count_roi=(680, 475, 885, 540),
        a1_board_swipe=(700, 440, 700, 180, 450), a1_max_board_swipes=2,
        a1_assist="assist", a1_assist_count_roi=(310, 440, 480, 500),
        a1_assist_popup="popup", a1_assist_confirm="confirm", wait_seconds=0,
    )
    value.sleep = lambda _: None
    return value


def test_a1_claims_every_visible_reward_then_sweeps_board():
    value = runner()
    screens = iter(["after_claim_1", "after_claim_2", "after_swipe_1", "after_swipe_2"])
    value.screen_provider = lambda: next(screens)
    rewards = iter([hit("r1"), hit("r2"), None, None, None])
    value._match = lambda screen, template, threshold=None: next(rewards)
    taps, swipes = [], []
    value._tap = lambda match: taps.append(match.name)
    value.input = SimpleNamespace(swipe=lambda *args: swipes.append(args))

    value._a1_claim_rewards("start")

    assert taps == ["r1", "r2"]
    assert swipes == [(700, 440, 700, 180, 450), (700, 440, 700, 180, 450)]


def test_a1_zero_or_unreadable_execution_count_never_opens_view():
    value = runner()
    value._read_roi_number = lambda screen, roi: 0
    value._match = lambda screen, template, threshold=None: hit("view")
    taps = []
    value._tap = taps.append

    assert value._a1_open_next_mission("board") is None
    assert taps == []


def test_a1_assist_requires_positive_counter_and_decremented_postcondition():
    value = runner()
    values = iter([2, 1])
    value._read_roi_number = lambda screen, roi: next(values)
    value._match = lambda screen, template, threshold=None: hit(template)
    screens = iter(["popup", "after"])
    value.screen_provider = lambda: next(screens)
    taps = []
    value._tap = lambda match: taps.append(match.name)

    assert value._a1_request_assistance("detail") == "after"
    assert taps == ["assist", "confirm"]


def test_a1_assist_at_zero_does_nothing():
    value = runner()
    value._read_roi_number = lambda screen, roi: 0
    value._match = lambda screen, template, threshold=None: hit(template)
    taps = []
    value._tap = taps.append

    assert value._a1_request_assistance("detail") is None
    assert taps == []
