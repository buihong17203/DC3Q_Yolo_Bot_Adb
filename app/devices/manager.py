from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Mapping

from app.accounts import AccountManager
from app.adb import ADBDeviceManager
from app.core.config import settings
from app.core.logger import get_logger

from .worker import DeviceWorker, WorkerSnapshot

logger = get_logger(__name__)


class DeviceManager:
    """High-level multi-emulator manager built on top of ADBDeviceManager."""

    def __init__(
        self,
        scenario: Mapping[str, Any] | str | Path,
        *,
        adb_manager: ADBDeviceManager | None = None,
        account_manager: AccountManager | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.scenario = scenario
        self.adb_manager = adb_manager or ADBDeviceManager()
        self.account_manager = account_manager
        self.max_workers = max(1, int(max_workers or settings.devices.max_workers))
        self._workers: dict[str, DeviceWorker] = {}
        self._lock = threading.RLock()

    def discover(self) -> list[DeviceWorker]:
        devices = self.adb_manager.refresh(online_only=True)
        allowed = devices[: self.max_workers]
        allowed_serials = {device.serial for device in allowed}

        with self._lock:
            for device in allowed:
                if device.serial not in self._workers:
                    self._workers[device.serial] = DeviceWorker(
                        device,
                        self.scenario,
                        account_manager=self.account_manager,
                        # Account batches are daily services: after finishing today's
                        # queue, wait for the 23:00 rollover instead of exiting.
                        stop_when_no_accounts=self.account_manager is None,
                    )
                    logger.info("Tạo worker cho thiết bị %s", device.serial)

            # Workers for disconnected devices are stopped but kept for final snapshot.
            for serial, worker in self._workers.items():
                if serial not in allowed_serials and worker.alive:
                    logger.warning("[%s] Device không còn online; yêu cầu dừng worker", serial)
                    worker.stop()

            return [self._workers[device.serial] for device in allowed]

    def workers(self) -> list[DeviceWorker]:
        with self._lock:
            return list(self._workers.values())

    def start_all(self) -> int:
        workers = self.discover()
        for worker in workers:
            worker.start()
        return len(workers)

    def stop_all(self) -> None:
        for worker in self.workers():
            if worker.alive:
                worker.stop()

    def join_all(self, timeout: float | None = None) -> None:
        for worker in self.workers():
            worker.join(timeout=timeout)

    def run_until_complete(self) -> list[WorkerSnapshot]:
        count = self.start_all()
        if count == 0:
            return []
        try:
            self.join_all()
        except KeyboardInterrupt:
            logger.warning("Nhận Ctrl+C, đang dừng tất cả worker")
            self.stop_all()
            self.join_all(timeout=5.0)
        return self.snapshots()

    def snapshots(self) -> list[WorkerSnapshot]:
        return [worker.snapshot() for worker in self.workers()]

    @property
    def active_count(self) -> int:
        return sum(1 for worker in self.workers() if worker.alive)
