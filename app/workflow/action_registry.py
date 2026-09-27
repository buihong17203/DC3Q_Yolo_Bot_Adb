from __future__ import annotations
from typing import Callable, Any

class ActionRegistry:
    def __init__(self): self._actions: dict[str, Callable[..., Any]] = {}
    def register(self, name: str, fn: Callable[..., Any]):
        if not name: raise ValueError("action name rỗng")
        self._actions[name]=fn; return fn
    def get(self, name: str):
        if name not in self._actions: raise KeyError(f"Action chưa đăng ký: {name}")
        return self._actions[name]
    def names(self): return sorted(self._actions)
