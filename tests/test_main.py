from pathlib import Path

from app.main import _resolve_scenario


def test_resolve_project_relative_scripts_path_without_duplication() -> None:
    resolved = _resolve_scenario("scripts/multi_account_login_logout.yaml")

    assert resolved == Path("scripts/multi_account_login_logout.yaml").resolve()
    assert "scripts\\scripts" not in str(resolved)


def test_resolve_bare_scenario_name_under_scripts() -> None:
    assert _resolve_scenario("multi_account_manager.yaml") == Path(
        "scripts/multi_account_manager.yaml"
    ).resolve()