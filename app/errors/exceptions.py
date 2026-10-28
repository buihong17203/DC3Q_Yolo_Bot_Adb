from __future__ import annotations

from typing import Any
from app.errors.categories import ErrorCategory, ErrorSeverity


class BotError(Exception):
    """Lớp cha cho toàn bộ lỗi được quản lý trong bot."""

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.SYSTEM_FATAL,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        account_id: str | None = None,
        task_name: str | None = None,
        device_serial: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.account_id = account_id
        self.task_name = task_name
        self.device_serial = device_serial
        self.details = details or {}

    def __str__(self) -> str:
        ctx = []
        if self.account_id:
            ctx.append(f"acc={self.account_id}")
        if self.task_name:
            ctx.append(f"task={self.task_name}")
        ctx_str = f" [{', '.join(ctx)}]" if ctx else ""
        return f"[{self.category.name} | {self.severity.value}]{ctx_str} {self.message}"


class AdbLostConnectionError(BotError):
    """Lỗi mất kết nối thiết bị ADB hoặc adb daemon gặp sự cố."""

    def __init__(self, message: str, *, device_serial: str | None = None, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.ADB_CONNECTION,
            severity=ErrorSeverity.CRITICAL,
            device_serial=device_serial,
            **kwargs,
        )


class GameCrashError(BotError):
    """Lỗi game bị văng / tự thoát ra ngoài màn hình Android Launcher."""

    def __init__(self, message: str = "Game com.daichien.mobile bị crash/văng ra ngoài", **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.APP_CRASH_ANR,
            severity=ErrorSeverity.HIGH,
            **kwargs,
        )


class GameAnrError(BotError):
    """Lỗi ANR (Application Not Responding) xuất hiện popup đơ ứng dụng."""

    def __init__(self, message: str = "Phát hiện popup ANR (Ứng dụng không phản hồi)", **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.APP_CRASH_ANR,
            severity=ErrorSeverity.HIGH,
            **kwargs,
        )


class AccountAuthError(BotError):
    """Lỗi xác thực tài khoản: sai mật khẩu, server từ chối, kẹt ô đăng nhập."""

    def __init__(
        self,
        message: str,
        *,
        invalid_credentials: bool = False,
        skip_account: bool = True,
        **kwargs,
    ):
        super().__init__(
            message,
            category=ErrorCategory.ACCOUNT_AUTH,
            severity=ErrorSeverity.HIGH,
            **kwargs,
        )
        self.invalid_credentials = invalid_credentials
        self.skip_account = skip_account


class UiStuckError(BotError):
    """Lỗi mắc kẹt giao diện: popup lạ không đóng được, không tìm thấy đường về HOME."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.UI_STUCK_POPUP,
            severity=ErrorSeverity.HIGH,
            **kwargs,
        )


class TaskExecutionError(BotError):
    """Lỗi xảy ra trong quá trình chạy một nhiệm vụ cụ thể."""

    def __init__(self, task_name: str, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.TASK_FAILURE,
            severity=ErrorSeverity.MEDIUM,
            task_name=task_name,
            **kwargs,
        )


class VisionCaptureError(BotError):
    """Lỗi chụp ảnh màn hình hoặc ảnh bị hỏng/đen."""

    def __init__(self, message: str = "Không chụp được ảnh màn hình hoặc ảnh rỗng", **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.VISION_CAPTURE,
            severity=ErrorSeverity.HIGH,
            **kwargs,
        )
