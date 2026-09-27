from __future__ import annotations
from app.actions.dc3q.common.common import ActionContext, Dc3qAction

class TargetAction(Dc3qAction):
    name="target"
    def execute(self):
        raise NotImplementedError("TargetAction là interface; chưa nối workflow")
