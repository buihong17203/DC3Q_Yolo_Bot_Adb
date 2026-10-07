from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(name):
    return SimpleNamespace(found=True, confidence=1.0, name=name, x=10, y=20, width=20, height=10)


def test_a4_free_reward_return_paid_close_recall_home_sequence():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a4_hub_entry=["ve_tuong"], a4_entry=["thien_co_cac"], a4_free=["free"],
        a4_bonus_continue=["continue"], a4_reward=["reward"],
        a4_return=["return"], a4_paid=["paid"],
        a4_close_point=(927, 33), a4_recall=["recall"],
        home_markers=["home"], wait_seconds=0,
    )
    screens = iter([
        "hub", "ve_tuong", "tcc_free", "reward", "reward_done", "tcc_paid",
        "ve_tuong_after_close", "home",
    ])
    runner.screen_provider = lambda: next(screens)
    taps = []
    runner._tap = lambda match: taps.append(match.name)
    runner.input = SimpleNamespace(tap=lambda x, y: taps.append((x, y)))
    runner.sleep = lambda _: None
    runner._open_home_entry = lambda: None

    def first(screen, templates, threshold=None):
        states = {
            ("hub", ("ve_tuong",)): "ve_tuong",
            ("ve_tuong", ("thien_co_cac",)): "thien_co_cac",
            ("tcc_free", ("free",)): "free",
            ("reward", ("continue",)): "continue",
            ("reward_done", ("return",)): "return",
            ("tcc_paid", ("paid",)): "paid",
            ("ve_tuong_after_close", ("recall",)): "recall",
            ("home", ("home",)): "home",
        }
        name = states.get((screen, tuple(templates)))
        return hit(name) if name else None

    runner._first = first
    runner._fresh_proven_free = lambda free, paid, threshold: ("tcc_free", hit("free"))
    waits = iter([
        ("ve_tuong", hit("thien_co_cac")), ("tcc_free", hit("free")),
        ("reward", hit("continue")),
        ("reward_done", hit("return")), ("tcc_paid", hit("paid")),
        ("ve_tuong_after_close", hit("recall")), ("home", hit("home")),
    ])
    runner._wait_first = lambda templates, attempts=6, threshold=None: next(waits)

    runner._run_a4()

    assert taps == [
        "ve_tuong", "thien_co_cac", "free", (480, 360), "return",
        (927, 33), "recall",
    ]
