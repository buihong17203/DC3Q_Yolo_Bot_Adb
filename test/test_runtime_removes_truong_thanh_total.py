import csv
from pathlib import Path

from app.accounts.runtime import AccountRuntime


def test_runtime_migrates_away_useless_truong_thanh_total(tmp_path: Path):
    accounts = tmp_path / "data" / "accounts"
    accounts.mkdir(parents=True)
    (accounts / "accounts.csv").write_text("id\nacc_001\n", encoding="utf-8")
    old = accounts / "account_runtime.csv"
    old.write_text(
        "id,Truong_Thanh,TT_A1_Bao_Vat,game_day,reset_hour\n"
        "acc_001,DONE,ERROR,2026-10-04,23\n",
        encoding="utf-8",
    )

    AccountRuntime(tmp_path)

    with old.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        row = next(reader)
        assert "Truong_Thanh" not in reader.fieldnames
    assert "Truong_Thanh" not in AccountRuntime.FIELDS
    assert row["TT_A1_Bao_Vat"] == "ERROR"