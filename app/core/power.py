"""Quản lý trạng thái nguồn điện và chống máy tính Windows đi vào chế độ ngủ (Sleep)."""

from __future__ import annotations

import atexit
import ctypes
import logging
import os

LOGGER = logging.getLogger("dc3q")

# Windows SetThreadExecutionState flags:
# https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_is_preventing_sleep: bool = False


def prevent_sleep(keep_screen_on: bool = True) -> bool:
    """Yêu cầu Windows không đi vào chế độ Sleep và không tắt màn hình khi bot đang chạy."""
    global _is_preventing_sleep
    if os.name != "nt":
        return False
    try:
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        if keep_screen_on:
            flags |= ES_DISPLAY_REQUIRED
        result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
        if result == 0:
            LOGGER.warning("POWER | Không thể kích hoạt chế độ chống Sleep.")
            return False
        _is_preventing_sleep = True
        LOGGER.info("POWER | Đã kích hoạt chế độ chống Sleep (máy và màn hình luôn bật trong quá trình chạy).")
        return True
    except Exception as exc:
        LOGGER.warning("POWER | Lỗi khi thiết lập chống Sleep: %s", exc)
        return False


def restore_sleep() -> bool:
    """Khôi phục cài đặt quản lý nguồn mặc định của Windows khi dừng chương trình."""
    global _is_preventing_sleep
    if os.name != "nt" or not _is_preventing_sleep:
        return False
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        _is_preventing_sleep = False
        LOGGER.info("POWER | Đã khôi phục chế độ quản lý nguồn bình thường của Windows.")
        return True
    except Exception as exc:
        LOGGER.warning("POWER | Lỗi khi khôi phục quản lý nguồn: %s", exc)
        return False


# Đảm bảo luôn hoàn trả trạng thái sleep bình thường kể cả khi app bị tắt đột ngột
atexit.register(restore_sleep)
