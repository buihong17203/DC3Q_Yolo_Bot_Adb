from __future__ import annotations

import logging
from pathlib import Path

from app.adb.client import AdbClient
from app.adb.device import AdbDevice

LOGGER = logging.getLogger("dc3q")


class AdbScreenshot:
    def __init__(self, client: AdbClient, device: AdbDevice):
        self.client, self.device = client, device

    def png_bytes(self) -> bytes:
        LOGGER.info("SCREENSHOT | device=%s | bắt đầu chụp ảnh mới", self.device.serial)
        result = self.client.run(["-s", self.device.serial, "exec-out", "screencap", "-p"], binary=True)
        LOGGER.info("SCREENSHOT | device=%s | hoàn tất | bytes=%d", self.device.serial, len(result.stdout))
        return result.stdout

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.png_bytes())
        LOGGER.info("SCREENSHOT | device=%s | lưu=%s", self.device.serial, target.resolve())
        return target
