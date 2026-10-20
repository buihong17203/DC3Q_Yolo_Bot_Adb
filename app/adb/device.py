from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdbDevice:
    serial: str
    state: str
    model: str | None = None
    product: str | None = None
    transport_id: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.state == "device"

    @property
    def is_emulator(self) -> bool:
        s = self.serial.lower()
        if (
            s.startswith("emulator-")
            or s.startswith("127.0.0.1:")
            or s.startswith("localhost:")
        ):
            return True
        keywords = (
            "vbox",
            "goldfish",
            "ranchu",
            "nox",
            "mumu",
            "ldplayer",
            "bluestacks",
            "genymotion",
            "android_x86",
            "google_sdk",
            "sdk_gphone",
        )
        for val in (self.model, self.product):
            if val:
                v = val.lower()
                if any(k in v for k in keywords):
                    return True
        return False

    @property
    def display_name(self) -> str:
        kind = "[EMULATOR]" if self.is_emulator else "[PHYSICAL]"
        if self.model:
            return f"{self.serial} ({self.model}) {kind}"
        return f"{self.serial} {kind}"
