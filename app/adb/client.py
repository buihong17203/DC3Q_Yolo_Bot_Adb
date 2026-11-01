from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Sequence


class AdbError(RuntimeError):
    """Raised when an ADB command cannot be executed successfully."""


class AdbClient:
    """Small, synchronous wrapper around the adb executable."""

    def __init__(self, adb_path: str = "adb", timeout: float = 15.0) -> None:
        self.adb_path = adb_path
        self.timeout = timeout

    def _command(self, args: Sequence[str]) -> list[str]:
        return [self.adb_path, *map(str, args)]

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
        check: bool = True,
        binary: bool = False,
    ) -> subprocess.CompletedProcess:

        command = self._command(args)

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=not binary,
                encoding=None if binary else "utf-8",
                errors=None if binary else "replace",
                start_new_session=(os.name != "nt"),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise AdbError(
                f"Không tìm thấy ADB executable: {self.adb_path!r}. "
                "Hãy cài Android SDK Platform-Tools hoặc cấu hình adb_path."
            ) from exc
        except OSError as exc:
            raise AdbError(f"Không thể khởi chạy ADB: {exc}") from exc

        try:
            stdout, stderr = process.communicate(
                timeout=self.timeout if timeout is None else timeout
            )
        except subprocess.TimeoutExpired as exc:
            self._terminate_process(process)
            raise AdbError(f"ADB timeout sau {timeout or self.timeout}s: {' '.join(command)}") from exc

        result = subprocess.CompletedProcess(
            command, process.returncode, stdout or "", stderr or ""
        )

        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise AdbError(
                f"ADB command thất bại (exit={result.returncode}): "
                f"{' '.join(command)}\n{detail}"
            )

        return result

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return

        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGTERM)
        except (OSError, ValueError):
            pass

        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def version(self) -> str:
        result = self.run(["version"])
        return result.stdout.strip()

    def start_server(self) -> str:
        result = self.run(["start-server"])
        return (result.stdout or result.stderr).strip()

    def devices_raw(self) -> str:
        return self.run(["devices", "-l"]).stdout

    def shell(self, serial: str, *args: str, timeout: float | None = None) -> str:
        result = self.run(["-s", serial, "shell", *args], timeout=timeout)
        return result.stdout.strip()

    def connect(self, address: str) -> str:
        return self.run(["connect", address]).stdout.strip()

    def disconnect(self, address: str) -> str:
        return self.run(["disconnect", address]).stdout.strip()
