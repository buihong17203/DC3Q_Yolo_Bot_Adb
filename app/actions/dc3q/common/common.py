from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class ActionContext:
    serial: str
    account_id: str | None = None
    data: dict[str, Any] | None = None

class Dc3qAction:
    name="base"
    def __init__(self, context: ActionContext): self.context=context
    def validate(self) -> None: pass
    def execute(self) -> Any:
        raise NotImplementedError("Action chưa có implementation/flow")
