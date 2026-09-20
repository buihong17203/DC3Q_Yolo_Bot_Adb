from __future__ import annotations

import re
import time
from pathlib import Path

from app.adb.client import (
    ADBClient,
    DeviceInfo,
)
from app.core.logger import get_logger


logger = get_logger(__name__)


class ADBDevice:
    """
    Đại diện cho một thiết bị Android / emulator cụ thể.

    Một object ADBDevice luôn gắn với một serial ADB.

    Ví dụ:
        emulator-5554
        127.0.0.1:5555
        R58M123456
    """

    def __init__(
        self,
        serial: str,
        client: ADBClient | None = None,
    ) -> None:

        if not serial:
            raise ValueError(
                "serial không được để trống"
            )

        self.serial = serial

        self.client = (
            client
            if client is not None
            else ADBClient()
        )

    def __repr__(self) -> str:
        return (
            f"ADBDevice(serial={self.serial!r})"
        )

    # ========================================================
    # THÔNG TIN THIẾT BỊ
    # ========================================================

    def get_info(self) -> DeviceInfo | None:

        for device in self.client.devices():

            if device.serial == self.serial:
                return device

        return None

    def get_state(self) -> str | None:
        return self.client.get_state(
            self.serial
        )

    def is_online(self) -> bool:
        return self.get_state() == "device"

    def wait_until_online(
        self,
        timeout: float | None = None,
    ) -> None:

        self.client.wait_for_device(
            serial=self.serial,
            timeout=timeout,
        )

    # ========================================================
    # SHELL
    # ========================================================

    def shell(
        self,
        *args: object,
        timeout: float | None = None,
        check: bool = True,
    ) -> str:

        return self.client.shell(
            *args,
            serial=self.serial,
            timeout=timeout,
            check=check,
        )

    # ========================================================
    # TOUCH
    # ========================================================

    def tap(
        self,
        x: int,
        y: int,
    ) -> None:

        logger.debug(
            "[%s] tap (%d, %d)",
            self.serial,
            x,
            y,
        )

        self.shell(
            "input",
            "tap",
            int(x),
            int(y),
        )

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:

        logger.debug(
            "[%s] swipe (%d,%d) -> (%d,%d), %dms",
            self.serial,
            x1,
            y1,
            x2,
            y2,
            duration_ms,
        )

        self.shell(
            "input",
            "swipe",
            int(x1),
            int(y1),
            int(x2),
            int(y2),
            int(duration_ms),
        )

    def long_press(
        self,
        x: int,
        y: int,
        duration_ms: int = 1000,
    ) -> None:

        self.swipe(
            x,
            y,
            x,
            y,
            duration_ms,
        )

    # ========================================================
    # KEYBOARD
    # ========================================================

    def keyevent(
        self,
        keycode: int | str,
    ) -> None:

        self.shell(
            "input",
            "keyevent",
            keycode,
        )

    def press_back(self) -> None:
        self.keyevent(
            "KEYCODE_BACK"
        )

    def press_home(self) -> None:
        self.keyevent(
            "KEYCODE_HOME"
        )

    def press_enter(self) -> None:
        self.keyevent(
            "KEYCODE_ENTER"
        )

    def press_power(self) -> None:
        self.keyevent(
            "KEYCODE_POWER"
        )

    def wake_up(self) -> None:
        self.keyevent(
            "KEYCODE_WAKEUP"
        )

    # ========================================================
    # TEXT INPUT
    # ========================================================

    @staticmethod
    def _escape_input_text(
        text: str,
    ) -> str:
        """
        Chuẩn hóa chuỗi cho:

            adb shell input text

        Android dùng %s để biểu diễn dấu cách.

        Lưu ý:
        input text của Android không phải phương án tốt cho
        Unicode tiếng Việt. Sau này nếu cần nhập Unicode đầy
        đủ có thể bổ sung ADB Keyboard / IME riêng.
        """

        escaped = text.replace(
            "%",
            r"\%",
        )

        escaped = escaped.replace(
            " ",
            "%s",
        )

        special_chars = (
            "&",
            "<",
            ">",
            "|",
            ";",
            "(",
            ")",
            "$",
            "`",
            '"',
            "'",
        )

        for char in special_chars:
            escaped = escaped.replace(
                char,
                "\\" + char,
            )

        return escaped

    def input_text(
        self,
        text: str,
    ) -> None:

        encoded = self._escape_input_text(
            text
        )

        self.shell(
            "input",
            "text",
            encoded,
        )

    # ========================================================
    # SCREENSHOT
    # ========================================================

    def screenshot(self) -> bytes:
        """
        Chụp màn hình trực tiếp từ thiết bị.

        Trả về PNG dưới dạng bytes.

        Không sử dụng OpenCV tại đây để tránh coupling giữa
        tầng ADB và tầng Vision.
        """

        data = self.client.exec_out(
            "screencap",
            "-p",
            serial=self.serial,
        )

        if not data:
            raise RuntimeError(
                f"Không nhận được screenshot từ "
                f"{self.serial}"
            )

        return data

    def save_screenshot(
        self,
        path: str | Path,
    ) -> Path:

        output_path = Path(path)

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_bytes(
            self.screenshot()
        )

        return output_path

    # ========================================================
    # SCREEN SIZE
    # ========================================================

    def get_screen_size(
        self,
    ) -> tuple[int, int]:
        """
        Trả về:
            (width, height)
        """

        output = self.shell(
            "wm",
            "size",
        )

        # Nếu emulator có override resolution thì ưu tiên nó.
        override_match = re.search(
            r"Override size:\s*(\d+)x(\d+)",
            output,
        )

        if override_match:

            return (
                int(
                    override_match.group(1)
                ),
                int(
                    override_match.group(2)
                ),
            )

        physical_match = re.search(
            r"Physical size:\s*(\d+)x(\d+)",
            output,
        )

        if physical_match:

            return (
                int(
                    physical_match.group(1)
                ),
                int(
                    physical_match.group(2)
                ),
            )

        generic_match = re.search(
            r"(\d+)x(\d+)",
            output,
        )

        if generic_match:

            return (
                int(
                    generic_match.group(1)
                ),
                int(
                    generic_match.group(2)
                ),
            )

        raise RuntimeError(
            f"Không đọc được kích thước màn hình "
            f"của {self.serial}: {output!r}"
        )

    # ========================================================
    # APP / PACKAGE
    # ========================================================

    def is_package_installed(
        self,
        package_name: str,
    ) -> bool:

        output = self.shell(
            "pm",
            "path",
            package_name,
            check=False,
        )

        return output.startswith(
            "package:"
        )

    def start_app(
        self,
        package_name: str,
        activity: str | None = None,
    ) -> None:
        """
        Nếu có activity:
            am start -n package/activity

        Nếu không:
            dùng monkey để launch main activity.
        """

        if activity:

            component = (
                f"{package_name}/{activity}"
            )

            self.shell(
                "am",
                "start",
                "-n",
                component,
            )

            return

        self.shell(
            "monkey",
            "-p",
            package_name,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )

    def stop_app(
        self,
        package_name: str,
    ) -> None:

        self.shell(
            "am",
            "force-stop",
            package_name,
        )

    def clear_app_data(
        self,
        package_name: str,
    ) -> None:

        self.shell(
            "pm",
            "clear",
            package_name,
        )

    def install_apk(
        self,
        apk_path: str | Path,
        replace: bool = True,
        grant_permissions: bool = False,
    ) -> str:

        return self.client.install(
            apk_path=apk_path,
            serial=self.serial,
            replace=replace,
            grant_permissions=grant_permissions,
        )

    def uninstall_app(
        self,
        package_name: str,
        keep_data: bool = False,
    ) -> str:

        return self.client.uninstall(
            package_name=package_name,
            serial=self.serial,
            keep_data=keep_data,
        )

    # ========================================================
    # ACTIVITY
    # ========================================================

    def get_current_activity(
        self,
    ) -> str | None:

        output = self.shell(
            "dumpsys",
            "window",
            "windows",
            check=False,
        )

        patterns = (
            r"mCurrentFocus=.*?\s([\w.$]+/[\w.$]+)",
            r"mFocusedApp=.*?\s([\w.$]+/[\w.$]+)",
        )

        for pattern in patterns:

            match = re.search(
                pattern,
                output,
            )

            if match:
                return match.group(1)

        return None

    # ========================================================
    # DEVICE CONTROL
    # ========================================================

    def reboot(self) -> None:

        logger.info(
            "[%s] Reboot device",
            self.serial,
        )

        self.client.run(
            "reboot",
            serial=self.serial,
        )

    def reboot_and_wait(
        self,
        timeout: float = 180.0,
        poll_interval: float = 2.0,
    ) -> None:

        self.reboot()

        deadline = time.monotonic() + timeout

        # Chờ thiết bị disconnect.
        while time.monotonic() < deadline:

            state = self.get_state()

            if state != "device":
                break

            time.sleep(
                poll_interval
            )

        # Chờ thiết bị online trở lại.
        remaining = max(
            1.0,
            deadline - time.monotonic(),
        )

        self.wait_until_online(
            timeout=remaining
        )