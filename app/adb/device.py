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
    def display_name(self) -> str:
        if self.model:
            return f"{self.serial} ({self.model})"
        return self.serial
