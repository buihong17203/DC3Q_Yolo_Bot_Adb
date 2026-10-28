import sys
import importlib.util
from pathlib import Path
import numpy as np
import pytest

# Load 02_hoat-dong dynamically
spec = importlib.util.spec_from_file_location("hoat_dong_module", "app/actions/dc3q/targets/02_hoat-dong.py")
hd_mod = importlib.util.module_from_spec(spec)
sys.modules["hoat_dong_module"] = hd_mod
spec.loader.exec_module(hd_mod)

from app.accounts.writer import read_attendance_day, write_attendance_day, write_accounts


def test_attendance_coordinates_geometry():
    coords = hd_mod.ATTENDANCE_COORDINATES
    assert len(coords) == 30, f"Expected 30 coordinates, got {len(coords)}"
    # 4 rows: 9 + 9 + 9 + 3
    row0 = coords[0:9]
    row1 = coords[9:18]
    row2 = coords[18:27]
    row3 = coords[27:30]
    
    assert all(y == 236 for x, y in row0)
    assert all(y == 311 for x, y in row1)
    assert all(y == 387 for x, y in row2)
    assert all(y == 462 for x, y in row3)
    
    # Within each row, x coordinates strictly increase
    for r in (row0, row1, row2, row3):
        xs = [x for x, y in r]
        assert xs == sorted(xs)
        assert len(set(xs)) == len(xs)


def test_resolve_attendance_candidate():
    runner_cls = hd_mod.HoatDongRunner
    
    # All blank -> candidate is index 0 (Day 1)
    states = ["blank"] * 30
    assert runner_cls.next_attendance_index(states) == 0
    
    # Days 1..10 ticked -> candidate is index 10 (Day 11)
    states = ["tick"] * 10 + ["blank"] * 20
    assert runner_cls.next_attendance_index(states) == 10
    
    # Days 1..29 ticked -> candidate is index 29 (Day 30)
    states = ["tick"] * 29 + ["blank"]
    assert runner_cls.next_attendance_index(states) == 29
    
    # All 30 ticked -> candidate is None
    states = ["tick"] * 30
    assert runner_cls.next_attendance_index(states) is None


def test_attendance_writer_roundtrip(tmp_path):
    csv_file = tmp_path / "accounts.csv"
    initial_rows = [
        {"id": "acc_001", "username": "u1", "password": "p1", "Diem-Danh": "5"},
        {"id": "acc_002", "username": "u2", "password": "p2", "Diem-Danh": "10"},
    ]
    write_accounts(csv_file, initial_rows)
    
    assert read_attendance_day(csv_file, "acc_001") == 5
    assert read_attendance_day(csv_file, "acc_002") == 10
    
    # Update acc_001 to day 6
    write_attendance_day(csv_file, "acc_001", 6)
    assert read_attendance_day(csv_file, "acc_001") == 6
    assert read_attendance_day(csv_file, "acc_002") == 10


def test_claim_attendance_milestones_skips_when_days_insufficient():
    class DummyConfig:
        wait_seconds = 0.0
        reward_marker = Path("dummy.png")
        attendance_milestone_rois = [(10, 10, 20, 20), (30, 30, 40, 40), (50, 50, 60, 60)]
        attendance_milestone_claimable = Path("dummy_claimable.png")
        attendance_milestone_locked = Path("dummy_locked.png")
        attendance_milestone_claimed = Path("dummy_claimed.png")

    class DummyInput:
        def __init__(self):
            self.taps = []
        def tap(self, x, y):
            self.taps.append((x, y))

    runner = hd_mod.HoatDongRunner(
        screen_provider=lambda: np.zeros((100, 100, 3), dtype=np.uint8),
        adb_input=DummyInput(),
        vision=None,
        config=DummyConfig(),
    )
    runner._drain_rewards = lambda *args: None
    runner._reward = lambda *args: False
    runner._milestone_state = lambda scr, roi: ("claimable", type("Match", (), {"confidence": 0.99, "x": 0, "y": 0, "width": 5, "height": 5})(), 0.1)

    # When current_days is 5, it should skip 10, 20, 30 days milestones
    runner._claim_attendance_milestones(None, current_days=5)
    assert len(runner.input.taps) == 0

    # When current_days is 15, it should only tap day 10
    runner._claim_attendance_milestones(None, current_days=15)
    assert len(runner.input.taps) == 1

