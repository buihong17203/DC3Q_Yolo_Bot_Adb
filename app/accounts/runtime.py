from __future__ import annotations

import csv
import shutil
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from threading import RLock


class AccountRuntime:
    """Durable per-account runtime journal with a daily 23:00 rollover."""

    TASK_FIELDS = [
        "Tam_Quoc_Lenh",
        "Hoat_Dong",
        "Cua_Hang",
        "Quan_Doan",
        "Khong_Gian_Ca_Nhan",
        "Xa_Giao",
        "TT_A1_Bao_Vat",
        "TT_A2_Tuong_An",
        "TT_A3_Chua_Cong",
        "TT_A4_Ve_Tuong",
        "TT_A5_Trai_Ngua",
        "TT_A6_Than_Binh",
        "TT_A7_Chien_Hon",
        "Vo_Tuong",
        "Quan_Su",
        "Nhiem_Vu",
    ]
    FIELDS = [
        "id", "status", "attempts", "assigned_device", *TASK_FIELDS,
        "last_run", "tasks", "game_day", "reset_hour",
    ]

    TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

    def __init__(self, root: str | Path, *, reset_hour: int = 23,
                 archive_dir: str | Path = "docs/docs_days_runtime"):
        self.root = Path(root)
        self.accounts_file = self.root / "data/accounts/accounts.csv"
        self.runtime_file = self.root / "data/accounts/account_runtime.csv"
        archive_path = Path(archive_dir)
        self.archive_dir = archive_path if archive_path.is_absolute() else self.root / archive_path
        self.reset_hour = reset_hour
        self._lock = RLock()
        self._ensure_current()

    @staticmethod
    def game_day(now: datetime, reset_hour: int) -> date:
        return (now.date() - timedelta(days=1)) if now.hour < reset_hour else now.date()

    def _ensure_current(self) -> None:
        self.runtime_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.runtime_file.exists() or self.runtime_file.stat().st_size == 0:
            self._reset_from_accounts(self.game_day(datetime.now(self.TIMEZONE), self.reset_hour))
            return
        with self.runtime_file.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if reader.fieldnames and "error_message" in reader.fieldnames:
            for row in rows:
                error = (row.get("error_message") or "").strip()
                if error:
                    self._append_error(
                        row.get("id", ""), "MIGRATION", error,
                        timestamp=row.get("last_run") or None,
                    )
        if reader.fieldnames != self.FIELDS:
            self._write(rows)

    def maybe_rollover(self, now: datetime | None = None) -> None:
        now = now or datetime.now(self.TIMEZONE)
        with self._lock:
            current_day = self._read_game_day()
            expected_day = self.game_day(now, self.reset_hour)
            if current_day == expected_day:
                return
            # Only archive a completed runtime once. If the file is from a prior
            # game day, archive it under that day and create the new day's state.
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            stamp = current_day.isoformat() if current_day else "unknown"
            target = self.archive_dir / f"account_runtime_{stamp}.csv"
            if self.runtime_file.exists():
                if target.exists():
                    target = self.archive_dir / f"account_runtime_{stamp}_{datetime.now(self.TIMEZONE):%H%M%S}.csv"
                shutil.move(str(self.runtime_file), str(target))
            self._reset_from_accounts(expected_day)

    def _read_game_day(self) -> date | None:
        if not self.runtime_file.exists():
            return None
        with self.runtime_file.open("r", encoding="utf-8-sig", newline="") as f:
            row = next(csv.DictReader(f), None)
        if not row or not row.get("game_day"):
            return None
        try:
            return date.fromisoformat(row["game_day"])
        except ValueError:
            return None

    @classmethod
    def _normalize_task(cls, task: str | None) -> str | None:
        if not task:
            return None
        if task in cls.TASK_FIELDS:
            return task
        clean_task = task.replace("-", "_").lower()
        for field in cls.TASK_FIELDS:
            if field.replace("-", "_").lower() == clean_task:
                return field
        return None

    def _reset_from_accounts(self, game_day: date) -> None:
        rows: list[dict[str, str]] = []
        source: list[dict[str, str]] = []
        if self.accounts_file.exists():
            with self.accounts_file.open("r", encoding="utf-8-sig", newline="") as f:
                source = [r for r in csv.DictReader(f) if r.get("id")]
        for row in source:
            item = {
                "id": row.get("id", ""),
                "status": "READY",
                "attempts": "0",
                "assigned_device": "",
                "last_run": "",
                "tasks": "{}",
                "game_day": game_day.isoformat(),
                "reset_hour": str(self.reset_hour),
            }
            for field in self.TASK_FIELDS:
                item[field] = "READY"
            rows.append(item)
        self._write(rows)

    def _write(self, rows: list[dict[str, str]]) -> None:
        self.runtime_file.parent.mkdir(parents=True, exist_ok=True)
        with self.runtime_file.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows({field: row.get(field, "READY" if field in self.TASK_FIELDS else "") for field in self.FIELDS} for row in rows)

    def _append_error(self, account_id: str, task: str, error: str,
                      *, timestamp: str | None = None, kind: str = "TASK") -> None:
        now = datetime.now(self.TIMEZONE)
        stamp = timestamp or now.isoformat(timespec="seconds")
        day = stamp[:10] if len(stamp) >= 10 else now.date().isoformat()
        path = self.runtime_file.parent / f"error_message_{day}.txt"
        message = " ".join(str(error).splitlines()).strip()
        line = f"{stamp} | account={account_id} | task={task or '-'} | type={kind} | {message}\n"
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)


    def statuses(self) -> dict[str, dict[str, str]]:
        self.maybe_rollover()
        if not self.runtime_file.exists():
            return {}
        with self.runtime_file.open("r", encoding="utf-8-sig", newline="") as f:
            return {row.get("id", ""): row for row in csv.DictReader(f) if row.get("id")}

    def update(self, account_id: str, **changes: str | int | None) -> None:
        with self._lock:
            self.maybe_rollover(datetime.now(self.TIMEZONE))
            with self.runtime_file.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            found = False
            for row in rows:
                if row.get("id") == account_id:
                    for key, value in changes.items():
                        if key not in self.FIELDS:
                            raise KeyError(key)
                        row[key] = "" if value is None else str(value)
                    found = True
                    break
            if not found:
                raise KeyError(f"Không tìm thấy runtime account: {account_id}")
            self._write(rows)

    def mark_login_attempt(self, account_id: str, device: str) -> None:
        with self._lock:
            self.maybe_rollover(datetime.now(self.TIMEZONE))
            with self.runtime_file.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                if row.get("id") == account_id:
                    row["status"] = "LOGINNING"
                    row["attempts"] = str(int(row.get("attempts") or 0) + 1)
                    row["assigned_device"] = device
                    row["last_run"] = datetime.now(self.TIMEZONE).isoformat(timespec="seconds")
                    self._write(rows)
                    return
            raise KeyError(account_id)

    def mark_logged_in(self, account_id: str, device: str) -> None:
        self.update(account_id, status="LOGGED_IN", assigned_device=device,
                     last_run=datetime.now(self.TIMEZONE).isoformat(timespec="seconds"))

    def mark_current_task(self, account_id: str, task: str) -> None:
        task_col = self._normalize_task(task)
        if not task_col:
            return
        self.update(account_id, **{
            task_col: "RUNNING",
            "last_run": datetime.now(self.TIMEZONE).isoformat(timespec="seconds"),
        })

    def mark_task_done(self, account_id: str, task: str) -> None:
        task_col = self._normalize_task(task)
        if not task_col:
            return
        self.update(account_id, **{
            task_col: "DONE",
            "last_run": datetime.now(self.TIMEZONE).isoformat(timespec="seconds"),
        })

    def mark_task_error(self, account_id: str, task: str, error: str) -> None:
        """Record a recoverable module error without stopping the account flow."""
        task_col = self._normalize_task(task)
        if not task_col:
            return
        now = datetime.now(self.TIMEZONE).isoformat(timespec="seconds")
        self._append_error(account_id, task_col, error, timestamp=now)
        self.update(account_id, **{
            task_col: "ERROR",
            "last_run": now,
        })

    def mark_logged_out(self, account_id: str) -> None:
        self.update(account_id, status="DONE", assigned_device="",
                     last_run=datetime.now(self.TIMEZONE).isoformat(timespec="seconds"))

    def mark_error(self, account_id: str, device: str, error: str, *, task: str | None = None) -> None:
        now = datetime.now(self.TIMEZONE).isoformat(timespec="seconds")
        task_col = self._normalize_task(task)
        self._append_error(account_id, task_col or task or "ACCOUNT", error,
                           timestamp=now, kind="ACCOUNT")
        changes = {
            "status": "ERROR", "assigned_device": device, "last_run": now,
        }
        if task_col:
            changes[task_col] = "ERROR"
        self.update(account_id, **changes)
