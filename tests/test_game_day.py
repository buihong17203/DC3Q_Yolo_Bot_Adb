from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from app.accounts import AccountManager, AccountRepository, AccountStatus
from app.core.game_day import DailyRuntimeStore, GameDayClock
from app.core.logger import GameDayFileHandler


def _source(path: Path) -> AccountRepository:
    path.write_text(json.dumps({"accounts": [
        {"id": "acc_001", "username": "u1", "password": "p1", "status": "DONE"},
        {"id": "acc_002", "username": "u2", "password": "p2", "status": "READY"},
    ]}), encoding="utf-8")
    return AccountRepository(path)


def test_game_day_changes_at_23_local() -> None:
    clock = GameDayClock(reset_hour=23)
    assert clock.key(datetime(2026, 9, 21, 22, 59, 59)) == "2026-09-21"
    assert clock.key(datetime(2026, 9, 21, 23, 0, 0)) == "2026-09-22"


def test_runtime_archives_without_credentials_then_resets(tmp_path: Path) -> None:
    source = _source(tmp_path / "accounts.json")
    runtime = tmp_path / "account_runtime.json"
    archive = tmp_path / "archive"
    runtime.write_text(json.dumps({
        "game_day": "2026-09-20",
        "accounts": [{"id": "acc_001", "status": "DONE", "attempts": 1}],
        "events": [{"account_id": "acc_001", "type": "reward", "items": ["known_item"]}],
    }), encoding="utf-8")
    store = DailyRuntimeStore(runtime, archive, clock=GameDayClock(23))

    changed = store.rollover(source.load(), now=datetime(2026, 9, 21, 23, 0, 0))

    assert changed
    archived = json.loads((archive / "2026-09-20" / "account_runtime.json").read_text(encoding="utf-8"))
    assert "username" not in json.dumps(archived)
    assert "password" not in json.dumps(archived)
    current = json.loads(runtime.read_text(encoding="utf-8"))
    assert current["game_day"] == "2026-09-22"
    assert [item["status"] for item in current["accounts"]] == ["READY", "READY"]
    assert current["events"] == []


def test_account_manager_persists_status_only_to_runtime(tmp_path: Path) -> None:
    source_path = tmp_path / "accounts.json"
    source = _source(source_path)
    original = source_path.read_text(encoding="utf-8")
    store = DailyRuntimeStore(tmp_path / "account_runtime.json", tmp_path / "archive")
    manager = AccountManager(source, runtime_store=store)

    account = manager.claim_next("device")
    assert account is not None and account.id == "acc_002"
    manager.mark_done(account, worker_id="device")

    assert source_path.read_text(encoding="utf-8") == original
    saved = json.loads((tmp_path / "account_runtime.json").read_text(encoding="utf-8"))
    assert saved["accounts"][1]["status"] == AccountStatus.DONE.value
    assert "username" not in json.dumps(saved)
    assert "password" not in json.dumps(saved)


def test_game_day_log_uses_dated_filename(tmp_path: Path) -> None:
    handler = GameDayFileHandler(tmp_path, "dc3q.log", 23)
    handler.clock = type("Clock", (), {"key": lambda self: "2026-09-20"})()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None))
    handler.close()

    assert (tmp_path / "dc3q_2026-09-20.log").read_text(encoding="utf-8") == "hello\n"


def test_status_save_cannot_advance_day_before_archive(tmp_path: Path) -> None:
    accounts = _source(tmp_path / "accounts.json").load()
    runtime = tmp_path / "account_runtime.json"
    runtime.write_text(json.dumps({
        "game_day": "2026-09-21",
        "accounts": [],
        "events": [{"type": "reward", "items": ["item"]}],
    }), encoding="utf-8")
    store = DailyRuntimeStore(runtime, tmp_path / "archive", clock=GameDayClock(23))

    store.save(accounts)

    saved = json.loads(runtime.read_text(encoding="utf-8"))
    assert saved["game_day"] == "2026-09-21"
    assert saved["events"][0]["items"] == ["item"]
