from __future__ import annotations

import re
from dataclasses import asdict
from typing import Iterable

from .client import AdbClient
from .device import AdbDevice


class AdbResolver:
    """Discovers devices already visible to the local ADB server."""

    _KEY_VALUE_RE = re.compile(r"(?P<key>[A-Za-z0-9_.-]+):(?P<value>\S+)")

    def __init__(self, client: AdbClient) -> None:
        self.client = client

    def ensure_server(self) -> None:
        self.client.start_server()

    def list_devices(self) -> list[AdbDevice]:
        raw = self.client.devices_raw()
        return list(self.parse_devices(raw))

    @classmethod
    def parse_devices(cls, raw: str) -> Iterable[AdbDevice]:
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices attached"):
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            serial, state = parts[0], parts[1]
            props: dict[str, str] = {}

            for token in parts[2:]:
                match = cls._KEY_VALUE_RE.fullmatch(token)
                if match:
                    props[match.group("key")] = match.group("value")

            yield AdbDevice(
                serial=serial,
                state=state,
                model=props.get("model"),
                product=props.get("product"),
                transport_id=props.get("transport_id"),
            )

    def find_ready(self) -> list[AdbDevice]:
        return [device for device in self.list_devices() if device.is_ready]

    @staticmethod
    def to_dict(device: AdbDevice) -> dict:
        return asdict(device)
