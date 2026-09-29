from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from app.vision.template import MatchResult

m = import_module("app.actions.dc3q.targets.07_truong-thanh")
TruongThanhConfig = m.TruongThanhConfig
TruongThanhRunner = m.TruongThanhRunner
ROOT = Path(__file__).parent
T = ROOT / "data/img/templates/targets/07_truong-thanh"
H = ROOT / "data/img/templates/stars/home/screen"


def cfg(**kw):
    base = dict(
        entry_templates=[H / "screen_truong-thanh_01.png"],
        menu_templates=[H / "screen_home_morong_chamthan.png"],
        home_markers=[H / "screen_chien-tranh_01.png"],
        close_templates=[
            T / "A4_ve-tuong/screen/full-screen_vt_tcc_cmnd_trove.png",
            T / "A6_than-binh/screen/screen_tb_tambinhmichbao_button_trove.png",
            T / "A5_trai-ngua/screen/screen_tn_anvaochotrongdethoat.png",
        ],
        skipped_subflows=["A1_bao-vat", "A2_tuong-an", "A3_chua-cong"],
        flows=[],
        threshold=0.7,
        max_steps=20,
        wait_seconds=0,
    )
    base.update(kw)
    return TruongThanhConfig(**base)


class Vision:
    def __init__(self, states):
        self.states = states
    def find_template(self, screen, name, template, threshold=0.85):
        return SimpleNamespace(match=self.states.get(screen, {}).get(template, MatchResult(False, 0.0)))


class Input:
    def __init__(self):
        self.taps = []
    def tap(self, x, y):
        self.taps.append((x, y))


def hit(x=10, y=20, w=30, h=40):
    return MatchResult(True, 0.99, x, y, w, h)


def test_skipped_subflows_are_explicit_contract():
    c = cfg()
    assert c.skipped_subflows == ["A1_bao-vat", "A2_tuong-an", "A3_chua-cong"]


def test_clicks_free_vetuong_then_proves_spent_state_before_done():
    free = T / "A4_ve-tuong/screen/screen_vt_tcc_button_dienquai1lan_free.png"
    spent = T / "A4_ve-tuong/full screen/full-screen_vt_tcc_chucmungnhanduoc.png"
    done = T / "A4_ve-tuong/screen/full-screen_vt_tcc_cmnd_trove.png"
    flow = m.SubFlow("A4", [T / "A4_ve-tuong/screen/screen_vt_vethanh.png"], [free], [spent], [done])
    states = {
        "home": {H / "screen_truong-thanh_01.png": hit()},
        "free": {free: hit(100, 100)},
        "spent": {spent: hit()},
        "done": {done: hit()},
        "back": {H / "screen_chien-tranh_01.png": hit()},
    }
    screens = iter(["home", "free", "spent", "done", "back"])
    inp = Input()

    assert TruongThanhRunner(lambda: next(screens), inp, Vision(states), cfg(flows=[flow])).run()
    assert inp.taps[0] == (25, 40)
    assert inp.taps[1] == (115, 120)
    assert inp.taps[2] == (25, 40)


def test_paid_or_unknown_control_is_not_clicked():
    paid = T / "A6_than-binh/screen/screen_tb_tambinhmichbao_button_tieptuc_tonngoc.png"
    flow = m.SubFlow("A6", [], [T / "A6_than-binh/screen/screen_tb_tambinhmichbao_button_1lan_mienphi.png"], [paid], [T / "A6_than-binh/screen/screen_tb_tambinhmichbao_button_dong.png"])
    states = {
        "home": {H / "screen_truong-thanh_01.png": hit()},
        "paid": {paid: hit(100, 100)},
        "closed": {T / "A6_than-binh/screen/screen_tb_tambinhmichbao_button_dong.png": hit()},
        "back": {H / "screen_chien-tranh_01.png": hit()},
    }
    screens = iter(["home", "paid", "closed", "back"])
    inp = Input()

    assert TruongThanhRunner(lambda: next(screens), inp, Vision(states), cfg(flows=[flow])).run()
    assert inp.taps == [(25, 40), (25, 40)]


def test_recover_home_closes_reverse_layers_only():
    close = T / "A5_trai-ngua/screen/screen_tn_anvaochotrongdethoat.png"
    states = {"layer": {close: hit(50, 60)}, "home": {H / "screen_chien-tranh_01.png": hit()}}
    screens = iter(["layer", "home"])
    inp = Input()

    assert TruongThanhRunner(lambda: next(screens), inp, Vision(states), cfg()).recover_home()
    assert inp.taps == [(65, 80)]
