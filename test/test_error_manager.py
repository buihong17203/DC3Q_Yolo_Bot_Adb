from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.errors import (
    ErrorManager,
    ErrorCategory,
    ErrorSeverity,
    BotError,
    AdbLostConnectionError,
    GameCrashError,
    GameAnrError,
    AccountAuthError,
    UiStuckError,
    TaskExecutionError,
)
from app.adb.client import AdbError


def test_classify_exceptions():
    mgr = ErrorManager()

    # 1. AdbError
    e1 = mgr.classify_exception(AdbError("device offline"), device_serial="127.0.0.1:5555")
    assert isinstance(e1, AdbLostConnectionError)
    assert e1.category == ErrorCategory.ADB_CONNECTION
    assert e1.severity == ErrorSeverity.CRITICAL
    assert e1.device_serial == "127.0.0.1:5555"

    # 2. ANR
    e2 = mgr.classify_exception(RuntimeError("Ứng dụng com.daichien.mobile không phản hồi (ANR)"))
    assert isinstance(e2, GameAnrError)
    assert e2.category == ErrorCategory.APP_CRASH_ANR

    # 3. Auth failure
    e3 = mgr.classify_exception(ValueError("Máy chủ từ chối tài khoản hoặc mật khẩu"), account_id="acc_001")
    assert isinstance(e3, AccountAuthError)
    assert e3.category == ErrorCategory.ACCOUNT_AUTH
    assert e3.invalid_credentials is True
    assert e3.account_id == "acc_001"

    # 4. UI stuck
    e4 = mgr.classify_exception(RuntimeError("TT_A6_THAN_BINH: không recover được HOME"))
    assert isinstance(e4, UiStuckError)
    assert e4.category == ErrorCategory.UI_STUCK_POPUP

    # 5. Task failure with task_name
    e5 = mgr.classify_exception(KeyError("missing item"), task_name="Tam_Quoc_Lenh", account_id="acc_002")
    assert isinstance(e5, TaskExecutionError)
    assert e5.category == ErrorCategory.TASK_FAILURE
    assert e5.task_name == "Tam_Quoc_Lenh"


def test_log_error_writes_to_file():
    with tempfile.TemporaryDirectory() as tmp_dir:
        err_dir = Path(tmp_dir) / "error"
        mgr = ErrorManager(error_dir=err_dir)

        err = AccountAuthError("Sai mật khẩu đăng nhập", account_id="acc_005")
        mgr.log_error(err)

        files = list(err_dir.glob("error_message_*.txt"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "account=acc_005" in content
        assert "type=ACCOUNT" in content
        assert "Sai mật khẩu đăng nhập" in content


def test_handle_account_auth_recovery():
    mgr = ErrorManager()
    mock_runtime = MagicMock()
    mock_accounts = MagicMock()
    mock_input = MagicMock()

    ctx = {
        "account_id": "acc_001",
        "device_serial": "emulator-5554",
        "runtime": mock_runtime,
        "accounts": mock_accounts,
        "input": mock_input,
    }

    action = mgr.handle(
        AccountAuthError("Máy chủ từ chối tài khoản", account_id="acc_001"),
        context=ctx,
    )

    assert action.should_skip_account is True
    mock_runtime.mark_error.assert_called_once_with("acc_001", "emulator-5554", "Máy chủ từ chối tài khoản")
    mock_accounts.skip_current.assert_called_once_with("acc_001")
    mock_input.shell.assert_any_call("am", "force-stop", "com.daichien.mobile")


def test_handle_app_crash_recovery():
    mgr = ErrorManager()
    mock_input = MagicMock()

    ctx = {"input": mock_input}
    action = mgr.handle(GameCrashError(), context=ctx)

    assert action.success is True
    assert action.should_retry is True
    mock_input.shell.assert_any_call("am", "force-stop", "com.daichien.mobile")
    mock_input.shell.assert_any_call("monkey", "-p", "com.daichien.mobile", "1")


def test_handle_ui_stuck_recovery():
    mgr = ErrorManager()
    mock_classifier = MagicMock()
    mock_classifier.ensure_home.return_value = False  # ensure_home fails
    mock_restart = MagicMock()
    mock_input = MagicMock()

    ctx = {
        "scene_classifier": mock_classifier,
        "screen_fn": lambda: None,
        "input": mock_input,
        "restart_fn": mock_restart,
    }

    action = mgr.handle(UiStuckError("Kẹt popup"), context=ctx)

    assert action.success is True
    assert action.should_retry is True
    mock_classifier.ensure_home.assert_called_once()
    mock_restart.assert_called_once()


def test_error_summary_statistics():
    mgr = ErrorManager()
    mgr.classify_exception(AdbError("offline"))
    mgr.log_error(AdbLostConnectionError("offline"))
    mgr.log_error(GameCrashError())
    mgr.log_error(AccountAuthError("bad pass"))

    summary = mgr.get_summary()
    assert summary["total_errors"] == 3
    assert summary["by_category"]["ADB_CONNECTION"] == 1
    assert summary["by_category"]["APP_CRASH_ANR"] == 1
    assert summary["by_category"]["ACCOUNT_AUTH"] == 1
