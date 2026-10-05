import csv
from pathlib import Path

from app.accounts.runtime import AccountRuntime


def seed(root: Path):
    accounts = root / "data/accounts/accounts.csv"
    accounts.parent.mkdir(parents=True)
    accounts.write_text("id\nacc_001\n", encoding="utf-8")


def test_runtime_migrates_error_message_column_to_dated_text(tmp_path: Path):
    seed(tmp_path)
    runtime = tmp_path / "data/accounts/account_runtime.csv"
    runtime.write_text(
        "id,status,error_message,last_run,game_day,reset_hour\n"
        "acc_001,ERROR,lỗi cũ,2026-10-04T20:22:54+07:00,2026-10-03,23\n",
        encoding="utf-8",
    )

    AccountRuntime(tmp_path)

    with runtime.open(encoding="utf-8-sig", newline="") as handle:
        assert "error_message" not in csv.DictReader(handle).fieldnames
    journal = tmp_path / "data/accounts/error_message_2026-10-04.txt"
    assert "acc_001" in journal.read_text(encoding="utf-8")
    assert "lỗi cũ" in journal.read_text(encoding="utf-8")


def test_new_task_error_appends_text_without_csv_error_column(tmp_path: Path):
    seed(tmp_path)
    runtime = AccountRuntime(tmp_path)

    runtime.mark_task_error("acc_001", "Quan_Doan", "không mở được")

    with runtime.runtime_file.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
        assert "error_message" not in row
        assert row["Quan_Doan"] == "ERROR"
    journals = list((tmp_path / "data/accounts").glob("error_message_*.txt"))
    assert len(journals) == 1
    text = journals[0].read_text(encoding="utf-8")
    assert "acc_001" in text
    assert "Quan_Doan" in text
    assert "không mở được" in text
