from __future__ import annotations

import logging
from pathlib import Path
import socket
import struct
from typing import TYPE_CHECKING
import cv2
import numpy as np

from app.adb.client import AdbClient
from app.adb.device import AdbDevice

if TYPE_CHECKING:
    from app.vision.image import ImageFrame

LOGGER = logging.getLogger("dc3q")


class AdbScreenshot:
    def __init__(self, client: AdbClient, device: AdbDevice):
        self.client, self.device = client, device

    def _capture_socket_raw(self) -> np.ndarray | None:
        """Fast path: connect directly to ADB daemon socket (127.0.0.1:5037) for raw screencap.
        Eliminates subprocess creation and Android PNG software compression."""
        try:
            s = socket.create_connection(("127.0.0.1", 5037), timeout=3.0)
            s.settimeout(3.0)

            def cmd(c: str) -> None:
                s.sendall(f"{len(c):04X}{c}".encode("ascii"))
                res = s.recv(4)
                if res != b"OKAY":
                    raise RuntimeError(f"ADB socket error: {res!r}")

            cmd(f"host:transport:{self.device.serial}")
            cmd("exec:screencap")

            header = s.recv(16)
            if len(header) < 16:
                s.close()
                return None
            w, h, fmt, _ = struct.unpack("<IIII", header)
            total = w * h * 4
            buf = bytearray(total)
            view = memoryview(buf)
            pos = 0
            while pos < total:
                n = s.recv_into(view[pos:], min(total - pos, 131072))
                if not n:
                    break
                pos += n
            s.close()
            if pos < total:
                return None
            rgba = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))
            return np.ascontiguousarray(rgba[:, :, :3])
        except Exception as exc:
            LOGGER.debug("Socket raw screencap fallback sang ADB exec-out: %s", exc)
            return None

    def capture_cv2(self) -> np.ndarray:
        """Capture screenshot via fast direct socket raw buffer or fallback to ADB exec-out."""
        LOGGER.info("SCREENSHOT | device=%s | bắt đầu chụp ảnh mới", self.device.serial)
        raw = self._capture_socket_raw()
        if raw is not None:
            LOGGER.info("SCREENSHOT | device=%s | hoàn tất (socket raw) | shape=%s", self.device.serial, raw.shape)
            return raw

        data = self._png_bytes_subprocess()
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("ADB screencap không decode được bằng cv2.imdecode")
        LOGGER.info("SCREENSHOT | device=%s | hoàn tất (subprocess fallback) | bytes=%d", self.device.serial, len(data))
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def capture_frame(self) -> ImageFrame:
        """Capture directly to an ImageFrame without intermediate PNG roundtrips."""
        from app.vision.image import ImageFrame
        rgb = self.capture_cv2()
        h, w = rgb.shape[:2]
        return ImageFrame(data=rgb, width=w, height=h)

    def _png_bytes_subprocess(self) -> bytes:
        result = self.client.run(["-s", self.device.serial, "exec-out", "screencap", "-p"], binary=True, timeout=15.0)
        return result.stdout

    def png_bytes(self) -> bytes:
        LOGGER.info("SCREENSHOT | device=%s | bắt đầu chụp ảnh mới", self.device.serial)
        raw = self._capture_socket_raw()
        if raw is not None:
            bgr = cv2.cvtColor(raw, cv2.COLOR_RGB2BGR)
            encoded = cv2.imencode(".png", bgr)[1].tobytes()
            LOGGER.info("SCREENSHOT | device=%s | hoàn tất (host fast encoded) | bytes=%d", self.device.serial, len(encoded))
            return encoded

        data = self._png_bytes_subprocess()
        LOGGER.info("SCREENSHOT | device=%s | hoàn tất | bytes=%d", self.device.serial, len(data))
        return data

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.png_bytes())
        LOGGER.info("SCREENSHOT | device=%s | lưu=%s", self.device.serial, target.resolve())
        return target
