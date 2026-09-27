from __future__ import annotations

from .client import AdbClient
from .device import AdbDevice


def get_android_properties(client: AdbClient, device: AdbDevice) -> dict[str, str]:
    """Read a small set of properties useful for identifying a device."""
    keys = {
        "ro.product.manufacturer": "manufacturer",
        "ro.product.model": "model",
        "ro.build.version.release": "android",
        "ro.build.version.sdk": "sdk",
    }

    result: dict[str, str] = {}
    for prop, name in keys.items():
        value = client.shell(device.serial, "getprop", prop)
        result[name] = value
    return result
