from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from zoneinfo import ZoneInfo

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
from app.errors.strategies import (
    RecoveryAction,
    recover_app_crash,
    recover_ui_stuck,
    handle_account_auth_failure,
    handle_task_failure,
)

LOGGER = logging.getLogger("dc3q")
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


class ErrorManager:
    """Bộ Quản lý & Xử lý lỗi tập trung (Centralized Error Management System)."""

    def __init__(self, root_dir: Path | None = None, error_dir: Path | None = None):
        self.root = (root_dir or Path(__file__).resolve().parents[2]).resolve()
        self.error_dir = error_dir or (self.root / "docs" / "docs_days_runtime" / "error")
        self._lock = Lock()
        self.stats: dict[str, int] = {cat.name: 0 for cat in ErrorCategory}

    def classify_exception(
        self,
        exc: Exception,
        *,
        account_id: str | None = None,
        task_name: str | None = None,
        device_serial: str | None = None,
    ) -> BotError:
        """Phân loại ngoại lệ thô (Exception) thành BotError có nhóm danh mục và mức độ nghiêm trọng rõ ràng."""
        if isinstance(exc, BotError):
            if account_id and not exc.account_id:
                exc.account_id = account_id
            if task_name and not exc.task_name:
                exc.task_name = task_name
            if device_serial and not exc.device_serial:
                exc.device_serial = device_serial
            return exc

        msg = str(exc)
        exc_type = type(exc).__name__

        # 1. Nhóm lỗi ADB / Mất kết nối
        if "AdbError" in exc_type or "device not found" in msg.lower() or "device offline" in msg.lower():
            return AdbLostConnectionError(msg, device_serial=device_serial, account_id=account_id)

        # 2. Nhóm lỗi ANR
        if "anr" in msg.lower() or "không phản hồi" in msg.lower() or "application not responding" in msg.lower():
            return GameAnrError(msg, account_id=account_id, task_name=task_name, device_serial=device_serial)

        # 3. Nhóm lỗi Xác thực tài khoản / Login Form
        if any(keyword in msg.lower() for keyword in (
            "từ chối tài khoản hoặc mật khẩu",
            "sai mật khẩu",
            "khóa tài khoản",
            "không tìm thấy input cần xóa",
            "không tìm thấy nút đăng nhập",
            "hết thời gian chờ đăng nhập",
            "popup cập nhật thông tin",
        )):
            return AccountAuthError(
                msg,
                account_id=account_id,
                device_serial=device_serial,
                invalid_credentials=("từ chối tài khoản" in msg or "sai mật khẩu" in msg),
            )

        # 4. Nhóm lỗi Kẹt Giao Diện / Không về được HOME
        if any(keyword in msg.lower() for keyword in (
            "không recover được home",
            "chưa về home",
            "mở game lại 2 lần nhưng chưa về home",
            "hết thời gian chờ trạng thái",
            "không tìm thấy nút đóng",
        )):
            return UiStuckError(msg, account_id=account_id, task_name=task_name, device_serial=device_serial)

        # 5. Nhóm lỗi Vision / Ảnh
        if "screenshot" in msg.lower() or "ảnh màn hình" in msg.lower() or "image is none" in msg.lower():
            return VisionCaptureError(msg, account_id=account_id, task_name=task_name, device_serial=device_serial)

        # 6. Nhóm lỗi Task cụ thể
        if task_name:
            return TaskExecutionError(task_name, msg, account_id=account_id, device_serial=device_serial)

        # 7. Mặc định: Lỗi hệ thống ngoài dự kiến
        return BotError(
            f"[{exc_type}] {msg}",
            category=ErrorCategory.SYSTEM_FATAL,
            severity=ErrorSeverity.HIGH,
            account_id=account_id,
            task_name=task_name,
            device_serial=device_serial,
        )

    def log_error(self, error: BotError) -> None:
        """Ghi nhận lỗi tập trung vào Logger và file lưu trữ hàng ngày docs/docs_days_runtime/error/."""
        # 1. Cập nhật thống kê
        with self._lock:
            self.stats[error.category.name] = self.stats.get(error.category.name, 0) + 1

        # 2. Ghi ra Logger hệ thống
        log_msg = f"ERROR_MANAGER | Phân loại: {error.category.name} ({error.severity.value}) | {error}"
        if error.severity in (ErrorSeverity.HIGH, ErrorSeverity.CRITICAL):
            LOGGER.error(log_msg)
        else:
            LOGGER.warning(log_msg)

        # 3. Ghi ra file text docs/docs_days_runtime/error/error_message_YYYY-MM-DD.txt
        now = datetime.now(TIMEZONE)
        stamp = now.isoformat(timespec="seconds")
        day = now.date().isoformat()
        clean_msg = " ".join(error.message.splitlines()).strip()
        kind = "ACCOUNT" if error.category == ErrorCategory.ACCOUNT_AUTH else "TASK"

        line = f"{stamp} | account={error.account_id or '-'} | task={error.task_name or '-'} | type={kind} | {clean_msg}\n"
        try:
            self.error_dir.mkdir(parents=True, exist_ok=True)
            path = self.error_dir / f"error_message_{day}.txt"
            with self._lock:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as file_err:
            LOGGER.error("Không thể ghi log lỗi vào file: %s", file_err)

    def handle(
        self,
        exc: Exception,
        *,
        context: dict[str, Any] | None = None,
    ) -> RecoveryAction:
        """Phương thức cốt lõi: Nhận diện, ghi log và thực thi chiến lược xử lý phục hồi cho lỗi."""
        ctx = context or {}
        account_id = ctx.get("account_id")
        task_name = ctx.get("task_name")
        device_serial = ctx.get("device_serial")
        input_ctrl = ctx.get("input")
        runtime = ctx.get("runtime")
        accounts = ctx.get("accounts")
        scene_classifier = ctx.get("scene_classifier")
        screen_fn = ctx.get("screen_fn")
        restart_fn = ctx.get("restart_fn")

        # Chuẩn hóa lỗi
        bot_error = self.classify_exception(
            exc,
            account_id=account_id,
            task_name=task_name,
            device_serial=device_serial,
        )

        # Ghi log tập trung
        self.log_error(bot_error)

        # Điều phối chiến lược xử lý theo danh mục lỗi
        cat = bot_error.category

        # Trường hợp 1: Lỗi Xác thực tài khoản / Login Form
        if cat == ErrorCategory.ACCOUNT_AUTH:
            if runtime and accounts and account_id and device_serial:
                return handle_account_auth_failure(
                    runtime, accounts, account_id, device_serial, bot_error.message,
                    input_ctrl=input_ctrl,
                )
            return RecoveryAction(success=True, should_skip_account=True, message=bot_error.message)

        # Trường hợp 2: Lỗi Game Crash / ANR
        elif cat == ErrorCategory.APP_CRASH_ANR:
            if input_ctrl:
                return recover_app_crash(input_ctrl)
            return RecoveryAction(success=False, should_retry=True, message="Thiếu input_ctrl để restart app")

        # Trường hợp 3: Lỗi Kẹt Giao Diện (UI Stuck)
        elif cat == ErrorCategory.UI_STUCK_POPUP:
            if scene_classifier and screen_fn and input_ctrl:
                return recover_ui_stuck(scene_classifier, screen_fn, input_ctrl, restart_fn)
            return RecoveryAction(success=False, should_skip_account=True, message="Thiếu context phục hồi UI")

        # Trường hợp 4: Lỗi Nhiệm Vụ cụ thể (Task Failure)
        elif cat == ErrorCategory.TASK_FAILURE:
            if runtime and account_id and task_name:
                return handle_task_failure(
                    runtime, account_id, task_name, bot_error.message,
                    scene_classifier=scene_classifier,
                    screen_fn=screen_fn,
                    input_ctrl=input_ctrl,
                )
            return RecoveryAction(success=True, should_retry=False, message=bot_error.message)

        # Trường hợp 5: Lỗi ADB Connection
        elif cat == ErrorCategory.ADB_CONNECTION:
            LOGGER.critical("PHỤC HỒI LỖI | Mất kết nối ADB nghiêm trọng: %s", bot_error.message)
            return RecoveryAction(success=False, should_skip_account=False, message="Mất kết nối ADB")

        # Các lỗi khác: Mặc định cố gắng dọn dẹp và restart an toàn
        if input_ctrl:
            recover_app_crash(input_ctrl)
        return RecoveryAction(success=False, should_skip_account=True, message=f"Đã xử lý fallback: {bot_error.message}")

    def get_summary(self) -> dict[str, Any]:
        """Báo cáo thống kê tổng kết số lượng các loại lỗi đã xử lý."""
        with self._lock:
            return {
                "total_errors": sum(self.stats.values()),
                "by_category": dict(self.stats),
            }
