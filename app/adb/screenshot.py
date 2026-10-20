from __future__ import annotations

import logging
from pathlib import Path
import cv2
import numpy as np

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

    def capture_cv2(self) -> np.ndarray:
        """Capture screenshot via ADB and decode directly in RAM using cv2.imdecode."""
        data = self.png_bytes()
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("ADB screencap không decode được bằng cv2.imdecode")
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.png_bytes())
        LOGGER.info("SCREENSHOT | device=%s | lưu=%s", self.device.serial, target.resolve())
        return target
