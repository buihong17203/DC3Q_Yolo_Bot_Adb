from __future__ import annotations

import csv
from pathlib import Path

from app.accounts import AccountManager, AccountRepository
from app.automation import AutomationRunResult
from app.devices import DeviceWorker, WorkerState


class FakeDevice:
    serial = "emulator-test"

    def set_action_guard(self, guard) -> None:
        self.guard = guard

    def is_online(self) -> bool:
        return True

    def wait_until_online(self, timeout: float = 1.0) -> bool:
        return True


class FakeEngine:
    def __init__(self) -> None:
        self.stopped = False
        self.usernames: list[str] = []

    def request_stop(self) -> None:
        self.stopped = True

    def run(self, scenario, *, account=None, variables=None) -> AutomationRunResult:
        assert account is not None
        self.usernames.append(account.username)
        return AutomationRunResult(True, "fake", 0.01, 1)


class FailingEngine(FakeEngine):
    def run(self, scenario, *, account=None, variables=None) -> AutomationRunResult:
        assert account is not None
        self.usernames.append(account.username)
        return AutomationRunResult(False, "fake", 0.01, 0, error="login failed")


def _accounts(path: Path) -> AccountManager:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["username", "password"])
        writer.writeheader()
        writer.writerow({"username": "a", "password": "1"})
        writer.writerow({"username": "b", "password": "2"})
    return AccountManager(AccountRepository(path), persist_status=False)


def test_worker_processes_all_accounts(tmp_path: Path) -> None:
    manager = _accounts(tmp_path / "accounts.csv")
    fake_engine = FakeEngine()
    worker = DeviceWorker(
        FakeDevice(),
        {"name": "fake", "steps": []},
        account_manager=manager,
        vision_factory=lambda device: object(),
        engine_factory=lambda device, vision: fake_engine,
    )

    worker.run()
    snapshot = worker.snapshot()

    assert snapshot.state == WorkerState.STOPPED
    assert snapshot.completed_accounts == 2
    assert fake_engine.usernames == ["a", "b"]
    assert manager.stats.done == 2


def test_worker_stops_batch_after_first_unproven_account(tmp_path: Path) -> None:
    manager = _accounts(tmp_path / "accounts.csv")
    fake_engine = FailingEngine()
    worker = DeviceWorker(
        FakeDevice(),
        {"name": "fake", "steps": []},
        account_manager=manager,
        vision_factory=lambda device: object(),
        engine_factory=lambda device, vision: fake_engine,
    )

    worker.run()

    assert fake_engine.usernames == ["a"]
    assert manager.stats.ready == 2
    assert worker.snapshot().failed_runs == 1


def test_worker_stops_after_exception(tmp_path: Path) -> None:
    class RaisingEngine(FakeEngine):
        def run(self, scenario, *, account=None, variables=None) -> AutomationRunResult:
            assert account is not None
            self.usernames.append(account.username)
            raise RuntimeError("unknown screen")

    manager = _accounts(tmp_path / "accounts.csv")
    fake_engine = RaisingEngine()
    worker = DeviceWorker(
        FakeDevice(),
        {"name": "fake", "steps": []},
        account_manager=manager,
        vision_factory=lambda device: object(),
        engine_factory=lambda device, vision: fake_engine,
    )

    worker.run()

    assert fake_engine.usernames == ["a"]
    assert manager.stats.ready == 2
    assert worker.snapshot().failed_runs == 1


def test_worker_action_guard_detects_game_day_change(tmp_path: Path) -> None:
    from app.core.game_day import GameDayRollover

    manager = _accounts(tmp_path / "accounts.csv")
    device = FakeDevice()
    worker = DeviceWorker(
        device,
        {"name": "fake", "steps": []},
        account_manager=manager,
        vision_factory=lambda value: object(),
        engine_factory=lambda value, vision: FakeEngine(),
    )
    worker._active_game_day = "old-day"

    try:
        device.guard()
    except GameDayRollover:
        pass
    else:
        raise AssertionError("physical-action guard must stop at game-day rollover")
