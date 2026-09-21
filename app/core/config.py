from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover - requirements.txt includes PyYAML
    yaml = None


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "app"
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
TEMP_DIR = ROOT_DIR / "temp"
ASSETS_DIR = ROOT_DIR / "assets"
MODELS_DIR = ROOT_DIR / "models"
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


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


def load_config_file(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML configuration. Missing files intentionally produce an empty config."""
    config_path = Path(path or os.getenv("DC3Q_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    if not config_path.is_file() or yaml is None:
        return {}

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")
    return data


def _deep_get(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _project_path(value: str | Path | None, fallback: Path) -> Path:
    if value in (None, ""):
        return fallback
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


_RAW_CONFIG = load_config_file()


def _default_adb_executable() -> str:
    configured = os.getenv("ADB_PATH")
    if configured:
        return configured

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        sdk_adb = Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        if sdk_adb.is_file():
            return str(sdk_adb)

    yaml_value = _deep_get(_RAW_CONFIG, "adb.executable")
    if yaml_value:
        candidate = _project_path(str(yaml_value), ROOT_DIR / "tools" / "adb" / "adb.exe")
        if candidate.is_file():
            return str(candidate)

    return "adb"


@dataclass(frozen=True, slots=True)
class ADBSettings:
    executable: str = field(default_factory=_default_adb_executable)
    command_timeout: float = field(
        default_factory=lambda: _env_float(
            "ADB_COMMAND_TIMEOUT", float(_deep_get(_RAW_CONFIG, "adb.command_timeout", 15.0))
        )
    )
    wait_for_device_timeout: float = field(
        default_factory=lambda: _env_float(
            "ADB_WAIT_DEVICE_TIMEOUT", float(_deep_get(_RAW_CONFIG, "adb.device_timeout", 60.0))
        )
    )
    install_timeout: float = field(default_factory=lambda: _env_float("ADB_INSTALL_TIMEOUT", 180.0))
    reboot_timeout: float = field(default_factory=lambda: _env_float("ADB_REBOOT_TIMEOUT", 180.0))
    reconnect_attempts: int = field(
        default_factory=lambda: _env_int(
            "ADB_RECONNECT_ATTEMPTS", int(_deep_get(_RAW_CONFIG, "adb.reconnect_attempts", 5))
        )
    )
    reconnect_delay: float = field(
        default_factory=lambda: _env_float(
            "ADB_RECONNECT_DELAY", float(_deep_get(_RAW_CONFIG, "adb.reconnect_delay", 2.0))
        )
    )


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = field(
        default_factory=lambda: os.getenv(
            "LOG_LEVEL", str(_deep_get(_RAW_CONFIG, "logging.level", "INFO"))
        ).upper()
    )
    filename: str = field(
        default_factory=lambda: os.getenv(
            "LOG_FILENAME", str(_deep_get(_RAW_CONFIG, "logging.filename", "dc3q_bot.log"))
        )
    )
    max_bytes: int = field(default_factory=lambda: _env_int("LOG_MAX_BYTES", 20 * 1024 * 1024))
    backup_count: int = field(default_factory=lambda: _env_int("LOG_BACKUP_COUNT", 5))
    console_enabled: bool = field(
        default_factory=lambda: _env_bool("LOG_CONSOLE", bool(_deep_get(_RAW_CONFIG, "logging.console", True)))
    )
    file_enabled: bool = field(
        default_factory=lambda: _env_bool("LOG_FILE", bool(_deep_get(_RAW_CONFIG, "logging.file", True)))
    )


@dataclass(frozen=True, slots=True)
class VisionSettings:
    enabled: bool = field(default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "vision.enabled", True)))
    template_threshold: float = field(
        default_factory=lambda: float(_deep_get(_RAW_CONFIG, "vision.template_threshold", 0.80))
    )
    minimum_threshold: float = field(
        default_factory=lambda: float(_deep_get(_RAW_CONFIG, "vision.minimum_threshold", 0.65))
    )
    grayscale: bool = field(default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "vision.grayscale", False)))
    multi_scale: bool = field(default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "vision.multi_scale", False)))
    scales: tuple[float, ...] = field(
        default_factory=lambda: tuple(float(v) for v in (_deep_get(_RAW_CONFIG, "vision.scales", [1.0]) or [1.0]))
    )
    templates_dir: Path = field(
        default_factory=lambda: _project_path(
            _deep_get(_RAW_CONFIG, "vision.templates_dir", "assets/templates"), ASSETS_DIR / "templates"
        )
    )


@dataclass(frozen=True, slots=True)
class YOLOSettings:
    enabled: bool = field(default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "yolo.enabled", True)))
    model_path: Path = field(
        default_factory=lambda: _project_path(
            _deep_get(_RAW_CONFIG, "yolo.model_path", "models/yolo/best.pt"), MODELS_DIR / "yolo" / "best.pt"
        )
    )
    device: str | int | None = field(default_factory=lambda: _deep_get(_RAW_CONFIG, "yolo.device", "auto"))
    confidence: float = field(default_factory=lambda: float(_deep_get(_RAW_CONFIG, "yolo.confidence", 0.50)))
    iou: float = field(default_factory=lambda: float(_deep_get(_RAW_CONFIG, "yolo.iou", 0.45)))
    image_size: int = field(default_factory=lambda: int(_deep_get(_RAW_CONFIG, "yolo.image_size", 640)))

    @property
    def runtime_device(self) -> str | int | None:
        value = self.device
        if isinstance(value, str) and value.lower() == "auto":
            return None
        return value


@dataclass(frozen=True, slots=True)
class AutomationSettings:
    enabled: bool = field(default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "automation.enabled", True)))
    loop_interval: float = field(
        default_factory=lambda: float(_deep_get(_RAW_CONFIG, "automation.loop_interval", 0.10))
    )
    action_retry_count: int = field(
        default_factory=lambda: int(_deep_get(_RAW_CONFIG, "automation.action_retry_count", 3))
    )
    action_retry_delay: float = field(
        default_factory=lambda: float(_deep_get(_RAW_CONFIG, "automation.action_retry_delay", 1.0))
    )
    scripts_dir: Path = field(
        default_factory=lambda: _project_path(
            _deep_get(_RAW_CONFIG, "automation.scripts_dir", "scripts"), ROOT_DIR / "scripts"
        )
    )


@dataclass(frozen=True, slots=True)
class AccountsSettings:
    source_file: Path = field(
        default_factory=lambda: _project_path(
            _deep_get(_RAW_CONFIG, "accounts.source_file", "data/accounts/accounts.xlsx"),
            DATA_DIR / "accounts" / "accounts.xlsx",
        )
    )
    runtime_file: Path = field(
        default_factory=lambda: _project_path(
            _deep_get(_RAW_CONFIG, "accounts.runtime_file", "data/accounts/account_runtime.json"),
            DATA_DIR / "accounts" / "account_runtime.json",
        )
    )
    archive_dir: Path = field(
        default_factory=lambda: _project_path(
            _deep_get(_RAW_CONFIG, "accounts.archive_dir", "data/accounts/history"),
            DATA_DIR / "accounts" / "history",
        )
    )
    reset_hour: int = field(
        default_factory=lambda: int(_deep_get(_RAW_CONFIG, "accounts.reset_hour", 23))
    )
    exclusive_lock: bool = field(
        default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "accounts.exclusive_lock", True))
    )
    auto_next_account: bool = field(
        default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "accounts.auto_next_account", True))
    )
    retry_failed_login: bool = field(
        default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "accounts.retry_failed_login", True))
    )
    login_retry_count: int = field(
        default_factory=lambda: int(_deep_get(_RAW_CONFIG, "accounts.login_retry_count", 3))
    )
    default_status: str = field(
        default_factory=lambda: str(_deep_get(_RAW_CONFIG, "accounts.default_status", "READY")).upper()
    )


@dataclass(frozen=True, slots=True)
class DevicesSettings:
    max_workers: int = field(default_factory=lambda: int(_deep_get(_RAW_CONFIG, "devices.max_workers", 8)))
    auto_discover: bool = field(default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "devices.auto_discover", True)))
    status_check_interval: float = field(
        default_factory=lambda: float(_deep_get(_RAW_CONFIG, "devices.status_check_interval", 5.0))
    )
    restart_worker_on_reconnect: bool = field(
        default_factory=lambda: bool(_deep_get(_RAW_CONFIG, "devices.restart_worker_on_reconnect", True))
    )


@dataclass(frozen=True, slots=True)
class AppSettings:
    app_name: str = field(default_factory=lambda: str(_deep_get(_RAW_CONFIG, "app.name", "DC3Q YOLO BOT ADB")))
    version: str = field(default_factory=lambda: str(_deep_get(_RAW_CONFIG, "app.version", "0.1.1")))
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", bool(_deep_get(_RAW_CONFIG, "app.debug", False))))

    root_dir: Path = ROOT_DIR
    app_dir: Path = APP_DIR
    data_dir: Path = DATA_DIR
    log_dir: Path = LOG_DIR
    temp_dir: Path = TEMP_DIR
    assets_dir: Path = ASSETS_DIR
    models_dir: Path = MODELS_DIR
    config_path: Path = DEFAULT_CONFIG_PATH
    raw: Mapping[str, Any] = field(default_factory=lambda: dict(_RAW_CONFIG))

    adb: ADBSettings = field(default_factory=ADBSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    vision: VisionSettings = field(default_factory=VisionSettings)
    yolo: YOLOSettings = field(default_factory=YOLOSettings)
    automation: AutomationSettings = field(default_factory=AutomationSettings)
    accounts: AccountsSettings = field(default_factory=AccountsSettings)
    devices: DevicesSettings = field(default_factory=DevicesSettings)

    def get(self, path: str, default: Any = None) -> Any:
        return _deep_get(self.raw, path, default)

    def resolve_path(self, value: str | Path, base: Path | None = None) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return (base or self.root_dir) / path

    def ensure_directories(self) -> None:
        directories = (
            self.data_dir,
            self.log_dir,
            self.temp_dir,
            self.vision.templates_dir,
            self.accounts.source_file.parent,
            self.accounts.archive_dir,
            self.automation.scripts_dir,
            self.models_dir / "yolo",
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


settings = AppSettings()
