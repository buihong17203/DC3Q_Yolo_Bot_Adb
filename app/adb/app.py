from __future__ import annotations
from app.adb.client import AdbClient
from app.adb.device import AdbDevice

class AdbApp:
    def __init__(self, client: AdbClient, device: AdbDevice):
        self.client, self.device = client, device
    def launch(self, package: str, activity: str | None = None) -> str:
        component = package if not activity else f"{package}/{activity}"
        return self.client.shell(self.device, "am", "start", "-n", component)
    def stop(self, package: str) -> str:
        return self.client.shell(self.device, "am", "force-stop", package)
    def clear(self, package: str) -> str:
        return self.client.shell(self.device, "pm", "clear", package)
