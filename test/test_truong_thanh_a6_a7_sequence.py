from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(name):
    return SimpleNamespace(found=True, confidence=1.0, name=name, x=10, y=20, width=20, height=10)


def miss(name="miss"):
    return SimpleNamespace(found=False, confidence=0.0, name=name, x=0, y=0, width=0, height=0)


def flow(name, *, repeat=False):
    return module.SubFlow(
        name=name,
        hub_entry=[f"{name}_hub"],
        entry=[f"{name}_entry"],
        free=[f"{name}_free3", f"{name}_free2", f"{name}_free1"],
        spent=[f"{name}_paid"],
        close=[f"{name}_close"],
        repeat_free=repeat,
    )


def test_a6_taps_only_free_3_2_1_then_stops_on_paid_ticket():
    a6 = flow("A6_than-binh", repeat=True)
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(flows=[a6], wait_seconds=0)
    runner.screen_provider = lambda: "hub"
    runner.sleep = lambda _: None
    runner._open_home_entry = lambda: None
    taps = []
    runner._tap = lambda match: taps.append(match.name)

    states = iter(["free3", "free2", "free1", "paid"])
    runner._first = lambda screen, templates, threshold=None: (
        hit(templates[0]) if screen == "hub" and templates == a6.hub_entry else
        hit(templates[0]) if screen == "panel" and templates == a6.entry else
        hit(a6.spent[0]) if screen == "paid" and templates == a6.spent else
        hit(a6.close[0]) if screen == "paid" and templates == a6.close else
        None
    )
    runner._wait_first = lambda templates, attempts=6, threshold=None: (
        ("paid", hit(a6.close[0])) if templates == a6.close else
        ("panel", hit(a6.entry[0])) if a6.entry[0] in templates else (next(states), hit("state"))
    )
    runner._match = lambda screen, template, threshold=None: hit(template) if template == f"A6_than-binh_{screen}" else miss(template)

    runner._run_a6()

    assert taps == [a6.hub_entry[0], a6.entry[0], a6.free[0], a6.free[1], a6.free[2], a6.close[0]]


def test_a7_free_once_then_paid_state_closes():
    a7 = flow("A7_chien-hon")
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(flows=[a7], wait_seconds=0)
    runner.screen_provider = lambda: "hub"
    runner.sleep = lambda _: None
    runner._open_home_entry = lambda: None
    runner._a7_has_free_label = lambda screen: screen == "free"
    taps = []
    runner._tap = lambda match: taps.append(match.name)

    runner._first = lambda screen, templates, threshold=None: (
        hit(templates[0]) if screen == "hub" and templates == a7.hub_entry else
        hit(templates[0]) if screen == "panel" and templates == a7.entry else
        hit(a7.free[0]) if screen == "free" and templates == a7.free else
        hit(a7.spent[0]) if screen == "paid" and templates == a7.spent else
        hit(a7.close[0]) if screen == "paid" and templates == a7.close else
        None
    )
    waits = iter([("panel", hit(a7.entry[0])), ("free", hit(a7.free[0])), ("paid", hit(a7.spent[0]))])
    runner._wait_first = lambda templates, attempts=6, threshold=None: (
        ("paid", hit(a7.close[0])) if templates == a7.close else next(waits)
    )

    runner._run_a7()

    assert taps == [a7.hub_entry[0], a7.entry[0], a7.free[0], a7.close[0]]


def test_a7_never_taps_colliding_free_button_without_free_label():
    a7 = flow("A7_chien-hon")
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(flows=[a7], wait_seconds=0)
    runner.screen_provider = lambda: "hub"
    runner.sleep = lambda _: None
    runner._open_home_entry = lambda: None
    runner._a7_has_free_label = lambda screen: False
    taps = []
    runner._tap = lambda match: taps.append(match.name)
    runner._first = lambda screen, templates, threshold=None: (
        hit(templates[0]) if screen == "hub" and templates == a7.hub_entry else
        hit(templates[0]) if screen == "panel" and templates == a7.entry else
        hit(a7.free[0]) if screen == "paid" and templates == a7.free else
        hit(a7.spent[0]) if screen == "paid" and templates == a7.spent else
        hit(a7.close[0]) if screen == "paid" and templates == a7.close else None
    )
    waits = iter([("panel", hit(a7.entry[0])), ("paid", hit(a7.spent[0]))])
    runner._wait_first = lambda templates, attempts=6, threshold=None: (
        ("paid", hit(a7.close[0])) if templates == a7.close else next(waits)
    )

    runner._run_a7()

    assert taps == [a7.hub_entry[0], a7.entry[0], a7.close[0]]
