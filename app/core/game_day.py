from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


# All workers and task actions share this process-wide lock when updating the
# same account_runtime.json. This prevents Windows replace races (WinError 5).
RUNTIME_FILE_LOCK = threading.RLock()


class GameDayRollover(RuntimeError):
    """Raised before a physical action crosses the 23:00 game-day boundary."""


@dataclass(frozen=True, slots=True)
class GameDayClock:
    reset_hour: int = 23

    def __post_init__(self) -> None:
        if not 0 <= self.reset_hour <= 23:
            raise ValueError("reset_hour must be between 0 and 23")

    def key(self, now: datetime | None = None) -> str:
        current = now or datetime.now().astimezone().replace(tzinfo=None)
        if current.hour >= self.reset_hour:
            current += timedelta(days=1)
        return current.date().isoformat()

    def seconds_until_next_reset(self, now: datetime | None = None) -> float:
        current = now or datetime.now().astimezone().replace(tzinfo=None)
        boundary = current.replace(hour=self.reset_hour, minute=0, second=0, microsecond=0)
        if current >= boundary:
            boundary += timedelta(days=1)
        return max(0.0, (boundary - current).total_seconds())


class DailyRuntimeStore:
    """Credential-free daily account state with immutable per-day archives."""

    def __init__(self, path: str | Path, archive_dir: str | Path, *, clock: GameDayClock | None = None) -> None:
        self.path = Path(path)
        self.archive_dir = Path(archive_dir)
        self.clock = clock or GameDayClock()
        self._lock = threading.RLock()

    @staticmethod
    def _default_tasks() -> dict[str, Any]:
        return {
            "workflow": {
                "status": "NOT_STARTED",
                "current_step": "LOGIN",
                "session_state": "LOGGED_OUT",
                "device_serial": None,
                "last_screen": None,
                "resume_count": 0,
                "last_error": None,
                "updated_at": None,
            },
            "tam_quoc_lenh": {
                "status": "NOT_STARTED",
                "que_boi": "NOT_STARTED",
                "diem_binh": "NOT_STARTED",
                "error": None,
            },
            "phuc_loi": {
                "status": "NOT_STARTED",
                "le_bao_quoc_van": "NOT_STARTED",
                "qua_online": "NOT_STARTED",
                "qua_online_claims": 0,
                "qua_online_reason": None,
                "diem_danh": "NOT_STARTED",
                "diem_danh_error": None,
                "trung_thu_thue": "NOT_STARTED",
                "trung_thu_thue_reason": None,
                "error": None,
            },
            "cua_hang": {
                "status": "NOT_STARTED",
                "cua_hang_goi_y": "NOT_STARTED",
                "cua_hang_goi_y_reason": None,
                "cua_hang_thoi_han": "NOT_STARTED",
                "cua_hang_thoi_han_tabs": {},
                "cua_hang_thoi_han_reason": None,
                "tiem_than_bi": "NOT_STARTED",
                "tiem_than_bi_reason": None,
                "chieu_hien_lenh_bought": 0,
                "error": None,
            },
        }

    @staticmethod
    def _record(account: Any, tasks: dict[str, Any] | None = None) -> dict[str, Any]:
        status = getattr(account, "status", "READY")
        status_value = getattr(status, "value", status)
        resolved_tasks = tasks or DailyRuntimeStore._default_tasks()
        workflow = resolved_tasks.get("workflow") if isinstance(resolved_tasks, dict) else None
        current_step = workflow.get("current_step") if isinstance(workflow, dict) else None
        if current_step in {None, "DONE"}:
            current_step = None
        return {
            "id": str(account.id),
            "status": str(status_value),
            "attempts": int(getattr(account, "attempts", 0) or 0),
            "assigned_device": getattr(account, "assigned_worker", None),
            # Không để worker save() xóa mất bước resume đã ghi trong tasks.workflow.
            "current_task": current_step,
            "last_run": workflow.get("updated_at") if isinstance(workflow, dict) else None,
            "error_message": getattr(account, "last_error", None),
            "tasks": resolved_tasks,
        }

    def _read(self) -> dict[str, Any] | list[Any] | None:
        if not self.path.is_file():
            return None
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        import os
        import time

        path.parent.mkdir(parents=True, exist_ok=True)
        with RUNTIME_FILE_LOCK:
            # Use a worker-specific temporary file and retry the atomic replace.
            # On Windows another thread/process can briefly hold the destination.
            for attempt in range(8):
                temporary = path.with_name(
                    f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
                )
                try:
                    with temporary.open("w", encoding="utf-8") as handle:
                        json.dump(data, handle, ensure_ascii=False, indent=2)
                        handle.write("\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                    return
                except PermissionError:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                    if attempt >= 7:
                        raise
                    time.sleep(0.05 * (attempt + 1))
                except Exception:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise

    def _document(
        self,
        accounts: Iterable[Any],
        game_day: str,
        events: list[dict[str, Any]] | None = None,
        tasks_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tasks_by_id = tasks_by_id or {}
        return {
            "game_day": game_day,
            "reset_hour": self.clock.reset_hour,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "accounts": [self._record(account, tasks_by_id.get(str(account.id))) for account in accounts],
            "events": list(events or []),
        }

    def initialize(self, accounts: list[Any], *, now: datetime | None = None) -> bool:
        """Load today's state; archive/reset stale state. Returns True on rollover."""
        with self._lock:
            current_key = self.clock.key(now)
            raw = self._read()
            if isinstance(raw, dict) and raw.get("game_day") == current_key:
                self._apply(accounts, raw.get("accounts", []))
                changed = False
                defaults = self._default_tasks()
                for row in raw.get("accounts", []):
                    if not isinstance(row, dict):
                        continue
                    tasks = row.setdefault("tasks", {})
                    for task_name, task_state in defaults.items():
                        if task_name not in tasks:
                            # Tự động nâng cấp runtime cũ khi bổ sung task mới,
                            # không làm mất tiến độ của các task đã tồn tại.
                            tasks[task_name] = dict(task_state)
                            changed = True
                            continue

                        current_task = tasks.get(task_name)
                        if not isinstance(current_task, dict):
                            tasks[task_name] = dict(task_state)
                            changed = True
                            continue

                        # Bổ sung field mới cho runtime đang tồn tại.
                        for field_name, default_value in task_state.items():
                            if field_name not in current_task:
                                current_task[field_name] = default_value
                                changed = True

                        # `rewards` trước đây là dữ liệu fix cứng, không phải kết quả
                        # đọc thật từ popup. Loại bỏ khi migrate runtime cũ.
                        if "rewards" in current_task:
                            current_task.pop("rewards", None)
                            changed = True
                if changed:
                    self._write_json(self.path, raw)
                return False
            if isinstance(raw, dict) and raw.get("game_day"):
                self._archive(raw)
                self._reset_accounts(accounts)
                self._write_json(self.path, self._document(accounts, current_key))
                return True
            # The legacy list was never connected to the active queue and may be stale.
            # Preserve current source progress once, then runtime becomes authoritative.
            self._write_json(self.path, self._document(accounts, current_key))
            return False

    def save(self, accounts: Iterable[Any]) -> None:
        with self._lock:
            raw = self._read()
            events = raw.get("events", []) if isinstance(raw, dict) else []
            tasks_by_id = {
                str(row.get("id")): dict(row.get("tasks") or self._default_tasks())
                for row in raw.get("accounts", [])
                if isinstance(row, dict)
            } if isinstance(raw, dict) else {}
            # Only rollover() may advance game_day. A status write at exactly
            # 23:00 must not relabel old-day data before it is archived.
            game_day = str(raw.get("game_day")) if isinstance(raw, dict) and raw.get("game_day") else self.clock.key()
            self._write_json(self.path, self._document(accounts, game_day, events, tasks_by_id))

    def rollover(self, accounts: list[Any], *, now: datetime | None = None) -> bool:
        with self._lock:
            new_key = self.clock.key(now)
            raw = self._read()
            if isinstance(raw, dict) and raw.get("game_day") == new_key:
                self._apply(accounts, raw.get("accounts", []))
                return False
            if isinstance(raw, dict) and raw.get("game_day"):
                self._archive(raw)
            self._reset_accounts(accounts)
            self._write_json(self.path, self._document(accounts, new_key))
            return True

    def record_event(self, account_id: str, event_type: str, *, items: list[str] | None = None) -> None:
        with self._lock:
            raw = self._read()
            if not isinstance(raw, dict):
                return
            raw.setdefault("events", []).append({
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "account_id": str(account_id),
                "type": str(event_type),
                "items": list(items or []),
            })
            raw["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self._write_json(self.path, raw)

    def get_task(self, account_id: str, task_name: str) -> dict[str, Any]:
        with self._lock:
            raw = self._read()
            if not isinstance(raw, dict):
                return {}
            for row in raw.get("accounts", []):
                if isinstance(row, dict) and str(row.get("id")) == str(account_id):
                    return dict((row.get("tasks") or {}).get(task_name) or {})
            return {}

    def update_task(self, account_id: str, task_name: str, state: dict[str, Any]) -> None:
        with self._lock:
            raw = self._read()
            if not isinstance(raw, dict):
                raise RuntimeError("Daily runtime is not initialized")
            for row in raw.get("accounts", []):
                if isinstance(row, dict) and str(row.get("id")) == str(account_id):
                    row.setdefault("tasks", self._default_tasks())[task_name] = dict(state)
                    raw["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                    self._write_json(self.path, raw)
                    return
            raise KeyError(f"Runtime account not found: {account_id}")

    @staticmethod
    def _apply(accounts: list[Any], records: Iterable[Any]) -> None:
        by_id = {str(row.get("id")): row for row in records if isinstance(row, dict)}
        for account in accounts:
            row = by_id.get(str(account.id))
            if row is None:
                continue
            status_type = type(account.status)
            normalize = getattr(status_type, "normalize", None)
            account.status = normalize(row.get("status")) if callable(normalize) else row.get("status", account.status)
            account.attempts = max(0, int(row.get("attempts", 0) or 0))
            account.assigned_worker = row.get("assigned_device") or None
            account.last_error = row.get("error_message") or None

    @staticmethod
    def _reset_accounts(accounts: Iterable[Any]) -> None:
        for account in accounts:
            status_type = type(account.status)
            disabled = getattr(status_type, "DISABLED", "DISABLED")
            ready = getattr(status_type, "READY", "READY")
            if account.status != disabled:
                account.status = ready
            account.attempts = 0
            account.assigned_worker = None
            account.last_error = None

    def _archive(self, raw: dict[str, Any]) -> None:
        game_day = str(raw["game_day"])
        target = self.archive_dir / game_day
        target.mkdir(parents=True, exist_ok=True)
        self._write_json(target / "account_runtime.json", raw)
        accounts = [row for row in raw.get("accounts", []) if isinstance(row, dict)]
        events = [row for row in raw.get("events", []) if isinstance(row, dict)]
        counts: dict[str, int] = {}
        for row in accounts:
            status = str(row.get("status", "UNKNOWN"))
            counts[status] = counts.get(status, 0) + 1
        known_items = [item for event in events for item in event.get("items", []) if item]
        lines = [
            f"# Tổng kết ngày game {game_day}",
            "",
            f"- Tổng tài khoản: {len(accounts)}",
            *[f"- {status}: {count}" for status, count in sorted(counts.items())],
            f"- Sự kiện đã ghi nhận: {len(events)}",
            f"- Vật phẩm xác định được: {len(known_items)}",
        ]
        if known_items:
            lines.extend(["", "## Vật phẩm", *[f"- {item}" for item in known_items]])
        else:
            lines.extend(["", "Chưa có dữ liệu OCR/định danh vật phẩm đủ tin cậy; không suy đoán."])
        (target / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
