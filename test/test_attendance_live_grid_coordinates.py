from importlib import import_module
from types import SimpleNamespace


module = import_module("app.actions.dc3q.targets.02_hoat-dong")


def test_day_5_and_6_use_real_nine_column_grid_centers():
    taps = []
    runner = object.__new__(module.HoatDongRunner)
    runner.config = SimpleNamespace(attendance_grid=(238, 199, 913, 500), wait_seconds=0)
    runner.input = SimpleNamespace(tap=lambda x, y: taps.append((x, y)))
    runner.sleep = lambda _: None

    runner._tap_attendance(4)  # saved day 4 -> click day 5
    runner._tap_attendance(5)  # saved day 5 -> click day 6

    assert taps == [(576, 237), (650, 237)]