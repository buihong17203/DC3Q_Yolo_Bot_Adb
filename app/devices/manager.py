from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable

from app.adb import AdbClient, AdbDevice, AdbResolver


@dataclass
class DeviceSnapshot:
    devices: list[AdbDevice]

    @property
    def ready(self) -> list[AdbDevice]:
        return [d for d in self.devices if d.is_ready]


class DeviceManager:
    """Owns device discovery; deliberately does not start game workflows."""
    def __init__(self, adb: AdbClient, resolver: AdbResolver | None = None):
        self.adb = adb
        self.resolver = resolver or AdbResolver(adb)
        self._lock = threading.RLock()
        self._devices: dict[str, AdbDevice] = {}

    def refresh(self) -> DeviceSnapshot:
        found = self.resolver.list_devices()
        with self._lock:
            self._devices = {d.serial: d for d in found}
            return DeviceSnapshot(list(self._devices.values()))

    def all(self) -> list[AdbDevice]:
        with self._lock:
            return list(self._devices.values())

    def ready(self) -> list[AdbDevice]:
        return [d for d in self.all() if d.is_ready]

    def get(self, serial: str) -> AdbDevice | None:
        with self._lock:
            return self._devices.get(serial)

    def require(self, serial: str) -> AdbDevice:
        d = self.get(serial)
        if d is None:
            raise KeyError(f"Không tìm thấy ADB device: {serial}")
        return d
