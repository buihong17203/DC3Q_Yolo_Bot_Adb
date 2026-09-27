from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
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

    def load(self, runtime_status: dict[str, dict[str, str]] | None = None) -> list[Account]:
        rows = read_accounts(self.path)
        runtime_status = runtime_status or {}
        # Keep accounts.csv as the source of credentials; runtime only decides
        # which accounts are already completed for the current game day.
        self._accounts = [
            Account(r.get("id", str(i)), r)
            for i, r in enumerate(rows, start=1)
            if runtime_status.get(r.get("id", str(i)), {}).get("status") not in {"DONE"}
        ]
        self._cursor = 0
        return list(self._accounts)

    def get(self, account_id: str) -> Account | None:
        return next((a for a in self._accounts if a.id == account_id), None)

    def all(self) -> list[Account]:
        return list(self._accounts)

    def peek_next(self) -> Account | None:
        if self._cursor >= len(self._accounts):
            return None
        return self._accounts[self._cursor]

    def commit_logged_in(self, account_id: str) -> Account:
        account = self.get(account_id)
        if account is None:
            raise KeyError(f"Không tìm thấy account: {account_id}")
        if self._cursor >= len(self._accounts) or self._accounts[self._cursor].id != account_id:
            raise ValueError("Chỉ được commit account đang đứng đầu hàng đợi")
        self._cursor += 1
        return account

    def reset(self) -> None:
        self._cursor = 0
