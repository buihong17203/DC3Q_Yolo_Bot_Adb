from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Any

from app.adb import AdbClient, AdbDevice


@dataclass
class WorkerResult:
    serial: str
    success: bool
    value: Any = None
    error: str | None = None


class DeviceWorker:
    """Per-device execution primitive. No automatic workflow is attached."""
    def __init__(self, adb: AdbClient, device: AdbDevice):
        self.adb = adb
        self.device = device
        self.stop_event = threading.Event()

    @property
    def serial(self) -> str:
        return self.device.serial

    def stop(self) -> None:
        self.stop_event.set()

    def run_once(self, fn: Callable[[AdbDevice], Any]) -> WorkerResult:
        if self.stop_event.is_set():
            return WorkerResult(self.serial, False, error="worker stopped")
        try:
            return WorkerResult(self.serial, True, value=fn(self.device))
        except Exception as exc:
            return WorkerResult(self.serial, False, error=str(exc))


# Compatibility alias for callers that prefer the shorter name.
Worker = DeviceWorker
