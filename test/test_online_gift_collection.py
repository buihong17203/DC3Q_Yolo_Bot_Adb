from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.02_hoat-dong")


class Input:
    def __init__(self):
        self.taps = []
        self.swipes = []

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, *args):
        self.swipes.append(args)


def match(x):
    return SimpleNamespace(found=True, x=x, y=200, width=20, height=10, confidence=1.0)


def test_online_claims_every_claimable_and_never_taps_unavailable():
    input_ = Input()
    runner = object.__new__(module.HoatDongRunner)
    runner.input = input_
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    runner.config = SimpleNamespace(
        online_claimable=Path("claim.png"), online_unavailable=Path("locked.png"),
        online_claimed=Path("claimed.png"), state_threshold=0.76, wait_seconds=0,
        reward_marker=Path("reward.png"), reward_dismiss=Path("dismiss.png"),
    )
    phases = iter([[match(100), match(200)], [match(200)], [], [], []])
    runner._all_matches = lambda screen, template, threshold=None: next(phases)
    counts = iter([(0, 1, 2), (0, 1, 2)])
    runner._online_counts = lambda screen: next(counts)
    runner._reward = lambda screen: True

    runner._claim_online(object())

    assert input_.taps == [(110, 205), (210, 205)]
    assert input_.swipes == [(700, 440, 700, 300, 900)]
