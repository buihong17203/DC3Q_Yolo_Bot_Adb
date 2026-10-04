from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(x=10, y=20):
    return SimpleNamespace(found=True, confidence=1.0, x=x, y=y, width=20, height=10)


def test_a1_selects_cards_until_execute_then_proves_running():
    runner = object.__new__(module.TruongThanhRunner)
    calls = []
    runner.config = SimpleNamespace(a1_card_centers=[(550, 370), (648, 370), (747, 370), (845, 370)], wait_seconds=0)
    runner.input = SimpleNamespace(tap=lambda x, y: calls.append((x, y)))
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    plus_counts = iter([4, 3, 2, 1, 0])
    runner._a1_plus_count = lambda screen: next(plus_counts)
    runner._first = lambda screen, templates: hit() if templates == runner.config.a1_execute else None
    runner._tap = lambda match: calls.append(("execute",))
    runner._wait_first = lambda templates, attempts=6: (object(), hit())
    runner.config.a1_execute = ["execute"]
    runner.config.a1_running = ["running"]

    runner._a1_fill_and_execute(object())

    assert calls == [(550, 370), (648, 370), (747, 370), (845, 370), ("execute",)]


def test_recovery_closes_open_hub_before_accepting_home():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        hub_markers=["a1"], entry_templates=["toggle"], home_markers=["home"],
        close_templates=[], wait_seconds=0,
    )
    screens = iter(["hub", "home"])
    runner.screen_provider = lambda: next(screens)
    runner.sleep = lambda _: None
    taps = []
    runner._tap = taps.append
    runner._first = lambda screen, templates: (
        hit() if (screen == "hub" and templates in (["a1"], ["toggle"]))
        or (screen == "home" and templates == ["home"]) else None
    )

    assert runner.recover_home() is True
    assert len(taps) == 1
