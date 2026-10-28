from __future__ import annotations

import logging
from time import sleep
from typing import Callable, Any

LOGGER = logging.getLogger("dc3q")


class RecoveryAction:
    """Đại diện cho kết quả xử lý phục hồi lỗi."""

    def __init__(self, success: bool, message: str = "", should_retry: bool = False, should_skip_account: bool = False):
        self.success = success
        self.message = message
        self.should_retry = should_retry
        self.should_skip_account = should_skip_account

    def __repr__(self) -> str:
        return f"RecoveryAction(success={self.success}, should_retry={self.should_retry}, should_skip_account={self.should_skip_account}, msg='{self.message}')"


def recover_app_crash(
    input_ctrl: Any,
    package: str = "com.daichien.mobile",
    wait_after_start: float = 3.0,
) -> RecoveryAction:
    """Xử lý đặc biệt khi game bị Crash/Văng hoặc ANR: buộc dừng và khởi động lại game."""
    try:
        LOGGER.info("PHỤC HỒI LỖI | Đang buộc dừng ứng dụng %s...", package)
        input_ctrl.shell("am", "force-stop", package)
        sleep(1.5)
        LOGGER.info("PHỤC HỒI LỖI | Đang mở lại ứng dụng %s...", package)
        input_ctrl.shell("monkey", "-p", package, "1")
        sleep(wait_after_start)
        return RecoveryAction(success=True, message="Đã restart game thành công sau crash", should_retry=True)
    except Exception as exc:
        LOGGER.error("PHỤC HỒI LỖI | Thất bại khi restart game sau crash: %s", exc)
        return RecoveryAction(success=False, message=f"Restart game thất bại: {exc}", should_skip_account=True)


def recover_ui_stuck(
    scene_classifier: Any,
    screen_fn: Callable[[], Any],
    input_ctrl: Any,
    restart_retained_home_fn: Callable[[], None] | None = None,
    max_ensure_steps: int = 4,
) -> RecoveryAction:
    """Xử lý đặc biệt khi UI bị kẹt: thử đóng popup trước, nếu không được thì restart về HOME."""
    LOGGER.info("PHỤC HỒI LỖI | Phát hiện kẹt giao diện, thử đóng popup/quay về HOME (max %d bước)...", max_ensure_steps)
    try:
        at_home = scene_classifier.ensure_home(screen_fn, input_ctrl, max_steps=max_ensure_steps)
        if at_home:
            LOGGER.info("PHỤC HỒI LỖI | Đã tự động thoát các popup và quay lại HOME thành công!")
            return RecoveryAction(success=True, message="Đã về HOME qua ensure_home", should_retry=True)
    except Exception as err:
        LOGGER.warning("PHỤC HỒI LỖI | ensure_home gặp lỗi: %s", err)

    if restart_retained_home_fn:
        try:
            LOGGER.info("PHỤC HỒI LỖI | ensure_home không thành công, thực hiện restart game giữ phiên login...")
            restart_retained_home_fn()
            return RecoveryAction(success=True, message="Đã restart game về retained HOME thành công", should_retry=True)
        except Exception as err:
            LOGGER.error("PHỤC HỒI LỖI | Không thể restart về HOME: %s", err)
            return RecoveryAction(success=False, message=f"Không thể thoát kẹt giao diện: {err}", should_skip_account=True)

    return RecoveryAction(success=False, message="Kẹt giao diện và không có cơ chế restart phù hợp", should_skip_account=True)


def handle_account_auth_failure(
    runtime: Any,
    accounts: Any,
    account_id: str,
    device_serial: str,
    reason: str,
    *,
    input_ctrl: Any | None = None,
    package: str = "com.daichien.mobile",
) -> RecoveryAction:
    """Xử lý đặc biệt khi lỗi xác thực / sai mật khẩu / kẹt ô đăng nhập: Đánh dấu và bỏ qua ngay."""
    LOGGER.error("PHỤC HỒI LỖI | Tài khoản %s lỗi xác thực: %s -> Bỏ qua và chuyển tài khoản kế tiếp.", account_id, reason)
    try:
        runtime.mark_error(account_id, device_serial, reason)
    except Exception as err:
        LOGGER.warning("Không thể mark_error vào runtime: %s", err)

    try:
        accounts.skip_current(account_id)
    except Exception as err:
        LOGGER.warning("Không thể skip_current trong accounts: %s", err)

    # Đảm bảo làm sạch form đăng nhập hoặc restart game để sẵn sàng cho acc tiếp theo
    if input_ctrl:
        try:
            input_ctrl.shell("am", "force-stop", package)
            sleep(1.0)
            input_ctrl.shell("monkey", "-p", package, "1")
            sleep(2.0)
        except Exception as r_err:
            LOGGER.warning("Lỗi làm mới app sau lỗi auth: %s", r_err)

    return RecoveryAction(success=True, message="Đã đánh dấu lỗi auth và skip sang tài khoản kế tiếp", should_skip_account=True)


def handle_task_failure(
    runtime: Any,
    account_id: str,
    task_name: str,
    reason: str,
    *,
    scene_classifier: Any | None = None,
    screen_fn: Callable[[], Any] | None = None,
    input_ctrl: Any | None = None,
) -> RecoveryAction:
    """Xử lý đặc biệt khi một task đơn lẻ bị lỗi: ghi nhận lỗi task và cố gắng đưa bot về HOME để chạy task tiếp theo."""
    LOGGER.error("PHỤC HỒI LỖI | Task %s của tài khoản %s gặp lỗi: %s -> Đang đưa về HOME để chạy tiếp...", task_name, account_id, reason)
    try:
        runtime.mark_task_error(account_id, task_name, f"home target error: {reason}")
    except Exception as err:
        LOGGER.warning("Không thể mark_task_error vào runtime: %s", err)

    if scene_classifier and screen_fn and input_ctrl:
        try:
            scene_classifier.ensure_home(screen_fn, input_ctrl, max_steps=4)
        except Exception as err:
            LOGGER.warning("Lỗi đưa về HOME sau task failure: %s", err)

    return RecoveryAction(success=True, message=f"Đã ghi nhận lỗi task {task_name} và dọn đường về HOME", should_retry=False)
