from __future__ import annotations

import shlex
import logging

from app.adb.client import AdbClient
from app.adb.device import AdbDevice

LOGGER = logging.getLogger("dc3q")


class AdbInput:
    """Small, explicit ADB input API. It performs one command at a time."""
    def __init__(self, client: AdbClient, device: AdbDevice):
        self.client, self.device = client, device

    def shell(self, *args: str, timeout: float | None = None) -> str:
        return self.client.shell(self.device.serial, *args, timeout=timeout)

    def tap(self, x: int, y: int) -> str:
        LOGGER.info("ACTION | TAP | device=%s | x=%d | y=%d", self.device.serial, int(x), int(y))
        return self.shell("input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        LOGGER.info(
            "ACTION | SWIPE | device=%s | từ=(%d,%d) | đến=(%d,%d) | thời_gian_ms=%d",
            self.device.serial, int(x1), int(y1), int(x2), int(y2), int(duration_ms),
        )
        return self.shell("input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)))

    def keyevent(self, key: int | str) -> str:
        LOGGER.info("ACTION | KEYEVENT | device=%s | key=%s", self.device.serial, key)
        return self.shell("input", "keyevent", str(key))

    def text(self, value: str) -> str:
        LOGGER.info("ACTION | TEXT | device=%s | giá_trị=[ĐÃ ẨN] | ký_tự=%d", self.device.serial, len(value))
        # Android input text uses shell escaping; keep spaces and common punctuation safe.
        escaped = value.replace("%s", "%%s").replace(" ", "%s")
        return self.shell("input", "text", escaped)

    def ui_xml(self) -> str:
        LOGGER.info("ACTION | UI_XML | device=%s | bắt đầu", self.device.serial)
        remote = "/sdcard/dc3q_window.xml"
        self.shell("rm", "-f", remote)
        self.shell("uiautomator", "dump", remote, timeout=15)
        xml = self.shell("cat", remote)
        self.shell("rm", "-f", remote)
        if not xml.lstrip().startswith("<?xml"):
            LOGGER.info("ACTION | UI_XML | device=%s | kết_quả=KHÔNG HỢP LỆ", self.device.serial)
            raise RuntimeError("UI dump không hợp lệ")
        LOGGER.info("ACTION | UI_XML | device=%s | kết_quả=HỢP LỆ | ký_tự=%d", self.device.serial, len(xml))
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
        LOGGER.info("ACTION | LAUNCH_APP | device=%s | component=%s", self.device.serial, component)
        return self.shell("am", "start", "-n", component)

    def force_stop_app(self, package: str) -> str:
        LOGGER.info("ACTION | FORCE_STOP | device=%s | package=%s", self.device.serial, package)
        return self.shell("am", "force-stop", package)
