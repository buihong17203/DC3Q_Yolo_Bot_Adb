from __future__ import annotations
from pathlib import Path
from app.adb import AdbClient, AdbDevice, AdbScreenshot

def capture_png(client: AdbClient, device: AdbDevice) -> bytes:
    return AdbScreenshot(client, device).png_bytes()

def capture_cv2(client: AdbClient, device: AdbDevice):
    return AdbScreenshot(client, device).capture_cv2()

def capture_frame(client: AdbClient, device: AdbDevice):
    return AdbScreenshot(client, device).capture_frame()

def capture_to(client: AdbClient, device: AdbDevice, path: str | Path) -> Path:
    return AdbScreenshot(client, device).save(path)
