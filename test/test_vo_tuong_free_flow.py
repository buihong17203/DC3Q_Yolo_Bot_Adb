from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.08_vo-tuong")


def match(name, confidence):
    return SimpleNamespace(found=confidence >= .7, confidence=confidence, x=0, y=0, width=10, height=10, name=name)


def test_vo_tuong_exposes_runtime_checkpoint_name():
    assert module.VoTuongRunner.runtime_task == "VO_TUONG"


def test_nhan_duc_free_requires_clear_winner_over_25_soul():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(
        nhan_duc_free="free", nhan_duc_paid="paid",
        action_threshold=.8, state_margin=.05,
    )
    runner.screen_provider = lambda: "fresh"
    runner._match = lambda screen, template, threshold=None: match(
        template, {"free": .98, "paid": .84}[template]
    )
    assert runner._nhan_duc_free()[1].name == "free"


def test_nhan_duc_rejects_paid_or_ambiguous_control():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(
        nhan_duc_free="free", nhan_duc_paid="paid",
        action_threshold=.8, state_margin=.05,
    )
    runner.screen_provider = lambda: "fresh"
    scores = {"free": .98, "paid": .96}
    runner._match = lambda screen, template, threshold=None: match(template, scores[template])
    assert runner._nhan_duc_free()[1] is None
    scores.update(free=.91, paid=.99)
    assert runner._nhan_duc_free()[1] is None


def test_free_draw_waits_for_stable_return_control_not_random_fullscreen():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(reward_dismiss="return", point_markers=["lobby"])
    runner._wait_first = lambda templates, attempts=None: (
        ("result", match("return", 1.0))
        if templates == ["return"]
        else ("screen", match("state", 1.0))
    )
    runner._match = lambda screen, template, threshold=None: match(template, 1.0)
    runner._tap = lambda found: None
    runner._nhan_duc_free = lambda: ("screen", match("free", 1.0))

    assert runner._draw_or_return(
        "Nhân Đức", ["state"], "paid", runner._nhan_duc_free,
    ) == "screen"
