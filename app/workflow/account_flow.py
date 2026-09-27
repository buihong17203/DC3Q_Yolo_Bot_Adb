from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class WorkflowContext:
    serial: str
    account_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

@dataclass
class WorkflowPlan:
    name: str
    steps: list[dict[str, Any]] = field(default_factory=list)

class AccountFlow:
    """Plan representation only; intentionally does not execute steps in this patch."""
    def build_plan(self, workflow: dict[str, Any]) -> WorkflowPlan:
        name=str(workflow.get("name", "unnamed"))
        steps=workflow.get("steps", [])
        if not isinstance(steps, list): raise ValueError("workflow.steps phải là list")
        return WorkflowPlan(name, steps)
