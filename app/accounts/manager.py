from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from .reader import read_accounts


@dataclass
class Account:
    id: str
    data: dict[str, str]

    @property
    def username(self) -> str:
        return self.data.get("username", self.data.get("user", ""))

    @property
    def password(self) -> str:
        return self.data.get("password", self.data.get("pass", ""))


class AccountManager:
    """Account queue. An account is consumed only after login is confirmed."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._accounts: list[Account] = []
        self._cursor = 0
        self._claimed: dict[str, Account] = {}
        self._limit: int | None = None
        self._active_tasks: list[str] | None = None
        self._lock = Lock()

    def load(self, runtime_status: dict[str, dict[str, str]] | None = None,
             *, limit: int | None = None,
             active_tasks: list[str] | None = None) -> list[Account]:
        self._limit = limit
        self._active_tasks = active_tasks
        rows = read_accounts(self.path)
        if limit is not None:
            rows = rows[:max(0, limit)]
        runtime_status = runtime_status or {}
        # Cap the requested row range before filtering completed runtime rows.
        def unfinished(account_id: str) -> bool:
            state = runtime_status.get(account_id, {})
            if active_tasks is not None:
                return any(state.get(task, "READY") != "DONE" for task in active_tasks)
            return state.get("status") not in {"DONE", "ERROR"}

        self._accounts = [
            Account(r.get("id", str(i)), r)
            for i, r in enumerate(rows, start=1)
            if unfinished(r.get("id", str(i)))
        ]
        self._cursor = 0
        self._claimed.clear()
        return list(self._accounts)

    def reload(self, runtime_status: dict[str, dict[str, str]] | None = None) -> list[Account]:
        return self.load(runtime_status, limit=self._limit, active_tasks=self._active_tasks)

    def get(self, account_id: str) -> Account | None:
        return next((a for a in self._accounts if a.id == account_id), None)

    def all(self) -> list[Account]:
        return list(self._accounts)

    def peek_next(self) -> Account | None:
        if self._cursor >= len(self._accounts):
            return None
        return self._accounts[self._cursor]

    def claim_next(self) -> Account | None:
        """Atomically reserve one account for one device worker."""
        with self._lock:
            if self._cursor >= len(self._accounts):
                return None
            account = self._accounts[self._cursor]
            self._cursor += 1
            self._claimed[account.id] = account
            return account

    def commit_logged_in(self, account_id: str) -> Account:
        with self._lock:
            account = self._claimed.pop(account_id, None)
            if account is None:
                raise ValueError("Account chưa được worker claim hoặc đã commit")
            return account

    def skip_current(self, account_id: str) -> Account:
        """Consume one rejected account without treating it as logged in."""
        with self._lock:
            account = self._claimed.pop(account_id, None)
            if account is None:
                raise ValueError("Account chưa được worker claim hoặc đã bỏ qua")
            return account

    def reset(self) -> None:
        with self._lock:
            self._cursor = 0
            self._claimed.clear()
