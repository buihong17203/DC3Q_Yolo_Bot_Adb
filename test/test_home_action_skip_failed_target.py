from importlib import import_module
from types import SimpleNamespace

import pytest


HomeAction = import_module("app.actions.dc3q.stars.01-4_home").HomeAction


class FailedTarget:
    runtime_task = "QUAN_DOAN"

    def __init__(self, recovered=True, error=None):
        self.recovered = recovered
        self.error = error or RuntimeError("lỗi Quân đoàn")
        self.runs = 0

    def run(self):
        self.runs += 1
        raise self.error

    def recover_home(self):
        return self.recovered


class FalseTarget:
    runtime_task = "CUA_HANG"

    def __init__(self):
        self.runs = 0
        self.recoveries = 0

    def run(self):
        self.runs += 1
        return False

    def recover_home(self):
        self.recoveries += 1
        return True


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


def test_non_runtime_target_error_also_recovers_and_advances():
    failed, following = FailedTarget(error=ValueError("OCR hỏng")), NextTarget()
    value = action([failed, following])

    assert value.process(object(), logged_in=True) is False
    assert value.current_task == "KHONG_GIAN_CA_NHAN"
    assert value.last_task_error == "OCR hỏng"


def test_false_target_recovers_and_advances_instead_of_looping_forever():
    failed, following = FalseTarget(), NextTarget()
    value = action([failed, following])

    assert value.process(object(), logged_in=True) is False
    assert failed.runs == 1
    assert failed.recoveries == 1
    assert value.current_task == "KHONG_GIAN_CA_NHAN"
    assert "returned False" in value.last_task_error


def test_failed_target_still_stops_when_home_recovery_fails():
    value = action([FailedTarget(recovered=False)])

    with pytest.raises(RuntimeError, match="lỗi Quân đoàn"):
        value.process(object(), logged_in=True)


def test_home_done_requires_three_consecutive_stable_frames():
    value = HomeAction(
        SimpleNamespace(), SimpleNamespace(),
        SimpleNamespace(home_targets=[], home_events=[], logged_in_confirmations=3),
    )

    assert value.process(object(), logged_in=True) is False
    assert value.process(object(), logged_in=True) is False
    assert value.process(object(), logged_in=False) is False
    assert value.process(object(), logged_in=True) is False
    assert value.process(object(), logged_in=True) is False
    assert value.process(object(), logged_in=True) is True
