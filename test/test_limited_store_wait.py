from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.03_cua-hang")


def test_each_limited_tab_waits_for_slow_catalog_after_tap():
    waits = []
    runner = object.__new__(module.CuaHangRunner)
    runner.sleep = waits.append
    runner.screen_provider = lambda: object()
    runner.config = SimpleNamespace(
        limited_tabs_closed=[[Path("day-closed")], [Path("week-closed")], [Path("month-closed")]],
        limited_tabs_open=[[Path("day-open")], [Path("week-open")], [Path("month-open")]],
        limited_wait_seconds=2.5,
        wait_seconds=0.8,
        threshold=0.6,
    )
    selected = set()

    def best(screen, templates):
        name = templates[0].name
        period = name.split("-")[0]
        is_open = name.endswith("open")
        confidence = 1.0 if ((period in selected) == is_open) else 0.0
        return SimpleNamespace(found=bool(confidence), confidence=confidence, period=period)

    runner._best = best
    runner._tap = lambda match: selected.add(match.period)
    runner._limited_offer_state = lambda screen: ("claimed", None)

    runner._run_limited_tabs(object())

    assert selected == {"day", "week", "month"}
    assert waits.count(2.5) >= 3
