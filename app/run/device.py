from __future__ import annotations
from app.adb import AdbClient, AdbDevice, AdbInput, AdbScreenshot, AdbApp
from app.devices.worker import DeviceWorker

class DeviceRuntime:
    def __init__(self, adb: AdbClient, device: AdbDevice):
        self.device=device; self.worker=DeviceWorker(adb, device)
        self.input=AdbInput(adb,device); self.screenshot=AdbScreenshot(adb,device); self.app=AdbApp(adb,device)
