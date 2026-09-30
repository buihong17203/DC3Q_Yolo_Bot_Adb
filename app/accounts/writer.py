from __future__ import annotations
import csv
from pathlib import Path

ATTENDANCE_FIELD = "Diem-Danh"

def write_accounts(path: str | Path, rows: list[dict[str,str]]) -> Path:
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    fields=list(rows[0].keys()) if rows else []
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    return p


def read_attendance_day(path: str | Path, account_id: str) -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("id") != account_id:
                continue
            value = (row.get(ATTENDANCE_FIELD) or "").strip()
            return int(value) if value.isdigit() and 1 <= int(value) <= 30 else None
    raise KeyError(account_id)


def write_attendance_day(path: str | Path, account_id: str, day: int) -> None:
    if not 1 <= day <= 30:
        raise ValueError("Ngày điểm danh phải nằm trong 1..30")
    p = Path(path)
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if ATTENDANCE_FIELD not in fields:
        fields.append(ATTENDANCE_FIELD)
    found = False
    for row in rows:
        if row.get("id") == account_id:
            row[ATTENDANCE_FIELD] = str(day)
            found = True
            break
    if not found:
        raise KeyError(account_id)
    temporary = p.with_suffix(p.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(p)
