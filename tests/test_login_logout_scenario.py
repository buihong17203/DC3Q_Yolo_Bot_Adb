from pathlib import Path

import cv2
import numpy as np

from app.automation import AutomationEngine
from app.core.config import settings


def _load(name: str) -> dict:
    return AutomationEngine.load_scenario(settings.automation.scripts_dir / name)


def test_login_logout_are_separate_and_manager_calls_both() -> None:
    login = _load("auth/login.yaml")
    logout = _load("auth/logout.yaml")
    manager = _load("multi_account_manager.yaml")

    assert "${account.username}" in str(login)
    assert "${account.password}" in str(login)
    assert "${account.password}" not in str(logout)
    assert [step["run_scenario"] for step in manager["steps"] if "run_scenario" in step] == [
        "auth/login.yaml",
        "tasks/tam_quoc_lenh.yaml",
        "auth/logout.yaml",
    ]


def test_auth_scenario_templates_exist_and_decode() -> None:
    for scenario_name in ("auth/login.yaml", "auth/logout.yaml"):
        for step in _load(scenario_name)["steps"]:
            if not isinstance(step, dict):
                continue
            template = step.get("template")
            if template:
                template_path = settings.vision.templates_dir / Path(template)
                assert template_path.is_file(), template
                encoded = np.fromfile(template_path, dtype=np.uint8)
                assert cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED) is not None, template


def test_manager_executes_child_scenarios_in_same_context() -> None:
    class Device:
        serial = "fake"

    class Vision:
        pass

    engine = AutomationEngine(Device(), Vision())
    context = engine.create_context(variables={"account": {"id": "1"}})
    calls: list[str] = []

    def fake_run_steps(child_context, steps):
        calls.append(steps[0]["action"])
        assert child_context is context
        return True

    engine.run_steps = fake_run_steps
    engine.load_scenario = lambda path: {"steps": [{"action": "fixture_action"}]}
    assert engine._run_control_step(context, {"run_scenario": "fixture.yaml"}) is True
    assert calls == ["fixture_action"]