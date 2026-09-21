from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Mapping

from app.accounts import AccountManager
from app.adb import ADBDeviceManager
from app.core.config import settings
from app.core.logger import get_logger
from app.core.shutdown import terminate_child_processes

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
        self._interrupted = False

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
        workers = self.workers()
        if timeout is None:
            for worker in workers:
                worker.join()
            return

        # One shared timeout budget; do not wait timeout * number_of_workers.
        deadline = time.monotonic() + max(0.0, float(timeout))
        for worker in workers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)

    def shutdown(self, grace_timeout: float = 5.0) -> None:
        """Stop every worker and every subprocess created by this project."""
        self.stop_all()

        # A worker can be blocked inside subprocess.run(adb ...). Killing only
        # descendants of this Python PID unblocks it without killing the global
        # ADB server used by Android Studio/other tools.
        terminate_child_processes(timeout=1.0)
        self.join_all(timeout=grace_timeout)

        alive = [worker.serial for worker in self.workers() if worker.alive]
        if alive:
            logger.warning(
                "Worker chưa thoát sau %.1fs: %s; tiến trình chính sẽ kết thúc và daemon worker sẽ bị hủy",
                grace_timeout,
                ", ".join(alive),
            )

        if self.account_manager is not None:
            worker_ids = [worker.serial for worker in self.workers()]
            released = self.account_manager.release_all_in_use(worker_ids)
            if released:
                logger.info("Đã trả %d account IN_USE về READY khi shutdown", released)

        # Final sweep in case a child process appeared while workers were unwinding.
        terminate_child_processes(timeout=0.5)

    def run_until_complete(self) -> list[WorkerSnapshot]:
        count = self.start_all()
        if count == 0:
            return []
        try:
            self.join_all()
        except KeyboardInterrupt:
            self._interrupted = True
            logger.warning("Nhận Ctrl+C: dừng toàn bộ worker và child process của project")
            self.shutdown()
        return self.snapshots()

    def snapshots(self) -> list[WorkerSnapshot]:
        return [worker.snapshot() for worker in self.workers()]

    @property
    def active_count(self) -> int:
        return sum(1 for worker in self.workers() if worker.alive)

    @property
    def interrupted(self) -> bool:
        return self._interrupted
