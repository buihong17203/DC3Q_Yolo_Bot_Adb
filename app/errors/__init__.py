from __future__ import annotations

from app.errors.categories import ErrorCategory, ErrorSeverity
from app.errors.exceptions import (
    BotError,
    AdbLostConnectionError,
    GameCrashError,
    GameAnrError,
    AccountAuthError,
    UiStuckError,
    TaskExecutionError,
    VisionCaptureError,
)
from app.errors.handler import ErrorManager
from app.errors.strategies import (
    RecoveryAction,
    recover_app_crash,
    recover_ui_stuck,
    handle_account_auth_failure,
    handle_task_failure,
)

__all__ = [
    "ErrorCategory",
    "ErrorSeverity",
    "BotError",
    "AdbLostConnectionError",
    "GameCrashError",
    "GameAnrError",
    "AccountAuthError",
    "UiStuckError",
    "TaskExecutionError",
    "VisionCaptureError",
    "ErrorManager",
    "RecoveryAction",
    "recover_app_crash",
    "recover_ui_stuck",
    "handle_account_auth_failure",
    "handle_task_failure",
]
