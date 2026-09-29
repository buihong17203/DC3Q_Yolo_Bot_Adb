from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_activity_tab_closed_and_open_templates_are_disjoint():
    cfg = load("config/dc3q/targets/02_hoat-dong.yaml")["hoat_dong"]
    for name in ("welfare", "national_fortune", "attendance", "tax"):
        group = cfg[name]
        assert set(group["tabs"]).isdisjoint(group["open"]), name


def test_all_configured_png_templates_exist():
    missing = []
    for config in (ROOT / "config").rglob("*.yaml"):
        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
        stack = [raw]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, str) and value.endswith(".png"):
                if not (ROOT / value).is_file():
                    missing.append((config.relative_to(ROOT).as_posix(), value))
    assert missing == []
