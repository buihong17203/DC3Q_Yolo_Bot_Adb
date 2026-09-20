from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.core.logger import get_logger


logger = get_logger(__name__)


# ============================================================
# EXCEPTION
# ============================================================

class ADBError(RuntimeError):
    """
    Exception cơ sở của tầng ADB.
    """


class ADBNotFoundError(ADBError):
    """
    Không tìm thấy adb / adb.exe.
    """


class ADBTimeoutError(ADBError):
    """
    Lệnh ADB chạy quá thời gian cho phép.
    """


class ADBCommandError(ADBError):
    """
    ADB trả về exit code khác 0.
    """

    def __init__(self, result: "ADBResult") -> None:
        self.result = result

        message = (
            f"ADB command failed with exit code "
            f"{result.returncode}:\n"
            f"{result.command}\n"
        )

        if result.stderr:
            message += f"\nSTDERR:\n{result.stderr}"

        elif result.stdout:
            message += f"\nSTDOUT:\n{result.stdout}"

        super().__init__(message)


# ============================================================
# DATA MODEL
# ============================================================

@dataclass(frozen=True, slots=True)
class ADBResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """
    Thông tin lấy từ:

        adb devices -l
    """

    serial: str
    state: str

    properties: dict[str, str] = field(
        default_factory=dict
    )

    @property
    def model(self) -> str | None:
        return self.properties.get("model")

    @property
    def product(self) -> str | None:
        return self.properties.get("product")

    @property
    def device(self) -> str | None:
        return self.properties.get("device")

    @property
    def transport_id(self) -> str | None:
        return self.properties.get("transport_id")

    @property
    def is_online(self) -> bool:
        return self.state == "device"

    @property
    def is_offline(self) -> bool:
        return self.state == "offline"

    @property
    def is_unauthorized(self) -> bool:
        return self.state == "unauthorized"


# ============================================================
# ADB CLIENT
# ============================================================

class ADBClient:
    """
    Lớp giao tiếp trực tiếp với adb.exe.

    Các module khác không nên tự subprocess adb.
    Toàn bộ lệnh ADB nên đi qua class này.
    """

    def __init__(
        self,
        executable: str | None = None,
        timeout: float | None = None,
    ) -> None:

        self.executable = (
            executable
            or settings.adb.executable
        )

        self.timeout = (
            timeout
            if timeout is not None
            else settings.adb.command_timeout
        )

    # ========================================================
    # INTERNAL
    # ========================================================

    def _build_command(
        self,
        args: Iterable[object],
        serial: str | None = None,
    ) -> list[str]:

        command = [self.executable]

        if serial:
            command.extend([
                "-s",
                serial,
            ])

        command.extend(
            str(arg)
            for arg in args
        )

        return command

    @staticmethod
    def _command_to_string(
        command: list[str],
    ) -> str:
        """
        Chuyển command list thành chuỗi dễ đọc trong log.

        subprocess.list2cmdline tương thích tốt với Windows.
        """

        return subprocess.list2cmdline(command)

    # ========================================================
    # TEXT COMMAND
    # ========================================================

    def run(
        self,
        *args: object,
        serial: str | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> ADBResult:

        command = self._build_command(
            args=args,
            serial=serial,
        )

        command_text = self._command_to_string(
            command
        )

        effective_timeout = (
            timeout
            if timeout is not None
            else self.timeout
        )

        logger.debug(
            "ADB command: %s",
            command_text,
        )

        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                check=False,
            )

        except FileNotFoundError as exc:
            raise ADBNotFoundError(
                f"Không tìm thấy ADB executable: "
                f"{self.executable}"
            ) from exc

        except subprocess.TimeoutExpired as exc:
            raise ADBTimeoutError(
                f"ADB command timeout "
                f"({effective_timeout}s): "
                f"{command_text}"
            ) from exc

        result = ADBResult(
            command=command_text,
            returncode=completed.returncode,
            stdout=(completed.stdout or "").strip(),
            stderr=(completed.stderr or "").strip(),
        )

        if check and not result.ok:
            raise ADBCommandError(result)

        return result

    # ========================================================
    # BINARY COMMAND
    # ========================================================

    def run_bytes(
        self,
        *args: object,
        serial: str | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> bytes:

        command = self._build_command(
            args=args,
            serial=serial,
        )

        command_text = self._command_to_string(
            command
        )

        effective_timeout = (
            timeout
            if timeout is not None
            else self.timeout
        )

        logger.debug(
            "ADB binary command: %s",
            command_text,
        )

        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=effective_timeout,
                check=False,
            )

        except FileNotFoundError as exc:
            raise ADBNotFoundError(
                f"Không tìm thấy ADB executable: "
                f"{self.executable}"
            ) from exc

        except subprocess.TimeoutExpired as exc:
            raise ADBTimeoutError(
                f"ADB command timeout "
                f"({effective_timeout}s): "
                f"{command_text}"
            ) from exc

        if check and completed.returncode != 0:

            stderr = (
                completed.stderr
                or b""
            ).decode(
                "utf-8",
                errors="replace",
            )

            result = ADBResult(
                command=command_text,
                returncode=completed.returncode,
                stdout="",
                stderr=stderr.strip(),
            )

            raise ADBCommandError(result)

        return completed.stdout or b""

    # ========================================================
    # SERVER
    # ========================================================

    def version(self) -> str:
        return self.run(
            "version"
        ).stdout

    def start_server(self) -> None:
        self.run(
            "start-server"
        )

    def kill_server(self) -> None:
        self.run(
            "kill-server"
        )

    # ========================================================
    # DEVICE DISCOVERY
    # ========================================================

    def devices(self) -> list[DeviceInfo]:
        """
        Lấy danh sách toàn bộ thiết bị mà ADB nhìn thấy.

        Bao gồm:
            device
            offline
            unauthorized
            ...
        """

        result = self.run(
            "devices",
            "-l",
        )

        devices: list[DeviceInfo] = []

        lines = result.stdout.splitlines()

        for raw_line in lines:

            line = raw_line.strip()

            if not line:
                continue

            if line.startswith(
                "List of devices attached"
            ):
                continue

            # Bỏ qua message từ ADB daemon nếu có.
            if line.startswith("*"):
                continue

            parts = line.split()

            if len(parts) < 2:
                continue

            serial = parts[0]
            state = parts[1]

            properties: dict[str, str] = {}

            for token in parts[2:]:

                if ":" not in token:
                    continue

                key, value = token.split(
                    ":",
                    maxsplit=1,
                )

                properties[key] = value

            devices.append(
                DeviceInfo(
                    serial=serial,
                    state=state,
                    properties=properties,
                )
            )

        return devices

    def get_state(
        self,
        serial: str,
    ) -> str | None:

        result = self.run(
            "get-state",
            serial=serial,
            check=False,
        )

        if not result.ok:
            return None

        state = result.stdout.strip()

        return state or None

    def wait_for_device(
        self,
        serial: str | None = None,
        timeout: float | None = None,
    ) -> None:

        effective_timeout = (
            timeout
            if timeout is not None
            else settings.adb.wait_for_device_timeout
        )

        self.run(
            "wait-for-device",
            serial=serial,
            timeout=effective_timeout,
        )

    # ========================================================
    # NETWORK ADB
    # ========================================================

    def connect(
        self,
        host: str,
        port: int = 5555,
    ) -> str:

        target = f"{host}:{port}"

        result = self.run(
            "connect",
            target,
        )

        return result.stdout

    def disconnect(
        self,
        host: str | None = None,
        port: int = 5555,
    ) -> str:

        if host is None:

            result = self.run(
                "disconnect"
            )

        else:

            target = f"{host}:{port}"

            result = self.run(
                "disconnect",
                target,
            )

        return result.stdout

    # ========================================================
    # SHELL
    # ========================================================

    def shell(
        self,
        *args: object,
        serial: str,
        timeout: float | None = None,
        check: bool = True,
    ) -> str:

        result = self.run(
            "shell",
            *args,
            serial=serial,
            timeout=timeout,
            check=check,
        )

        return result.stdout

    def exec_out(
        self,
        *args: object,
        serial: str,
        timeout: float | None = None,
    ) -> bytes:

        return self.run_bytes(
            "exec-out",
            *args,
            serial=serial,
            timeout=timeout,
        )

    # ========================================================
    # FILE
    # ========================================================

    def push(
        self,
        local_path: str | Path,
        remote_path: str,
        serial: str,
        timeout: float | None = None,
    ) -> str:

        result = self.run(
            "push",
            str(local_path),
            remote_path,
            serial=serial,
            timeout=timeout,
        )

        return result.stdout

    def pull(
        self,
        remote_path: str,
        local_path: str | Path,
        serial: str,
        timeout: float | None = None,
    ) -> str:

        result = self.run(
            "pull",
            remote_path,
            str(local_path),
            serial=serial,
            timeout=timeout,
        )

        return result.stdout

    # ========================================================
    # APK
    # ========================================================

    def install(
        self,
        apk_path: str | Path,
        serial: str,
        replace: bool = True,
        grant_permissions: bool = False,
    ) -> str:

        args: list[object] = [
            "install",
        ]

        if replace:
            args.append("-r")

        if grant_permissions:
            args.append("-g")

        args.append(
            str(apk_path)
        )

        result = self.run(
            *args,
            serial=serial,
            timeout=settings.adb.install_timeout,
        )

        return result.stdout

    def uninstall(
        self,
        package_name: str,
        serial: str,
        keep_data: bool = False,
    ) -> str:

        args: list[object] = [
            "uninstall",
        ]

        if keep_data:
            args.append("-k")

        args.append(
            package_name
        )

        result = self.run(
            *args,
            serial=serial,
        )

        return result.stdout