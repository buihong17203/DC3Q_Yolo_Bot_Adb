from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.core.config import settings
from app.core.game_day import GameDayClock


_config_lock = threading.Lock()
_configured = False


class GameDayFileHandler(logging.Handler):
    """Write one log file per 23:00-to-22:59 game day."""

    def __init__(self, directory: Path, filename: str, reset_hour: int = 23) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.stem = Path(filename).stem
        self.suffix = Path(filename).suffix or ".log"
        self.clock = GameDayClock(reset_hour)
        self._key: str | None = None
        self._stream = None
        self._lock = threading.RLock()

    def _ensure_stream(self) -> None:
        key = self.clock.key()
        if self._stream is not None and self._key == key:
            return
        if self._stream is not None:
            self._stream.close()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._key = key
        self._stream = (self.directory / f"{self.stem}_{key}{self.suffix}").open("a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._ensure_stream()
                assert self._stream is not None
                self._stream.write(self.format(record) + "\n")
                self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        super().close()


def configure_logging() -> None:
    """
    Khởi tạo hệ thống logging toàn ứng dụng.

    Chỉ cấu hình một lần dù hàm được gọi nhiều lần.
    """

    global _configured

    if _configured:
        return

    with _config_lock:
        if _configured:
            return

        settings.ensure_directories()

        log_level = getattr(
            logging,
            settings.logging.level,
            logging.INFO,
        )

        formatter = logging.Formatter(
            fmt=(
                "%(asctime)s | "
                "%(levelname)-8s | "
                "%(name)s | "
                "%(threadName)s | "
                "%(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        root_logger = logging.getLogger()

        root_logger.setLevel(log_level)

        # Xóa handler cũ để tránh log bị in lặp.
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # ====================================================
        # LOG RA CONSOLE
        # ====================================================

        if settings.logging.console_enabled:
            console_handler = logging.StreamHandler()

            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)

            root_logger.addHandler(console_handler)

        # ====================================================
        # LOG RA FILE
        # ====================================================

        if settings.logging.file_enabled:
            file_handler = GameDayFileHandler(
                settings.log_dir,
                settings.logging.filename,
                settings.accounts.reset_hour,
            )

            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)

            root_logger.addHandler(file_handler)

        _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Lấy logger dùng cho từng module.

    Ví dụ:
        logger = get_logger(__name__)
    """

    configure_logging()

    return logging.getLogger(name)