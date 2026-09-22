from __future__ import annotations

from pathlib import Path

import yaml

from app.automation import ActionRegistry
from app.core.game_day import DailyRuntimeStore


def test_resume_actions_are_registered() -> None:
    registry = ActionRegistry()
    assert registry.has("prepare_account_session")
    assert registry.has("set_workflow_step")
    assert registry.has("complete_account_flow")


def test_workflow_derives_first_unfinished_stage() -> None:
    row = {
        "tasks": {
            "phuc_loi": {"diem_danh": "NOT_STARTED", "status": "NOT_STARTED"},
            "tam_quoc_lenh": {"status": "NOT_STARTED"},
        }
    }
    # Điểm danh không phải workflow step độc lập; TQL luôn đứng trước Phúc lợi.
    assert ActionRegistry._derive_next_workflow_step(row) == "TAM_QUOC_LENH"

    row["tasks"]["tam_quoc_lenh"]["status"] = "DONE"
    assert ActionRegistry._derive_next_workflow_step(row) == "PHUC_LOI"

    # Phúc lợi tự resume các task con (bao gồm Điểm danh) dựa vào runtime nội bộ.
    row["tasks"]["phuc_loi"]["diem_danh"] = "CLAIMED"
    assert ActionRegistry._derive_next_workflow_step(row) == "PHUC_LOI"

    row["tasks"]["phuc_loi"]["status"] = "DONE_FOR_NOW"
    assert ActionRegistry._derive_next_workflow_step(row) == "LOGOUT"


def test_default_runtime_has_persistent_workflow() -> None:
    defaults = DailyRuntimeStore._default_tasks()
    assert defaults["workflow"]["current_step"] == "LOGIN"
    assert defaults["workflow"]["session_state"] == "LOGGED_OUT"
    assert defaults["workflow"]["resume_count"] == 0


def test_manager_order_is_login_tql_welfare_logout() -> None:
    root = Path(__file__).resolve().parents[1]
    manager = yaml.safe_load((root / "scripts/multi_account_manager.yaml").read_text(encoding="utf-8"))
    children = [step["run_scenario"] for step in manager["steps"] if "run_scenario" in step]
    assert children == [
        "tasks/tam_quoc_lenh.yaml",
        "tasks/phuc_loi.yaml",
        "auth/logout.yaml",
    ]
    assert manager["steps"][0]["action"] == "prepare_account_session"
