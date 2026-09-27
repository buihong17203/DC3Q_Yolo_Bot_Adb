from __future__ import annotations
from dataclasses import dataclass

@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""

class Guard:
    def __init__(self, max_failures: int = 3): self.max_failures=max_failures; self.failures=0
    def success(self): self.failures=0
    def failure(self, reason: str = "") -> GuardResult:
        self.failures += 1
        return GuardResult(self.failures < self.max_failures, reason)
    def check(self) -> GuardResult:
        return GuardResult(self.failures < self.max_failures, "failure limit reached" if self.failures >= self.max_failures else "")

class RecoveryManager:
    """Recovery policy container; no automatic recovery is triggered by this patch."""
    def __init__(self, guard: Guard | None = None): self.guard=guard or Guard()
    def record_failure(self, reason=""): return self.guard.failure(reason)
    def record_success(self): self.guard.success()
    def can_continue(self): return self.guard.check()
