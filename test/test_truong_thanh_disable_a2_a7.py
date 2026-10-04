from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def test_only_a1_runs_when_a2_through_a7_are_temporarily_disabled():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        skipped_subflows=[
            "A2_tuong-an", "A3_chua-cong", "A4_ve-tuong",
            "A5_trai-ngua", "A6_than-binh", "A7_chien-hon",
        ],
        flows=[
            SimpleNamespace(name="A4_ve-tuong"),
            SimpleNamespace(name="A5_trai-ngua"),
            SimpleNamespace(name="A6_than-binh"),
            SimpleNamespace(name="A7_chien-hon"),
        ],
    )
    calls = []
    runner._run_a1 = lambda: calls.append("A1")
    runner._run_a2 = lambda: calls.append("A2")
    runner._run_a3 = lambda: calls.append("A3")
    runner._open_home_entry = lambda: calls.append("open")
    runner._run_a5 = lambda flow: calls.append(flow.name)
    runner._run_flow = lambda flow: calls.append(flow.name)
    runner.recover_home = lambda: calls.append("home") or True

    assert runner.run() is True
    assert calls == ["A1", "home"]
