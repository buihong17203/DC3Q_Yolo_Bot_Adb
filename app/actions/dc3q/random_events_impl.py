from __future__ import annotations
from app.actions.dc3q.common.common import Dc3qAction

class RandomEventAction(Dc3qAction):
    name="random_event"
    def execute(self):
        raise NotImplementedError("Random event flow chưa được nối trong bản patch")
