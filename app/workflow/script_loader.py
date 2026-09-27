from __future__ import annotations
from pathlib import Path
from typing import Any

class WorkflowError(ValueError): pass

class ScriptLoader:
    def load(self, path: str | Path) -> dict[str, Any]:
        p=Path(path)
        if not p.is_file(): raise FileNotFoundError(p)
        try:
            import yaml
        except ImportError as exc: raise RuntimeError("Cần cài PyYAML để đọc workflow YAML") from exc
        data=yaml.safe_load(p.read_text(encoding="utf-8"))
        if data is None: return {}
        if not isinstance(data, dict): raise WorkflowError("Workflow root phải là mapping/object")
        return data
