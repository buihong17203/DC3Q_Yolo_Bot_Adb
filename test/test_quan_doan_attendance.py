from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import yaml

module = import_module("app.actions.dc3q.targets.04_quan-doan")
ROOT = Path(__file__).parents[1]


def match(found, confidence=0.0):
    return SimpleNamespace(
        found=found, confidence=confidence, x=10, y=20, width=20, height=10,
    )


def runner():
    value = object.__new__(module.QuanDoanRunner)
    value.config = SimpleNamespace(
        registration_available=Path("registration-yellow"),
        registration_done=Path("registration-gray"),
        prayer_available=Path("prayer-nonzero"),
        prayer_empty=Path("prayer-zero"),
        prayer_entry=Path("screen_qd_button_open_cauvanquandoan.png"),
        prayer_open=[Path("prayer-nonzero"), Path("prayer-zero")],
        state_threshold=0.76,
        registration_wait_attempts=24,
        wait_seconds=0,
        max_steps=30,
    )
    value.sleep = lambda _: None
    value.input = SimpleNamespace(tap=lambda x, y: None)
    return value


def test_quan_doan_config_maps_registration_and_prayer_states():
    cfg = yaml.safe_load(
        (ROOT / "config/dc3q/targets/04_quan-doan.yaml").read_text(encoding="utf-8")
    )["quan_doan"]
    assert cfg["enabled"] is True
    assert cfg["entrance_wait_attempts"] == 24
    assert Path(cfg["registration"]["available"]).name == "screen_qd_button_baodanh_chuabaodanh.png"
    assert Path(cfg["registration"]["done"]).name == "screen_qd_button_baodanh_dabaodanh.png"
    assert Path(cfg["prayer"]["available"]).name == "screen_qd_cvqd_button_10cauvan.png"
    assert Path(cfg["prayer"]["empty"]).name == "screen_qd_cvqd_button_0cauvan.png"
    assert Path(cfg["prayer"]["entry"]).name == "screen_qd_button_open_cauvanquandoan.png"
    paths = [cfg["registration"]["available"], cfg["registration"]["done"]]
    paths += [cfg["prayer"]["entry"], cfg["prayer"]["available"], cfg["prayer"]["empty"]]
    assert all((ROOT / p).is_file() for p in paths)


def test_open_prayer_taps_dedicated_button_and_waits_for_10_or_0_state():
    value = runner()
    entry = match(True, 0.99)
    value._first = lambda screen, templates, threshold=None: None
    value._match = lambda screen, template, threshold=None: entry
    calls = []
    value._tap = calls.append
    value._wait_for = lambda templates: ("prayer-screen", match(True, 0.99))

    assert value._open_prayer("guild-screen") == "prayer-screen"
    assert calls == [entry]


def test_available_registration_clicks_and_requires_done_state():
    value = runner()
    states = {
        "registration-yellow": [match(True, 0.93)],
        "registration-gray": [match(False), match(True, 0.95)],
    }
    value._match = lambda screen, template, threshold=None: states[template.name].pop(0)
    tapped = []
    value._tap = tapped.append
    value.screen_provider = lambda: object()

    assert value._register(object()) == "registered"
    assert len(tapped) == 1


def test_registration_waits_through_loading_frame_before_clicking():
    value = runner()
    available = [match(False, 0.26), match(True, 0.99)]
    done = [match(False, 0.26), match(False), match(True, 0.99)]
    value._match = lambda screen, template, threshold=None: (
        available.pop(0) if template.name == "registration-yellow" else done.pop(0)
    )
    frames = iter(["loaded", "verified"])
    value.screen_provider = lambda: next(frames)
    tapped = []
    value._tap = tapped.append

    assert value._register("loading") == "registered"
    assert len(tapped) == 1


def test_done_registration_does_not_tap():
    value = runner()
    answers = {
        "registration-yellow": match(False),
        "registration-gray": match(True, 0.96),
    }
    value._match = lambda screen, template, threshold=None: answers[template.name]
    tapped = []
    value._tap = tapped.append

    assert value._register(object()) == "already_registered"
    assert tapped == []


def test_prayer_nonzero_clicks_until_zero():
    value = runner()
    frames = iter(["after-first", "after-second"])
    value.screen_provider = lambda: next(frames)
    states = {
        ("start", "prayer-nonzero"): match(True, 0.93),
        ("start", "prayer-zero"): match(False),
        ("after-first", "prayer-nonzero"): match(True, 0.91),
        ("after-first", "prayer-zero"): match(False),
        ("after-second", "prayer-nonzero"): match(False),
        ("after-second", "prayer-zero"): match(True, 0.98),
    }
    value._match = lambda screen, template, threshold=None: states[(screen, template.name)]
    tapped = []
    value._tap = tapped.append

    assert value._run_prayer("start") == "empty"
    assert len(tapped) == 2
