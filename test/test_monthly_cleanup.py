from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core.monthly_cleanup import MonthlyCleanup

TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.fixture
def temp_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        docs_dir = root / "docs" / "docs_days_runtime"
        logs_dir = root / "logs" / "logs_days_runtime"
        doc_project = root / "docs" / "doc_project"
        logs_project = root / "logs" / "logs_project"
        state_file = root / "data" / "accounts" / "monthly_cleanup.json"

        # Create subdirectories
        (docs_dir / "csv").mkdir(parents=True, exist_ok=True)
        (docs_dir / "error").mkdir(parents=True, exist_ok=True)
        (logs_dir / "log powershell").mkdir(parents=True, exist_ok=True)
        (logs_dir / "vision").mkdir(parents=True, exist_ok=True)
        doc_project.mkdir(parents=True, exist_ok=True)
        logs_project.mkdir(parents=True, exist_ok=True)

        # Create project docs (MUST NEVER BE DELETED)
        (doc_project / "kich_ban.md").write_text("spec", encoding="utf-8")
        (doc_project / "project_structure.md").write_text("spec", encoding="utf-8")
        (logs_project / "project.log").write_text("info", encoding="utf-8")

        # Create .gitkeep
        (docs_dir / "csv" / ".gitkeep").write_text("", encoding="utf-8")

        # Create old month files (2026-10)
        (docs_dir / "csv" / "account_runtime_2026-10-18.csv").write_text("data", encoding="utf-8")
        (docs_dir / "csv" / "account_runtime_2026-10-31.csv").write_text("data", encoding="utf-8")
        (docs_dir / "error" / "error_message_2026-10-20.txt").write_text("error", encoding="utf-8")
        (docs_dir / "error" / "error_message_2026-10-31.txt").write_text("error", encoding="utf-8")
        (logs_dir / "log powershell" / "dc3q_log-powershell_2026-10-31.log").write_text("log", encoding="utf-8")
        (logs_dir / "vision" / "dc3q_vision_2026-10-31.log").write_text("vision", encoding="utf-8")

        # Create an old unknown file without date in filename (set mtime to 2026-10-25)
        unknown_file = docs_dir / "csv" / "account_runtime_unknown.csv"
        unknown_file.write_text("unknown", encoding="utf-8")
        oct_mtime = datetime(2026, 10, 25, 12, 0, 0, tzinfo=TIMEZONE).timestamp()
        os.utime(unknown_file, (oct_mtime, oct_mtime))

        # Create current month files (2026-11)
        (docs_dir / "csv" / "account_runtime_2026-11-01.csv").write_text("data_nov", encoding="utf-8")
        (docs_dir / "error" / "error_message_2026-11-01.txt").write_text("error_nov", encoding="utf-8")
        (logs_dir / "log powershell" / "dc3q_log-powershell_2026-11-01.log").write_text("log_nov", encoding="utf-8")
        (logs_dir / "vision" / "dc3q_vision_2026-11-01.log").write_text("vision_nov", encoding="utf-8")

        cleanup = MonthlyCleanup(
            root,
            docs_dir=docs_dir,
            logs_dir=logs_dir,
            state_file=state_file,
            timezone=TIMEZONE,
        )

        yield {
            "root": root,
            "docs_dir": docs_dir,
            "logs_dir": logs_dir,
            "doc_project": doc_project,
            "logs_project": logs_project,
            "state_file": state_file,
            "cleanup": cleanup,
        }


def test_is_old_month_file(temp_env):
    cleanup: MonthlyCleanup = temp_env["cleanup"]
    docs_dir = temp_env["docs_dir"]

    # October 2026 is old relative to November 2026
    old_csv = docs_dir / "csv" / "account_runtime_2026-10-31.csv"
    assert cleanup.is_old_month_file(old_csv, 2026, 11) is True

    # November 2026 is NOT old relative to November 2026
    cur_csv = docs_dir / "csv" / "account_runtime_2026-11-01.csv"
    assert cleanup.is_old_month_file(cur_csv, 2026, 11) is False

    # .gitkeep should never be marked as old
    gitkeep = docs_dir / "csv" / ".gitkeep"
    assert cleanup.is_old_month_file(gitkeep, 2026, 11) is False

    # File without date in name with October mtime
    unknown_csv = docs_dir / "csv" / "account_runtime_unknown.csv"
    assert cleanup.is_old_month_file(unknown_csv, 2026, 11) is True


def test_year_boundary(temp_env):
    cleanup: MonthlyCleanup = temp_env["cleanup"]
    docs_dir = temp_env["docs_dir"]

    # Create Dec 2026 file
    dec_file = docs_dir / "csv" / "account_runtime_2026-12-31.csv"
    dec_file.write_text("dec", encoding="utf-8")

    # In January 2027, December 2026 must be old
    assert cleanup.is_old_month_file(dec_file, 2027, 1) is True

    # In December 2026, December 2026 is not old
    assert cleanup.is_old_month_file(dec_file, 2026, 12) is False


def test_should_run_on_first_run_of_mung_1(temp_env):
    cleanup: MonthlyCleanup = temp_env["cleanup"]

    # Simulated time: 2026-11-01 08:00 (mùng 1)
    mung_1 = datetime(2026, 11, 1, 8, 0, 0, tzinfo=TIMEZONE)

    # First run: state file doesn't exist yet -> should run
    assert cleanup.should_run(now=mung_1) is True

    # Perform cleanup
    res = cleanup.maybe_run(now=mung_1)
    assert res is not None
    assert len(res["docs"]) > 0
    assert len(res["logs"]) > 0

    # Second run on mùng 1 at 12:00 -> should NOT run again
    mung_1_later = datetime(2026, 11, 1, 12, 0, 0, tzinfo=TIMEZONE)
    assert cleanup.should_run(now=mung_1_later) is False
    assert cleanup.maybe_run(now=mung_1_later) is None


def test_clean_preserves_current_month_and_project_docs(temp_env):
    cleanup: MonthlyCleanup = temp_env["cleanup"]
    docs_dir = temp_env["docs_dir"]
    logs_dir = temp_env["logs_dir"]
    doc_project = temp_env["doc_project"]
    logs_project = temp_env["logs_project"]

    now = datetime(2026, 11, 1, 8, 0, 0, tzinfo=TIMEZONE)
    cleanup.clean(now=now)

    # All October files in docs and logs must be deleted
    assert not (docs_dir / "csv" / "account_runtime_2026-10-18.csv").exists()
    assert not (docs_dir / "csv" / "account_runtime_2026-10-31.csv").exists()
    assert not (docs_dir / "csv" / "account_runtime_unknown.csv").exists()
    assert not (docs_dir / "error" / "error_message_2026-10-20.txt").exists()
    assert not (docs_dir / "error" / "error_message_2026-10-31.txt").exists()
    assert not (logs_dir / "log powershell" / "dc3q_log-powershell_2026-10-31.log").exists()
    assert not (logs_dir / "vision" / "dc3q_vision_2026-10-31.log").exists()

    # November files must still exist!
    assert (docs_dir / "csv" / "account_runtime_2026-11-01.csv").exists()
    assert (docs_dir / "error" / "error_message_2026-11-01.txt").exists()
    assert (logs_dir / "log powershell" / "dc3q_log-powershell_2026-11-01.log").exists()
    assert (logs_dir / "vision" / "dc3q_vision_2026-11-01.log").exists()

    # .gitkeep must still exist!
    assert (docs_dir / "csv" / ".gitkeep").exists()

    # Project docs must NEVER be touched!
    assert (doc_project / "kich_ban.md").exists()
    assert (doc_project / "project_structure.md").exists()
    assert (logs_project / "project.log").exists()


def test_catch_up_if_mung_1_missed(temp_env):
    cleanup: MonthlyCleanup = temp_env["cleanup"]

    # Bot runs on 2026-11-02 (mùng 2) for the first time
    mung_2 = datetime(2026, 11, 2, 9, 0, 0, tzinfo=TIMEZONE)
    assert cleanup.should_run(now=mung_2) is True

    cleanup.maybe_run(now=mung_2)

    # Next run on mùng 2 -> should not run
    assert cleanup.should_run(now=mung_2) is False

    # Run on mùng 15 -> should not run
    mung_15 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=TIMEZONE)
    assert cleanup.should_run(now=mung_15) is False


def test_force_always_runs(temp_env):
    cleanup: MonthlyCleanup = temp_env["cleanup"]
    mung_15 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=TIMEZONE)

    # Record state as already cleaned
    cleanup.save_state({"last_cleanup_month": "2026-11"})

    assert cleanup.should_run(now=mung_15, force=False) is False
    assert cleanup.should_run(now=mung_15, force=True) is True
