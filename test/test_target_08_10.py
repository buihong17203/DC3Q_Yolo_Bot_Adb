from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

import yaml

from app.vision.template import MatchResult


ROOT = Path(__file__).parents[1]


@dataclass
class Detection:
    match: MatchResult


class FakeVision:
    def __init__(self, states):
        self.states = states
        self.current = None

    def find_template(self, screen, name, template, threshold=0.85):
        self.current = screen
        key = Path(template).name
        if key in screen:
            x, y, w, h, score = screen[key]
            return Detection(MatchResult(True, score, x, y, w, h))
        return Detection(MatchResult(False, 0.0, 0, 0, 10, 10))


class FakeInput:
    def __init__(self):
        self.taps = []
        self.swipes = []

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, *args):
        self.swipes.append(args)


class Screens:
    def __init__(self, states):
        self.states = list(states)
        self.index = 0

    def __call__(self):
        if self.index < len(self.states):
            state = self.states[self.index]
            self.index += 1
            return state
        return self.states[-1]


def cfg(name):
    return yaml.safe_load((ROOT / f"config/dc3q/targets/{name}.yaml").read_text(encoding="utf-8"))


def paths(values):
    return [ROOT / value for value in values]


def one(value):
    return ROOT / value


def m(path, x=10, y=20, w=30, h=40, score=0.95):
    return {Path(path).name: (x, y, w, h, score)}


def merge(*items):
    out = {}
    for item in items:
        out.update(item)
    return out


def test_target_08_clicks_only_free_vo_tuong_and_recovers_home():
    mod = import_module("app.actions.dc3q.targets.08_vo-tuong")
    raw = cfg("08_vo-tuong")["vo_tuong"]
    c = mod.VoTuongConfig(
        entry_templates=paths(raw["home"]["entry"]), menu_templates=paths(raw["home"]["menu"]),
        home_markers=paths(raw["home"]["markers"]), panel_markers=paths(raw["panel"]["markers"]),
        close_template=one(raw["panel"]["close"]), reward_marker=one(raw["reward"]["marker"]),
        reward_dismiss=one(raw["reward"]["dismiss"]), safe_actions=paths(raw["safe_actions"]),
        forbidden_actions=paths(raw["forbidden_actions"]), threshold=0.60, max_steps=10, wait_seconds=0,
    )
    screens = Screens([
        m(c.entry_templates[0], 100, 100, 20, 20),
        merge(m(c.panel_markers[0]), m(c.safe_actions[0], 200, 210, 40, 20)),
        merge(m(c.reward_marker), m(c.reward_dismiss, 250, 260, 20, 20)),
        merge(m(c.panel_markers[0]), m(c.close_template, 300, 310, 20, 20)),
        m(c.home_markers[0]),
    ])
    inp = FakeInput()
    assert mod.VoTuongRunner(screens, inp, FakeVision([]), c, sleep=lambda _: None).run() is True
    assert (220, 220) in inp.taps
    assert all(t != (15, 25) for t in inp.taps)


def test_target_08_skips_when_only_ton_ngoc_action_visible():
    mod = import_module("app.actions.dc3q.targets.08_vo-tuong")
    raw = cfg("08_vo-tuong")["vo_tuong"]
    c = mod.VoTuongConfig(
        entry_templates=paths(raw["home"]["entry"]), menu_templates=paths(raw["home"]["menu"]),
        home_markers=paths(raw["home"]["markers"]), panel_markers=paths(raw["panel"]["markers"]),
        close_template=one(raw["panel"]["close"]), reward_marker=one(raw["reward"]["marker"]),
        reward_dismiss=one(raw["reward"]["dismiss"]), safe_actions=paths(raw["safe_actions"]),
        forbidden_actions=paths(raw["forbidden_actions"]), threshold=0.60, max_steps=8, wait_seconds=0,
    )
    screens = Screens([
        m(c.entry_templates[0]),
        merge(m(c.panel_markers[0]), m(c.forbidden_actions[0], 400, 410, 40, 20), m(c.close_template, 300, 310, 20, 20)),
        m(c.home_markers[0]),
    ])
    inp = FakeInput()
    assert mod.VoTuongRunner(screens, inp, FakeVision([]), c, sleep=lambda _: None).run() is True
    assert (420, 420) not in inp.taps


def test_target_09_claims_only_finished_reward_never_unfinished_battle():
    mod = import_module("app.actions.dc3q.targets.09_quan-su")
    raw = cfg("09_quan-su")["quan_su"]
    c = mod.QuanSuConfig(
        entry_templates=paths(raw["home"]["entry"]), menu_templates=paths(raw["home"]["menu"]),
        home_markers=paths(raw["home"]["markers"]), panel_markers=paths(raw["panel"]["markers"]),
        close_template=one(raw["panel"]["close"]), reward_button=one(raw["reward"]["button"]),
        claimed_markers=paths(raw["reward"]["claimed"]), unfinished_markers=paths(raw["forbidden"]["unfinished_battle"]),
        threshold=0.60, max_steps=8, wait_seconds=0,
    )
    screens = Screens([
        m(c.entry_templates[0]),
        merge(m(c.panel_markers[0]), m(c.unfinished_markers[0], 10, 10, 20, 20), m(c.close_template, 300, 310, 20, 20)),
        m(c.home_markers[0]),
    ])
    inp = FakeInput()
    assert mod.QuanSuRunner(screens, inp, FakeVision([]), c, sleep=lambda _: None).run() is True
    assert (20, 20) not in inp.taps

    screens = Screens([
        m(c.entry_templates[0]),
        merge(m(c.panel_markers[0]), m(c.reward_button, 200, 210, 40, 20)),
        merge(m(c.panel_markers[0]), m(c.claimed_markers[0]), m(c.close_template, 300, 310, 20, 20)),
        m(c.home_markers[0]),
    ])
    inp = FakeInput()
    assert mod.QuanSuRunner(screens, inp, FakeVision([]), c, sleep=lambda _: None).run() is True
    assert (220, 220) in inp.taps


def test_target_10_is_disabled_without_its_own_close_template():
    raw = cfg("10_nhiem-vu")["nhiem_vu"]
    assert raw["enabled"] is False
    assert raw["panel"]["close"] is None

def test_configs_use_only_existing_png_assets_and_no_new_images_needed():
    for name in ("08_vo-tuong", "09_quan-su", "10_nhiem-vu"):
        raw = cfg(name)
        stack = [raw]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, str) and value.endswith(".png"):
                assert (ROOT / value).is_file(), value
