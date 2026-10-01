from importlib import import_module
from types import SimpleNamespace

import pytest


HomeAction = import_module("app.actions.dc3q.stars.01-4_home").HomeAction


class FailedTarget:
    runtime_task = "QUAN_DOAN"

    def __init__(self, recovered=True):
        self.recovered = recovered
        self.runs = 0

    def run(self):
        self.runs += 1
        raise RuntimeError("lỗi Quân đoàn")

    def recover_home(self):
        return self.recovered


class NextTarget:
    runtime_task = "KHONG_GIAN_CA_NHAN"

    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1
        return True


def action(targets):
    return HomeAction(
        SimpleNamespace(), SimpleNamespace(),
        SimpleNamespace(home_targets=targets, home_events=[], logged_in_confirmations=1),
    )


def test_failed_target_recovers_marks_error_and_advances_to_next_target():
    failed, following = FailedTarget(), NextTarget()
    value = action([failed, following])

    assert value.process(object(), logged_in=True) is False
    assert value.current_task == "KHONG_GIAN_CA_NHAN"
    assert value.last_task_error == "lỗi Quân đoàn"

    assert value.process(object(), logged_in=True) is False
    assert following.runs == 1
    assert value.target_done is True


def test_failed_target_still_stops_when_home_recovery_fails():
    value = action([FailedTarget(recovered=False)])

    with pytest.raises(RuntimeError, match="lỗi Quân đoàn"):
        value.process(object(), logged_in=True)
