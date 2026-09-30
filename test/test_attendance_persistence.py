import csv
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from app.accounts.writer import read_attendance_day, write_attendance_day

module = import_module("app.actions.dc3q.targets.02_hoat-dong")


def write_fixture(path: Path):
    path.write_text(
        "id,username,password,Diem-Danh\nacc_001,u1,p1,4\nacc_002,u2,p2,30\n",
        encoding="utf-8-sig",
    )


def test_attendance_day_updates_only_after_success(tmp_path):
    path = tmp_path / "accounts.csv"
    write_fixture(path)

    assert read_attendance_day(path, "acc_001") == 4
    write_attendance_day(path, "acc_001", 5)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0] == {"id": "acc_001", "username": "u1", "password": "p1", "Diem-Danh": "5"}
    assert rows[1]["Diem-Danh"] == "30"


def test_saved_day_selects_next_and_failed_click_keeps_old_value():
    saved = []
    runner = object.__new__(module.HoatDongRunner)
    runner.attendance_day = lambda: 4
    runner.save_attendance_day = saved.append

    assert runner._saved_attendance_candidate(object()) == 4
    assert saved == []


def test_day_30_stays_30_until_visual_reset():
    runner = object.__new__(module.HoatDongRunner)
    runner.attendance_day = lambda: 30
    runner._attendance_reset = lambda screen: False
    assert runner._saved_attendance_candidate(object()) is None

    runner._attendance_reset = lambda screen: True
    assert runner._saved_attendance_candidate(object()) == 0
