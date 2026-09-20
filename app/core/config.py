from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# ĐƯỜNG DẪN GỐC DỰ ÁN

ROOT_DIR = Path(__file__).resolve().parents[2]

APP_DIR = ROOT_DIR / "app"
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
TEMP_DIR = ROOT_DIR / "temp"
ASSETS_DIR = ROOT_DIR / "assets"
MODELS_DIR = ROOT_DIR / "models"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enable",
        "enabled",
    }


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        return default


# CẤU HÌNH ADB


def _default_adb_executable() -> str:
    configured = os.getenv("ADB_PATH")
    if configured:
        return configured

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        sdk_adb = (
            Path(local_app_data)
            / "Android"
            / "Sdk"
            / "platform-tools"
            / "adb.exe"
        )
        if sdk_adb.is_file():
            return str(sdk_adb)

    return "adb"


@dataclass(frozen=True, slots=True)
class ADBSettings:
    """
    Cấu hình chung cho tầng ADB.

    ADB_PATH:
        Đường dẫn đến adb.exe.

        Nếu adb đã nằm trong PATH của Windows:
            ADB_PATH=adb

        Nếu dùng Android Platform Tools riêng:
            ADB_PATH=C:/platform-tools/adb.exe
    """

    executable: str = field(
        default_factory=_default_adb_executable
    )

    # Timeout mặc định cho một lệnh ADB.
    command_timeout: float = field(
        default_factory=lambda: _env_float(
            "ADB_COMMAND_TIMEOUT",
            15.0,
        )
    )

    # Timeout khi chờ thiết bị xuất hiện.
    wait_for_device_timeout: float = field(
        default_factory=lambda: _env_float(
            "ADB_WAIT_DEVICE_TIMEOUT",
            60.0,
        )
    )

    # Timeout các thao tác cài APK.
    install_timeout: float = field(
        default_factory=lambda: _env_float(
            "ADB_INSTALL_TIMEOUT",
            180.0,
        )
    )

    # Thời gian chờ thao tác reboot.
    reboot_timeout: float = field(
        default_factory=lambda: _env_float(
            "ADB_REBOOT_TIMEOUT",
            180.0,
        )
    )


# CẤU HÌNH LOG

@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = field(
        default_factory=lambda: os.getenv(
            "LOG_LEVEL",
            "INFO",
        ).upper()
    )

    filename: str = field(
        default_factory=lambda: os.getenv(
            "LOG_FILENAME",
            "dc3q_bot.log",
        )
    )

    # 10 MB.
    max_bytes: int = field(
        default_factory=lambda: _env_int(
            "LOG_MAX_BYTES",
            10 * 1024 * 1024,
        )
    )

    backup_count: int = field(
        default_factory=lambda: _env_int(
            "LOG_BACKUP_COUNT",
            5,
        )
    )

    console_enabled: bool = field(
        default_factory=lambda: _env_bool(
            "LOG_CONSOLE",
            True,
        )
    )

    file_enabled: bool = field(
        default_factory=lambda: _env_bool(
            "LOG_FILE",
            True,
        )
    )

# CẤU HÌNH ỨNG DỤNG

@dataclass(frozen=True, slots=True)
class AppSettings:
    app_name: str = "DC3Q YOLO BOT ADB"

    debug: bool = field(
        default_factory=lambda: _env_bool(
            "DEBUG",
            False,
        )
    )

    root_dir: Path = ROOT_DIR
    app_dir: Path = APP_DIR
    data_dir: Path = DATA_DIR
    log_dir: Path = LOG_DIR
    temp_dir: Path = TEMP_DIR
    assets_dir: Path = ASSETS_DIR
    models_dir: Path = MODELS_DIR

    adb: ADBSettings = field(
        default_factory=ADBSettings
    )

    logging: LoggingSettings = field(
        default_factory=LoggingSettings
    )

    def ensure_directories(self) -> None:
        """
        Tạo các thư mục runtime nếu chưa tồn tại.
        """

        directories = (
            self.data_dir,
            self.log_dir,
            self.temp_dir,
        )

        for directory in directories:
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )


# SINGLETON CONFIG
settings = AppSettings()