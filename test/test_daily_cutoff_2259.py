from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.adb.input import AdbInput, DailyCutoff
from app.accounts.manager import AccountManager


TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class Client:
    def shell(self, serial, *args, timeout=None):
        return "ok"


def test_physical_input_stops_at_2259():
    value = AdbInput(Client(), SimpleNamespace(serial="emulator-5554"))
    value.set_cutoff_guard(lambda: True)

    with pytest.raises(DailyCutoff):
        value.tap(10, 20)


def test_recovery_actions_can_run_inside_cutoff_override():
    value = AdbInput(Client(), SimpleNamespace(serial="emulator-5554"))
    value.set_cutoff_guard(lambda: True)

    with value.allow_cutoff_actions():
        assert value.tap(10, 20) == "ok"


def test_cutoff_window_starts_at_2259_and_ends_at_2300():
    from app.workflow.account_login import in_daily_cutoff

    assert not in_daily_cutoff(datetime(2026, 10, 3, 22, 58, 59, tzinfo=TZ), 22, 59)
    assert in_daily_cutoff(datetime(2026, 10, 3, 22, 59, 0, tzinfo=TZ), 22, 59)
    assert not in_daily_cutoff(datetime(2026, 10, 3, 23, 0, 0, tzinfo=TZ), 22, 59)


def test_account_manager_reload_after_rollover_starts_from_acc_001(tmp_path):
    path = tmp_path / "accounts.csv"
    path.write_text("id,username,password\nacc_001,u1,p1\nacc_002,u2,p2\n", encoding="utf-8")
    value = AccountManager(path)
    value.load({"acc_001": {"status": "ERROR"}}, limit=2)
    assert value.claim_next().id == "acc_002"  # ERROR không tự chạy lại cùng ngày.

    value.reload({"acc_001": {"status": "READY"}, "acc_002": {"status": "READY"}})
    assert value.claim_next().id == "acc_001"
