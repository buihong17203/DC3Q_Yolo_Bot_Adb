from __future__ import annotations
import csv
from pathlib import Path

def read_accounts(path: str | Path) -> list[dict[str,str]]:
    p=Path(path)
    if not p.exists(): return []
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]
