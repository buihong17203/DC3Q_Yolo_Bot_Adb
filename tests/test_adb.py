from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import (
    Mock,
    patch,
)

from app.adb.client import (
    ADBClient,
    ADBCommandError,
    DeviceInfo,
)

from app.adb.device import ADBDevice
from app.adb.device_manager import (
    ADBDeviceManager,
)
from app.core.config import _default_adb_executable


class TestADBConfig(unittest.TestCase):

    def test_prefers_android_sdk_adb_over_path_alias(self) -> None:
        with patch.dict(
            "os.environ",
            {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"},
            clear=True,
        ), patch.object(Path, "is_file", return_value=True):
            self.assertEqual(
                _default_adb_executable(),
                str(Path("C:/Users/Test/AppData/Local/Android/Sdk/platform-tools/adb.exe")),
            )


def completed_process(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess:

    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestADBClient(unittest.TestCase):

    def test_devices_parser(self) -> None:

        output = (
            "List of devices attached\n"
            "emulator-5554 device "
            "product:sdk_gphone64_x86_64 "
            "model:sdk_gphone64_x86_64 "
            "device:emu64xa "
            "transport_id:1\n"
            "\n"
            "emulator-5556 offline "
            "transport_id:2\n"
            "\n"
            "127.0.0.1:5555 unauthorized "
            "transport_id:3\n"
        )

        client = ADBClient(
            executable="adb"
        )

        with patch(
            "app.adb.client.subprocess.run",
            return_value=completed_process(
                stdout=output
            ),
        ) as run_mock:

            devices = client.devices()

        self.assertEqual(
            len(devices),
            3,
        )

        first = devices[0]

        self.assertEqual(
            first.serial,
            "emulator-5554",
        )

        self.assertEqual(
            first.state,
            "device",
        )

        self.assertTrue(
            first.is_online
        )

        self.assertEqual(
            first.model,
            "sdk_gphone64_x86_64",
        )

        second = devices[1]

        self.assertTrue(
            second.is_offline
        )

        third = devices[2]

        self.assertTrue(
            third.is_unauthorized
        )

        command = (
            run_mock.call_args.args[0]
        )

        self.assertEqual(
            command,
            [
                "adb",
                "devices",
                "-l",
            ],
        )

    def test_shell_command_contains_serial(
        self,
    ) -> None:

        client = ADBClient(
            executable="adb"
        )

        with patch(
            "app.adb.client.subprocess.run",
            return_value=completed_process(
                stdout=(
                    "Physical size: "
                    "1280x720"
                )
            ),
        ) as run_mock:

            output = client.shell(
                "wm",
                "size",
                serial="emulator-5554",
            )

        self.assertIn(
            "1280x720",
            output,
        )

        command = (
            run_mock.call_args.args[0]
        )

        self.assertEqual(
            command,
            [
                "adb",
                "-s",
                "emulator-5554",
                "shell",
                "wm",
                "size",
            ],
        )

    def test_command_error(
        self,
    ) -> None:

        client = ADBClient(
            executable="adb"
        )

        with patch(
            "app.adb.client.subprocess.run",
            return_value=completed_process(
                stderr="device not found",
                returncode=1,
            ),
        ):

            with self.assertRaises(
                ADBCommandError
            ):

                client.run(
                    "shell",
                    "echo",
                    "test",
                    serial="invalid-device",
                )


class TestADBDevice(unittest.TestCase):

    def test_tap(self) -> None:

        client = Mock(
            spec=ADBClient
        )

        client.shell.return_value = ""

        device = ADBDevice(
            serial="emulator-5554",
            client=client,
        )

        device.tap(
            100,
            200,
        )

        client.shell.assert_called_once_with(
            "input",
            "tap",
            100,
            200,
            serial="emulator-5554",
            timeout=None,
            check=True,
        )

    def test_swipe(self) -> None:

        client = Mock(
            spec=ADBClient
        )

        client.shell.return_value = ""

        device = ADBDevice(
            serial="emulator-5554",
            client=client,
        )

        device.swipe(
            10,
            20,
            300,
            400,
            duration_ms=500,
        )

        client.shell.assert_called_once_with(
            "input",
            "swipe",
            10,
            20,
            300,
            400,
            500,
            serial="emulator-5554",
            timeout=None,
            check=True,
        )

    def test_screen_size_physical(
        self,
    ) -> None:

        client = Mock(
            spec=ADBClient
        )

        client.shell.return_value = (
            "Physical size: 1280x720"
        )

        device = ADBDevice(
            serial="emulator-5554",
            client=client,
        )

        size = device.get_screen_size()

        self.assertEqual(
            size,
            (
                1280,
                720,
            ),
        )

    def test_screen_size_override(
        self,
    ) -> None:

        client = Mock(
            spec=ADBClient
        )

        client.shell.return_value = (
            "Physical size: 1920x1080\n"
            "Override size: 1280x720"
        )

        device = ADBDevice(
            serial="emulator-5554",
            client=client,
        )

        size = device.get_screen_size()

        self.assertEqual(
            size,
            (
                1280,
                720,
            ),
        )

    def test_screenshot(
        self,
    ) -> None:

        fake_png = (
            b"\x89PNG\r\n\x1a\n"
            b"fake-png-data"
        )

        client = Mock(
            spec=ADBClient
        )

        client.exec_out.return_value = (
            fake_png
        )

        device = ADBDevice(
            serial="emulator-5554",
            client=client,
        )

        data = device.screenshot()

        self.assertEqual(
            data,
            fake_png,
        )

        client.exec_out.assert_called_once_with(
            "screencap",
            "-p",
            serial="emulator-5554",
        )

    def test_save_screenshot(
        self,
    ) -> None:

        fake_png = (
            b"\x89PNG\r\n\x1a\n"
            b"test"
        )

        client = Mock(
            spec=ADBClient
        )

        client.exec_out.return_value = (
            fake_png
        )

        device = ADBDevice(
            serial="emulator-5554",
            client=client,
        )

        with tempfile.TemporaryDirectory() as temp_dir:

            path = (
                Path(temp_dir)
                / "screenshots"
                / "screen.png"
            )

            output = (
                device.save_screenshot(
                    path
                )
            )

            self.assertTrue(
                output.exists()
            )

            self.assertEqual(
                output.read_bytes(),
                fake_png,
            )


class TestADBDeviceManager(unittest.TestCase):

    def test_refresh_online_only(
        self,
    ) -> None:

        client = Mock(
            spec=ADBClient
        )

        client.devices.return_value = [
            DeviceInfo(
                serial="emulator-5554",
                state="device",
                properties={
                    "model": "Device_A",
                },
            ),
            DeviceInfo(
                serial="emulator-5556",
                state="offline",
                properties={
                    "model": "Device_B",
                },
            ),
        ]

        manager = ADBDeviceManager(
            client=client
        )

        devices = manager.refresh(
            online_only=True
        )

        self.assertEqual(
            len(devices),
            1,
        )

        self.assertEqual(
            devices[0].serial,
            "emulator-5554",
        )

        self.assertEqual(
            manager.count,
            2,
        )

        self.assertEqual(
            manager.online_count,
            1,
        )

    def test_refresh_all_devices(
        self,
    ) -> None:

        client = Mock(
            spec=ADBClient
        )

        client.devices.return_value = [
            DeviceInfo(
                serial="emulator-5554",
                state="device",
            ),
            DeviceInfo(
                serial="emulator-5556",
                state="offline",
            ),
        ]

        manager = ADBDeviceManager(
            client=client
        )

        devices = manager.refresh(
            online_only=False
        )

        self.assertEqual(
            len(devices),
            2,
        )

    def test_execute_parallel(
        self,
    ) -> None:

        client = Mock(
            spec=ADBClient
        )

        client.devices.return_value = [
            DeviceInfo(
                serial="emulator-5554",
                state="device",
            ),
            DeviceInfo(
                serial="emulator-5556",
                state="device",
            ),
        ]

        manager = ADBDeviceManager(
            client=client
        )

        devices = manager.refresh(
            online_only=True
        )

        results = manager.execute_parallel(
            lambda device: (
                f"OK:{device.serial}"
            ),
            devices=devices,
        )

        self.assertEqual(
            results["emulator-5554"],
            "OK:emulator-5554",
        )

        self.assertEqual(
            results["emulator-5556"],
            "OK:emulator-5556",
        )


if __name__ == "__main__":
    unittest.main()