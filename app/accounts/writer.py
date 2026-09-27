from __future__ import annotations
import csv
from pathlib import Path

def write_accounts(path: str | Path, rows: list[dict[str,str]]) -> Path:
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    fields=list(rows[0].keys()) if rows else []
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    return p
