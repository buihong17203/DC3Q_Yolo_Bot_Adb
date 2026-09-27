from __future__ import annotations
from app.actions.dc3q.common.common import Dc3qAction

class HomeAction(Dc3qAction):
    name="stars.home"
    def execute(self):
        raise NotImplementedError("DC3Q home flow chưa được nối trong bản patch")
