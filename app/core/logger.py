from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler

from app.core.config import settings


_config_lock = threading.Lock()
_configured = False


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
            log_file = (
                settings.log_dir
                / settings.logging.filename
            )

            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=settings.logging.max_bytes,
                backupCount=settings.logging.backup_count,
                encoding="utf-8",
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