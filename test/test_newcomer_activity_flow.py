from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.02_hoat-dong")


class Input:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))


def match(found=True, x=10, y=20, confidence=1.0):
    return SimpleNamespace(found=found, confidence=confidence, x=x, y=y, width=20, height=10)


def test_optional_newcomer_absence_does_not_tap_or_fail():
    runner = object.__new__(module.HoatDongRunner)
    runner.input = Input()
    runner.config = SimpleNamespace(
        newcomer_tabs=[Path("newcomer-closed.png")],
        newcomer_open=[Path("newcomer-open.png")],
        threshold=0.65,
    )
    runner._tab_state = lambda screen, closed, opened: ("unknown", None, None)

    assert runner._open_newcomer_if_present(object()) is None
    assert runner.input.taps == []


def test_newcomer_claims_every_visible_vassal_reward():
    runner = object.__new__(module.HoatDongRunner)
    runner.input = Input()
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    runner.config = SimpleNamespace(
        newcomer_vassal_claimable=Path("claim.png"),
        newcomer_reward_marker=Path("reward.png"),
        newcomer_reward_dismiss=Path("dismiss.png"),
        wait_seconds=0,
    )
    phases = iter([[match(x=10), match(x=40)], [match(x=40)], []])
    runner._all_matches = lambda screen, template, threshold=0.95: next(phases)
    runner._wait_newcomer_reward = lambda: object()

    runner._claim_newcomer_vassal_rewards(object())

    assert runner.input.taps == [(20, 25), (50, 25)]


def test_newcomer_processing_returns_to_welfare_after_safe_tabs():
    runner = object.__new__(module.HoatDongRunner)
    calls = []
    runner.config = SimpleNamespace(
        newcomer_vassal_tabs=[Path("vassal-c.png")],
        newcomer_vassal_open=[Path("vassal-o.png")],
        newcomer_offer_tabs=[Path("offer-c.png")],
        newcomer_offer_open=[Path("offer-o.png")],
        newcomer_seven_day_tabs=[Path("seven-c.png")],
        newcomer_seven_day_open=[Path("seven-o.png")],
        newcomer_login_tabs=[Path("login-c.png")],
        newcomer_login_open=[Path("login-o.png")],
        welfare_tabs=[Path("welfare-c.png")],
        welfare_open=[Path("welfare-o.png")],
    )
    runner._open_tab = lambda screen, closed, opened, name, **kwargs: calls.append(name) or object()
    runner._claim_newcomer_vassal_rewards = lambda screen: calls.append("claim-vassal") or object()
    runner._claim_newcomer_single_reward = lambda screen, kind: calls.append(f"claim-{kind}") or object()

    runner._process_newcomer(object())

    assert calls == [
        "Chư hầu chi thủy", "claim-vassal",
        "Ưu đãi tân thủ", "claim-offer",
        "Quà 7 ngày", "claim-seven_day",
        "Đăng nhập tích lũy", "claim-login",
        "Phúc lợi",
    ]
