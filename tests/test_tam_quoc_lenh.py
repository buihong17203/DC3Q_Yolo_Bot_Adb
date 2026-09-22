from __future__ import annotations

import json
from pathlib import Path

from app.accounts import AccountRepository
from app.core.game_day import DailyRuntimeStore


def _accounts(path: Path):
    path.write_text(json.dumps({"accounts": [
        {"id": "acc_001", "username": "u1", "password": "p1"},
        {"id": "acc_002", "username": "u2", "password": "p2"},
    ]}), encoding="utf-8")
    return AccountRepository(path).load()


def test_runtime_has_tam_quoc_lenh_state_for_every_account(tmp_path: Path) -> None:
    accounts = _accounts(tmp_path / "accounts.json")
    store = DailyRuntimeStore(tmp_path / "runtime.json", tmp_path / "history")

    store.initialize(accounts)

    raw = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    states = [row["tasks"]["tam_quoc_lenh"] for row in raw["accounts"]]
    assert states == [
        {"status": "NOT_STARTED", "que_boi": "NOT_STARTED", "diem_binh": "NOT_STARTED", "error": None},
        {"status": "NOT_STARTED", "que_boi": "NOT_STARTED", "diem_binh": "NOT_STARTED", "error": None},
    ]


def test_runtime_updates_tam_quoc_lenh_progress_per_account(tmp_path: Path) -> None:
    accounts = _accounts(tmp_path / "accounts.json")
    store = DailyRuntimeStore(tmp_path / "runtime.json", tmp_path / "history")
    store.initialize(accounts)

    store.update_task("acc_001", "tam_quoc_lenh", {
        "status": "PARTIAL",
        "que_boi": "DONE",
        "diem_binh": "NOT_STARTED",
        "error": None,
    })

    raw = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    first, second = raw["accounts"]
    assert first["tasks"]["tam_quoc_lenh"]["status"] == "PARTIAL"
    assert first["tasks"]["tam_quoc_lenh"]["que_boi"] == "DONE"
    assert second["tasks"]["tam_quoc_lenh"]["status"] == "NOT_STARTED"


def test_game_day_reset_clears_tam_quoc_lenh_state(tmp_path: Path) -> None:
    accounts = _accounts(tmp_path / "accounts.json")
    store = DailyRuntimeStore(tmp_path / "runtime.json", tmp_path / "history")
    store.initialize(accounts)
    store.update_task("acc_001", "tam_quoc_lenh", {
        "status": "DONE", "que_boi": "DONE", "diem_binh": "DONE",
        "error": None,
    })

    raw = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    raw["game_day"] = "2000-01-01"
    (tmp_path / "runtime.json").write_text(json.dumps(raw), encoding="utf-8")
    store.rollover(accounts)

    current = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    task = current["accounts"][0]["tasks"]["tam_quoc_lenh"]
    assert task["status"] == "NOT_STARTED"
    assert "rewards" not in task


def test_manager_scenario_orders_tam_quoc_lenh_between_login_logout() -> None:
    import yaml

    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "scripts/multi_account_manager.yaml").read_text(encoding="utf-8"))
    calls = [step.get("run_scenario") for step in data["steps"] if "run_scenario" in step]
    assert calls == ["tasks/tam_quoc_lenh.yaml", "tasks/phuc_loi.yaml", "auth/logout.yaml"]
