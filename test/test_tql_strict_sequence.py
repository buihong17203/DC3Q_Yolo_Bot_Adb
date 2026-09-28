from pathlib import Path
from importlib import import_module

from app.vision.template import MatchResult

tam_quoc_lenh = import_module("app.actions.dc3q.targets.01_tam-quoc-lenh")
TamQuocLenhConfig = tam_quoc_lenh.TamQuocLenhConfig
TamQuocLenhRunner = tam_quoc_lenh.TamQuocLenhRunner


class Input:
    def __init__(self): self.taps = []
    def tap(self, x, y): self.taps.append((x, y))


class Vision:
    points = {"entry": 10, "que_tab": 20, "que_free": 25, "que_paid": 30,
              "diem_tab": 40, "diem_free": 45, "diem_paid": 50,
              "dismiss": 55, "close": 60, "home": 70}
    def find_template(self, screen, _name, template, _threshold):
        name = Path(template).stem
        found = name in screen
        x = self.points.get(name, 0)
        return type("D", (), {"match": MatchResult(found, float(found), x, 0, 2, 2)})()


def test_must_open_diem_binh_tab_before_accepting_100_vang(tmp_path):
    p = lambda name: tmp_path / f"{name}.png"
    cfg = TamQuocLenhConfig(
        entry_templates=[p("entry")], menu_templates=[], panel_markers=[p("close")],
        close_template=p("close"), reward_marker=p("reward"), reward_dismiss=p("dismiss"),
        que_boi_tabs=[p("que_tab")], que_boi_open=[p("que_open")], que_boi_free=p("que_free"), que_boi_paid=p("que_paid"),
        diem_binh_tabs=[p("diem_tab")], diem_binh_open=[p("diem_open")], diem_binh_free=p("diem_free"), diem_binh_paid=p("diem_paid"),
        action_roi=(0, 0, 999, 999), home_markers=[p("home")], max_steps=12,
    )
    screens = iter([
        {"entry"}, {"que_tab", "close"}, {"que_open", "close"}, {"que_paid", "close"},
        {"diem_tab", "diem_paid", "close"}, {"diem_open", "close"}, {"diem_paid", "close"}, {"close"}, {"home"},
    ])
    adb = Input()
    assert TamQuocLenhRunner(lambda: next(screens), adb, Vision(), cfg, sleep=lambda _: None).run()
    assert adb.taps == [(11, 1), (21, 1), (41, 1), (61, 1)]


def test_free_actions_are_claimed_before_paid_postconditions(tmp_path):
    p = lambda name: tmp_path / f"{name}.png"
    cfg = TamQuocLenhConfig(
        entry_templates=[p("entry")], menu_templates=[], panel_markers=[p("close")],
        close_template=p("close"), reward_marker=p("reward"), reward_dismiss=p("dismiss"),
        que_boi_tabs=[p("que_tab")], que_boi_open=[p("que_open")], que_boi_free=p("que_free"), que_boi_paid=p("que_paid"),
        diem_binh_tabs=[p("diem_tab")], diem_binh_open=[p("diem_open")], diem_binh_free=p("diem_free"), diem_binh_paid=p("diem_paid"),
        action_roi=(0, 0, 999, 999), home_markers=[p("home")], max_steps=16,
    )
    screens = iter([
        {"entry"}, {"que_tab", "close"}, {"que_open", "close"}, {"que_free", "close"},
        {"reward", "dismiss"}, {"que_paid", "close"},
        {"diem_tab", "close"}, {"diem_open", "close"}, {"diem_free", "close"},
        {"reward", "dismiss"}, {"diem_paid", "close"}, {"close"}, {"home"},
    ])
    adb = Input()
    assert TamQuocLenhRunner(lambda: next(screens), adb, Vision(), cfg, sleep=lambda _: None).run()
    assert adb.taps == [
        (11, 1), (21, 1), (26, 1), (56, 1),
        (41, 1), (46, 1), (56, 1), (61, 1),
    ]
