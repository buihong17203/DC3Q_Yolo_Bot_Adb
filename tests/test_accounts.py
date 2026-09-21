from __future__ import annotations

import csv
from pathlib import Path

from app.accounts import AccountManager, AccountRepository, AccountStatus


def _make_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "username", "password", "status", "server"])
        writer.writeheader()
        writer.writerow({"id": "1", "username": "user_a", "password": "pass_a", "status": "READY", "server": "s1"})
        writer.writerow({"id": "2", "username": "user_b", "password": "pass_b", "status": "READY", "server": "s2"})


def test_repository_load_csv(tmp_path: Path) -> None:
    source = tmp_path / "accounts.csv"
    _make_csv(source)
    accounts = AccountRepository(source).load()

    assert len(accounts) == 2
    assert accounts[0].username == "user_a"
    assert accounts[0].password == "pass_a"
    assert accounts[0].metadata["server"] == "s1"


def test_account_manager_exclusive_claim_and_done(tmp_path: Path) -> None:
    source = tmp_path / "accounts.csv"
    _make_csv(source)
    manager = AccountManager(AccountRepository(source), persist_status=False)

    first = manager.claim_next("emulator-5554")
    second = manager.claim_next("emulator-5556")

    assert first is not None and second is not None
    assert first.id != second.id
    assert manager.claim_next("emulator-5558") is None

    manager.mark_done(first, worker_id="emulator-5554")
    assert first.status == AccountStatus.DONE
    assert manager.stats.done == 1


def test_account_retry_then_failed(tmp_path: Path) -> None:
    source = tmp_path / "accounts.csv"
    _make_csv(source)
    manager = AccountManager(
        AccountRepository(source),
        persist_status=False,
        retry_failed=True,
        max_attempts=2,
    )

    account = manager.claim_next("device-1")
    assert account is not None
    manager.mark_failed(account, "bad login", worker_id="device-1")
    assert account.status == AccountStatus.READY

    account2 = manager.claim_next("device-1")
    assert account2 is account
    manager.mark_failed(account2, "bad login again", worker_id="device-1")
    assert account.status == AccountStatus.FAILED
    assert account.attempts == 2
