from __future__ import annotations

import os
import time
from typing import Iterable

from app.core.logger import get_logger

logger = get_logger(__name__)


def terminate_child_processes(
    *,
    timeout: float = 1.5,
    exclude_pids: Iterable[int] | None = None,
) -> int:
    """Terminate only processes spawned below the current Python process.

    This intentionally does not kill the global ADB server. It is used as a
    final cleanup path for adb.exe/other subprocesses that are still blocking
    worker threads when Ctrl+C is pressed.
    """

    try:
        import psutil
    except ImportError:
        logger.warning("psutil không khả dụng; bỏ qua cleanup child process")
        return 0

    excluded = {int(pid) for pid in (exclude_pids or ())}
    current_pid = os.getpid()
    try:
        current = psutil.Process(current_pid)
        children = [
            child
            for child in current.children(recursive=True)
            if child.pid not in excluded
        ]
    except psutil.Error:
        return 0

    if not children:
        return 0

    logger.warning("Đang dừng %d child process của project", len(children))
    for child in children:
        try:
            child.terminate()
        except psutil.Error:
            pass

    wait_timeout = max(0.0, float(timeout))
    try:
        _, alive = psutil.wait_procs(children, timeout=wait_timeout)
    except psutil.Error:
        alive = []

    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass

    if alive:
        try:
            psutil.wait_procs(alive, timeout=min(0.5, wait_timeout or 0.5))
        except psutil.Error:
            pass

    return len(children)


def join_threads_until(
    threads: Iterable[object],
    *,
    timeout: float,
) -> int:
    """Join thread-like objects under one shared timeout budget.

    Objects only need ``join(timeout=...)`` and ``is_alive()``.
    Returns how many are still alive after the deadline.
    """

    deadline = time.monotonic() + max(0.0, float(timeout))
    items = list(threads)
    for thread in items:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            thread.join(timeout=remaining)
        except RuntimeError:
            pass

    alive = 0
    for thread in items:
        try:
            if thread.is_alive():
                alive += 1
        except Exception:
            pass
    return alive
