from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def test_each_truong_thanh_subflow_reopens_route_then_returns_home():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(flows=[SimpleNamespace(name="A4"), SimpleNamespace(name="A5")])
    calls = []
    runner._run_a1 = lambda: None
    runner._run_a2 = lambda: None
    runner._run_a3 = lambda: None
    runner._open_home_entry = lambda: calls.append("open")
    runner._run_flow = lambda flow: calls.append(flow.name)
    runner.recover_home = lambda: calls.append("home") or True

    assert runner.run() is True
    assert calls == ["home", "home", "home", "open", "A4", "home", "open", "A5", "home"]


def test_missing_optional_subflow_recovers_home_and_continues():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(flows=[SimpleNamespace(name="A4"), SimpleNamespace(name="A5")])
    calls = []
    runner._run_a1 = lambda: None
    runner._run_a2 = lambda: None
    runner._run_a3 = lambda: None
    runner._open_home_entry = lambda: calls.append("open")

    def run_flow(flow):
        calls.append(flow.name)
        if flow.name == "A4":
            raise RuntimeError("A4 unavailable")

    runner._run_flow = run_flow
    runner.recover_home = lambda: calls.append("home") or True

    assert runner.run() is True
    assert calls == ["home", "home", "home", "open", "A4", "home", "open", "A5", "home"]
    assert runner.soft_errors == ["A4 unavailable"]


def test_non_runtime_subflow_error_recovers_home_and_continues():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(flows=[SimpleNamespace(name="A4"), SimpleNamespace(name="A5")])
    calls = []
    runner._run_a1 = lambda: None
    runner._run_a2 = lambda: None
    runner._run_a3 = lambda: None
    runner._open_home_entry = lambda: calls.append("open")

    def run_flow(flow):
        calls.append(flow.name)
        if flow.name == "A4":
            raise ValueError("OCR A4 hỏng")

    runner._run_flow = run_flow
    runner.recover_home = lambda: calls.append("home") or True

    assert runner.run() is True
    assert "A5" in calls
    assert runner.soft_errors == ["OCR A4 hỏng"]
