from pathlib import Path
from types import SimpleNamespace

from app.accounts.manager import AccountManager
from app.actions.dc3q.stars import HomeAction


class Target:
    def __init__(self, task):
        self.runtime_task = task
        self.runs = 0

    def run(self):
        self.runs += 1
        return True


def test_all_accounts_with_any_unfinished_active_task_are_selected(tmp_path: Path):
    path = tmp_path / "accounts.csv"
    path.write_text(
        "id,username,password\nacc_001,u1,p1\nacc_002,u2,p2\nacc_003,u3,p3\n",
        encoding="utf-8",
    )
    runtime = {
        "acc_001": {"status": "DONE", "Hoat_Dong": "DONE", "Cua_Hang": "ERROR"},
        "acc_002": {"status": "ERROR", "Hoat_Dong": "DONE", "Cua_Hang": "DONE"},
        "acc_003": {"status": "DONE", "Hoat_Dong": "READY", "Cua_Hang": "DONE"},
    }

    selected = AccountManager(path).load(
        runtime, active_tasks=["Hoat_Dong", "Cua_Hang"],
    )

    assert [account.id for account in selected] == ["acc_001", "acc_003"]


def test_home_action_skips_done_tasks_and_runs_each_unfinished_task_once():
    done, error, ready = Target("DONE_TASK"), Target("ERROR_TASK"), Target("READY_TASK")
    config = SimpleNamespace(
        home_targets=[done, error, ready], home_events=[], logged_in_confirmations=1,
    )
    action = HomeAction(SimpleNamespace(), SimpleNamespace(), config)
    action.set_completed_tasks({"DONE_TASK"})

    assert action.current_task == "ERROR_TASK"
    assert action.process(object(), logged_in=True) is False
    assert action.current_task == "READY_TASK"
    assert action.process(object(), logged_in=True) is False
    assert action.process(object(), logged_in=True) is True
    assert (done.runs, error.runs, ready.runs) == (0, 1, 1)


def test_truong_thanh_runtime_steps_expose_separate_leaf_tasks():
    from importlib import import_module
    module = import_module("app.actions.dc3q.targets.07_truong-thanh")
    runner = SimpleNamespace(
        _run_a1=lambda: None, _run_a2=lambda: None, _run_a6=lambda: None,
        _run_a7=lambda: None, recover_home=lambda: True,
    )

    a1 = module.TruongThanhRuntimeStep(runner, "TT_A1_BAO_VAT", "_run_a1")
    a2 = module.TruongThanhRuntimeStep(runner, "TT_A2_TUONG_AN", "_run_a2")
    a6 = module.TruongThanhRuntimeStep(runner, "TT_A6_THAN_BINH", "_run_a6")
    a7 = module.TruongThanhRuntimeStep(runner, "TT_A7_CHIEN_HON", "_run_a7")

    assert a1.runtime_task == "TT_A1_BAO_VAT"
    assert a2.runtime_task == "TT_A2_TUONG_AN"
    assert a6.runtime_task == "TT_A6_THAN_BINH"
    assert a7.runtime_task == "TT_A7_CHIEN_HON"
    assert a1.run() is True
    assert a2.run() is True
    assert a6.run() is True
    assert a7.run() is True
