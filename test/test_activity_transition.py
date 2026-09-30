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


def found(x=100, y=100):
    return SimpleNamespace(found=True, confidence=1.0, x=x, y=y, width=20, height=10)


def missing():
    return SimpleNamespace(found=False, confidence=0.0, x=0, y=0, width=20, height=10)


def test_online_has_four_milestones_and_scrolls_at_most_once():
    runner = object.__new__(module.HoatDongRunner)
    runner.input = Input()
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    runner.config = SimpleNamespace(
        online_claimable=Path("claim.png"), online_unavailable=Path("locked.png"),
        online_claimed=Path("claimed.png"), wait_seconds=0,
    )
    claim_phases = iter([[found(100), found(200)], [found(200)], [], [found(300)], [], []])
    runner._all_matches = lambda screen, template, threshold=None: (
        next(claim_phases) if template == runner.config.online_claimable else []
    )
    runner._online_counts = lambda screen: (0, 2, 2)
    runner._reward = lambda screen: True

    runner._claim_online(object())

    assert runner.input.taps == [(110, 105), (210, 105), (310, 105)]
    assert len(runner.input.swipes) == 1


def test_attendance_is_clicked_directly_after_online_without_scrolling():
    runner = object.__new__(module.HoatDongRunner)
    runner.input = Input()
    runner.sleep = lambda _: None
    screens = iter([object()])
    runner.screen_provider = lambda: next(screens)
    runner.config = SimpleNamespace(
        attendance_tabs=[Path("attendance-closed.png")],
        attendance_open=[Path("attendance-open.png")],
        threshold=0.65,
        wait_seconds=0,
    )
    runner._best = lambda screen, templates: found(99, 362)
    runner._first = lambda screen, templates: found() if templates == runner.config.attendance_open else None

    runner._open_attendance_tab(object())

    assert runner.input.taps == [(109, 367)]
    assert runner.input.swipes == []
