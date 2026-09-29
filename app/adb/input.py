from __future__ import annotations

import shlex

from app.adb.client import AdbClient
from app.adb.device import AdbDevice


class AdbInput:
    """Small, explicit ADB input API. It performs one command at a time."""
    def __init__(self, client: AdbClient, device: AdbDevice):
        self.client, self.device = client, device

    def shell(self, *args: str, timeout: float | None = None) -> str:
        return self.client.shell(self.device.serial, *args, timeout=timeout)

    def tap(self, x: int, y: int) -> str:
        return self.shell("input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        return self.shell("input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)))

    def keyevent(self, key: int | str) -> str:
        return self.shell("input", "keyevent", str(key))

    def text(self, value: str) -> str:
        # Android input text uses shell escaping; keep spaces and common punctuation safe.
        escaped = value.replace("%s", "%%s").replace(" ", "%s")
        return self.shell("input", "text", escaped)

    def ui_xml(self) -> str:
        remote = "/sdcard/dc3q_window.xml"
        self.shell("rm", "-f", remote)
        self.shell("uiautomator", "dump", remote, timeout=15)
        xml = self.shell("cat", remote)
        self.shell("rm", "-f", remote)
        if not xml.lstrip().startswith("<?xml"):
            raise RuntimeError("UI dump không hợp lệ")
        return xml

    def clear_focused_text(self) -> None:
        # SDK login fields can retain the previous account after manual logout.
        self.shell("input", "keyevent", "KEYCODE_MOVE_END")
        for _ in range(8):
            self.shell("input", "keyevent", *(["KEYCODE_DEL"] * 16))

    def back(self) -> str: return self.keyevent("KEYCODE_BACK")
    def home(self) -> str: return self.keyevent("KEYCODE_HOME")
    def enter(self) -> str: return self.keyevent("KEYCODE_ENTER")
    def recent(self) -> str: return self.keyevent("KEYCODE_APP_SWITCH")

    def launch_app(self, package: str, activity: str | None = None) -> str:
        component = package if not activity else f"{package}/{activity}"
        return self.shell("am", "start", "-n", component)

    def force_stop_app(self, package: str) -> str:
        return self.shell("am", "force-stop", package)
