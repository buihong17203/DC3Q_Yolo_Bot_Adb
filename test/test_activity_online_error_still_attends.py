from importlib import import_module
from types import SimpleNamespace


module = import_module("app.actions.dc3q.targets.02_hoat-dong")


def test_online_error_does_not_skip_attendance():
    runner = object.__new__(module.HoatDongRunner)
    runner.config = SimpleNamespace(
        entry_templates=["entry"], panel_markers=["panel"],
        national_tabs=["national"], national_open=["national-open"],
        national_free="free", national_claimed="claimed",
        online_tabs=["online"], online_open=["online-open"],
        attendance_tabs=["attendance"], attendance_open=["attendance-open"],
        attendance_milestone_rois=[], tax_tabs=[], newcomer_tabs=[],
        close_template="close", home_markers=["home"],
        state_threshold=.76, wait_seconds=0, threshold=.65,
    )
    screen = object()
    runner.screen_provider = lambda: screen
    closed = []
    runner._first = lambda image, templates: (
        None if templates == ["panel"] and closed else SimpleNamespace(found=True)
    )
    runner._tap = lambda match: closed.append(True) if getattr(match, "name", "") == "close" else None
    runner._wait_for = lambda templates: (screen, SimpleNamespace(found=True))
    runner._open_tab = lambda *args: screen
    runner._match = lambda image, template, threshold=None: SimpleNamespace(
        found=template in {"claimed", "close"},
        confidence=1.0 if template in {"claimed", "close"} else 0.0,
        name=template,
    )
    runner._open_online_tab = lambda image: screen
    runner._claim_online = lambda image: (_ for _ in ()).throw(RuntimeError("reward timeout"))
    opened = []
    runner._open_attendance_tab = lambda image: opened.append("attendance") or screen
    runner._attendance_states = lambda image: ["tick"] * 30
    runner._saved_attendance_candidate = lambda image: None
    runner._claim_attendance_milestones = lambda image: image
    runner._tax_window_open = lambda: False
    runner._open_newcomer_if_present = lambda image: None
    runner._run_newcomer = lambda image: None
    runner._close_panel = lambda image: True
    runner.attendance_day = lambda: 30

    assert runner.run() is True
    assert opened == ["attendance"]
    assert runner.soft_errors == ["Quà online: reward timeout"]