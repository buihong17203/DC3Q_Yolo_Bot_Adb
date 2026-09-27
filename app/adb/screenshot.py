from __future__ import annotations

from pathlib import Path

from app.adb.client import AdbClient
from app.adb.device import AdbDevice


class AdbScreenshot:
    def __init__(self, client: AdbClient, device: AdbDevice):
        self.client, self.device = client, device

    def png_bytes(self) -> bytes:
        result = self.client.run(["-s", self.device.serial, "exec-out", "screencap", "-p"], binary=True)
        return result.stdout

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.png_bytes())
        return target
