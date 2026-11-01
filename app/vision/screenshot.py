from __future__ import annotations
from pathlib import Path
from app.adb import AdbClient, AdbDevice, AdbScreenshot

def capture_png(client: AdbClient, device: AdbDevice) -> bytes:
    return AdbScreenshot(client, device).png_bytes()

def capture_to(client: AdbClient, device: AdbDevice, path: str | Path) -> Path:
    return AdbScreenshot(client, device).save(path)
