from __future__ import annotations

import threading
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from typing import (
    Callable,
    TypeVar,
)

from app.adb.client import (
    ADBClient,
    DeviceInfo,
)
from app.adb.device import ADBDevice
from app.core.logger import get_logger


logger = get_logger(__name__)


T = TypeVar("T")


class ADBDeviceManager:
    """
    Quản lý nhiều Android device / emulator.

    Một manager sử dụng chung một ADBClient.

    Sau này:
        devices/worker.py

    có thể lấy ADBDevice từ manager và tạo worker riêng
    cho từng giả lập.
    """

    def __init__(
        self,
        client: ADBClient | None = None,
    ) -> None:

        self.client = (
            client
            if client is not None
            else ADBClient()
        )

        self._devices: dict[
            str,
            ADBDevice,
        ] = {}

        self._device_infos: dict[
            str,
            DeviceInfo,
        ] = {}

        self._lock = threading.RLock()

    # ========================================================
    # REFRESH
    # ========================================================

    def refresh(
        self,
        online_only: bool = True,
    ) -> list[ADBDevice]:
        """
        Quét lại danh sách thiết bị ADB.

        online_only=True:
            chỉ trả device có state == "device"

        online_only=False:
            trả cả offline / unauthorized.
        """

        infos = self.client.devices()

        discovered_serials: set[str] = set()

        with self._lock:

            self._device_infos.clear()

            for info in infos:

                discovered_serials.add(
                    info.serial
                )

                self._device_infos[
                    info.serial
                ] = info

                if info.serial not in self._devices:

                    logger.info(
                        "Phát hiện thiết bị ADB: "
                        "%s | state=%s | model=%s",
                        info.serial,
                        info.state,
                        info.model or "unknown",
                    )

                    self._devices[
                        info.serial
                    ] = ADBDevice(
                        serial=info.serial,
                        client=self.client,
                    )

            # Xóa device không còn xuất hiện trong ADB.
            disappeared = (
                set(self._devices)
                - discovered_serials
            )

            for serial in disappeared:

                logger.info(
                    "Thiết bị ADB đã biến mất: %s",
                    serial,
                )

                self._devices.pop(
                    serial,
                    None,
                )

                self._device_infos.pop(
                    serial,
                    None,
                )

            if online_only:

                return [
                    self._devices[info.serial]
                    for info in infos
                    if info.is_online
                ]

            return [
                self._devices[info.serial]
                for info in infos
            ]

    # ========================================================
    # QUERY
    # ========================================================

    def get(
        self,
        serial: str,
        refresh: bool = False,
    ) -> ADBDevice | None:

        if refresh:
            self.refresh(
                online_only=False
            )

        with self._lock:
            return self._devices.get(
                serial
            )

    def get_info(
        self,
        serial: str,
    ) -> DeviceInfo | None:

        with self._lock:
            return self._device_infos.get(
                serial
            )

    def all_devices(
        self,
    ) -> list[ADBDevice]:

        with self._lock:
            return list(
                self._devices.values()
            )

    def online_devices(
        self,
    ) -> list[ADBDevice]:

        with self._lock:

            result: list[ADBDevice] = []

            for serial, device in self._devices.items():

                info = self._device_infos.get(
                    serial
                )

                if (
                    info is not None
                    and info.is_online
                ):
                    result.append(
                        device
                    )

            return result

    def serials(
        self,
        online_only: bool = True,
    ) -> list[str]:

        devices = (
            self.online_devices()
            if online_only
            else self.all_devices()
        )

        return [
            device.serial
            for device in devices
        ]

    @property
    def count(self) -> int:
        with self._lock:
            return len(
                self._devices
            )

    @property
    def online_count(self) -> int:
        return len(
            self.online_devices()
        )

    # ========================================================
    # WAIT
    # ========================================================

    def wait_for_any_device(
        self,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> ADBDevice | None:
        """
        Chờ đến khi có ít nhất một device online.
        """

        deadline = (
            time.monotonic()
            + timeout
        )

        while time.monotonic() < deadline:

            devices = self.refresh(
                online_only=True
            )

            if devices:
                return devices[0]

            time.sleep(
                poll_interval
            )

        return None

    # ========================================================
    # NETWORK ADB
    # ========================================================

    def connect(
        self,
        host: str,
        port: int = 5555,
    ) -> ADBDevice | None:

        logger.info(
            "ADB connect %s:%d",
            host,
            port,
        )

        self.client.connect(
            host=host,
            port=port,
        )

        serial = (
            f"{host}:{port}"
        )

        self.refresh(
            online_only=False
        )

        return self.get(
            serial
        )

    def disconnect(
        self,
        host: str,
        port: int = 5555,
    ) -> None:

        logger.info(
            "ADB disconnect %s:%d",
            host,
            port,
        )

        self.client.disconnect(
            host=host,
            port=port,
        )

        self.refresh(
            online_only=False
        )

    # ========================================================
    # PARALLEL EXECUTION
    # ========================================================

    def execute_parallel(
        self,
        operation: Callable[
            [ADBDevice],
            T,
        ],
        devices: list[ADBDevice] | None = None,
        max_workers: int | None = None,
    ) -> dict[str, T | Exception]:
        """
        Thực hiện cùng một operation trên nhiều thiết bị song song.

        Ví dụ:

            results = manager.execute_parallel(
                lambda device: device.get_screen_size()
            )

        Kết quả:

            {
                "emulator-5554": (1280, 720),
                "emulator-5556": (1280, 720)
            }

        Nếu một thiết bị lỗi:
            value sẽ là Exception.

        Exception của một device không làm chết các device khác.
        """

        target_devices = (
            devices
            if devices is not None
            else self.online_devices()
        )

        if not target_devices:
            return {}

        if max_workers is None:
            max_workers = len(
                target_devices
            )

        # Không cho 0 worker.
        max_workers = max(
            1,
            max_workers,
        )

        results: dict[
            str,
            T | Exception,
        ] = {}

        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="adb-device",
        ) as executor:

            future_map = {
                executor.submit(
                    operation,
                    device,
                ): device
                for device in target_devices
            }

            for future in as_completed(
                future_map
            ):

                device = future_map[
                    future
                ]

                try:

                    results[
                        device.serial
                    ] = future.result()

                except Exception as exc:

                    logger.exception(
                        "[%s] Parallel ADB operation failed",
                        device.serial,
                    )

                    results[
                        device.serial
                    ] = exc

        return results