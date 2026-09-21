from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable

from app.core.logger import get_logger

from .repository import Account, AccountRepository, AccountStatus

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AccountStats:
    total: int
    ready: int
    in_use: int
    done: int
    failed: int
    disabled: int


class AccountManager:
    """Thread-safe allocator that guarantees one account per worker at a time."""

    def __init__(
        self,
        repository: AccountRepository,
        *,
        persist_status: bool = True,
        retry_failed: bool = True,
        max_attempts: int = 3,
        runtime_store: Any | None = None,
    ) -> None:
        self.repository = repository
        self.persist_status = bool(persist_status)
        self.retry_failed = bool(retry_failed)
        self.max_attempts = max(1, int(max_attempts))
        self.runtime_store = runtime_store
        self._lock = threading.RLock()
        self._accounts: list[Account] = repository.load()
        if self.runtime_store is not None:
            self.runtime_store.initialize(self._accounts)

        # IN_USE from a previous crashed process is a stale lease.
        changed = False
        for account in self._accounts:
            if account.status == AccountStatus.IN_USE:
                account.status = AccountStatus.READY
                account.assigned_worker = None
                changed = True
        if changed:
            self._persist()

    def _persist(self) -> None:
        if self.persist_status:
            if self.runtime_store is not None:
                self.runtime_store.save(self._accounts)
            else:
                self.repository.save(self._accounts)

    def rollover(self) -> bool:
        """Archive the old game day, reset the queue, and start again at acc_001."""
        with self._lock:
            if self.runtime_store is None:
                return False
            changed = self.runtime_store.rollover(self._accounts)
            if changed:
                self._persist()
            return changed

    def all(self) -> list[Account]:
        with self._lock:
            return list(self._accounts)

    def get(self, account_id: str) -> Account | None:
        with self._lock:
            return next((account for account in self._accounts if account.id == str(account_id)), None)

    def claim_next(self, worker_id: str) -> Account | None:
        with self._lock:
            for account in self._accounts:
                if account.status != AccountStatus.READY:
                    continue
                account.status = AccountStatus.IN_USE
                account.assigned_worker = worker_id
                account.last_error = None
                self._persist()
                logger.info("[%s] Nhận account-%s", worker_id, account.id)
                return account
            return None

    def mark_done(self, account: Account, worker_id: str | None = None) -> None:
        with self._lock:
            self._validate_owner(account, worker_id)
            account.status = AccountStatus.DONE
            account.assigned_worker = None
            account.last_error = None
            self._persist()

    def mark_failed(
        self,
        account: Account,
        error: str | Exception | None = None,
        *,
        worker_id: str | None = None,
        allow_retry: bool | None = None,
    ) -> None:
        with self._lock:
            self._validate_owner(account, worker_id)
            account.attempts += 1
            account.last_error = str(error) if error is not None else None
            account.assigned_worker = None

            retry = self.retry_failed if allow_retry is None else bool(allow_retry)
            if retry and account.attempts < self.max_attempts:
                account.status = AccountStatus.READY
            else:
                account.status = AccountStatus.FAILED
            self._persist()

    def release(self, account: Account, *, worker_id: str | None = None) -> None:
        with self._lock:
            self._validate_owner(account, worker_id)
            if account.status == AccountStatus.IN_USE:
                account.status = AccountStatus.READY
            account.assigned_worker = None
            self._persist()

    def disable(self, account: Account) -> None:
        with self._lock:
            account.status = AccountStatus.DISABLED
            account.assigned_worker = None
            self._persist()

    def release_all_in_use(self, worker_ids: Iterable[str] | None = None) -> int:
        """Return active leases to READY during application shutdown.

        When ``worker_ids`` is provided, only leases owned by those workers are
        released. This prevents Ctrl+C from leaving accounts stuck at IN_USE.
        """
        with self._lock:
            allowed = {str(value) for value in worker_ids} if worker_ids is not None else None
            count = 0
            for account in self._accounts:
                if account.status != AccountStatus.IN_USE:
                    continue
                if allowed is not None and account.assigned_worker not in allowed:
                    continue
                account.status = AccountStatus.READY
                account.assigned_worker = None
                count += 1
            if count:
                self._persist()
            return count

    def reset_failed(self) -> int:
        with self._lock:
            count = 0
            for account in self._accounts:
                if account.status == AccountStatus.FAILED:
                    account.status = AccountStatus.READY
                    account.last_error = None
                    count += 1
            if count:
                self._persist()
            return count

    def has_available(self) -> bool:
        with self._lock:
            return any(account.status == AccountStatus.READY for account in self._accounts)

    @property
    def stats(self) -> AccountStats:
        with self._lock:
            counts = {status: 0 for status in AccountStatus}
            for account in self._accounts:
                counts[account.status] += 1
            return AccountStats(
                total=len(self._accounts),
                ready=counts[AccountStatus.READY],
                in_use=counts[AccountStatus.IN_USE],
                done=counts[AccountStatus.DONE],
                failed=counts[AccountStatus.FAILED],
                disabled=counts[AccountStatus.DISABLED],
            )

    @staticmethod
    def _validate_owner(account: Account, worker_id: str | None) -> None:
        if worker_id is None or account.assigned_worker in (None, worker_id):
            return
        raise RuntimeError(
            f"Account {account.id} is leased by {account.assigned_worker}, not {worker_id}"
        )
