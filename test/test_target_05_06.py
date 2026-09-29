from pathlib import Path
import importlib

import yaml
from app.vision.template import MatchResult

ROOT = Path(__file__).parents[1]


class FakeInput:
    def __init__(self):
        self.taps = []
    def tap(self, x, y):
        self.taps.append((x, y))


class FakeVision:
    def __init__(self, states):
        self.states = states
        self.index = 0
    def next_screen(self):
        screen = f"s{self.index}"
        self.index += 1
        return screen
    def find_template(self, screen, name, template, threshold=0.85):
        path = str(template).replace("\\", "/")
        key = path.rsplit("/", 1)[-1]
        found = key in self.states.get(screen, set())
        return type("D", (), {"match": MatchResult(found, 0.99 if found else 0.0, 10, 20, 30, 40)})()


def load(rel):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def test_target_05_config_uses_only_existing_pngs_and_safe_states():
    cfg = load("config/dc3q/targets/05_khong-gian-ca-nhan.yaml")["khong_gian_ca_nhan"]
    assert cfg["max_steps"] > 0
    assert cfg["like"]["before"].endswith("screen_kgcn_chualike.png")
    assert cfg["like"]["after"].endswith("screen_kgcn_dalike.png")
    for group in ("home", "info", "personal", "like", "share", "panel"):
        for value in cfg[group].values():
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, str) and item.endswith(".png"):
                    assert (ROOT / item).is_file(), item


def test_target_06_config_uses_only_existing_pngs_and_safe_states():
    cfg = load("config/dc3q/targets/06_xa-giao.yaml")["xa_giao"]
    assert cfg["max_steps"] > 0
    assert cfg["heart"]["before"].endswith("screen_xg_bb_tim_chuatang.png")
    assert cfg["heart"]["after"].endswith("screen_xg_bb_tim_datang.png")
    assert cfg["quick_give"]["before"].endswith("screen_xg_bb_button_tangnhanh_chuabam.png")
    assert cfg["quick_give"]["after"].endswith("screen_xg_bb_button_tangnhanh_dabam.png")
    for group in ("home", "panel", "heart", "quick_give"):
        for value in cfg[group].values():
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, str) and item.endswith(".png"):
                    assert (ROOT / item).is_file(), item


def test_target_05_taps_template_center_then_requires_like_postcondition():
    m = importlib.import_module("app.actions.dc3q.targets.05_khong-gian-ca-nhan")
    cfg = m.KhongGianCaNhanConfig(
        entry_templates=[Path("screen_ttct_button_open_khonggiancanhan.png")],
        info_markers=[Path("full-screen_thongtincuatoi_01.png")],
        personal_markers=[Path("full-screen_khonggiancanhan_01.png")],
        close_template=Path("screen_kgcn_button_dong.png"),
        home_markers=[Path("full-screen_thongtincuatoi_01.png")],
        like_before=Path("screen_kgcn_chualike.png"),
        like_after=Path("screen_kgcn_dalike.png"),
        share_before=Path("screen_ttct_chiase.png"),
        share_panel=Path("full-screen_chiase.png"),
        share_button=Path("screen_chiase_chiase.png"),
        share_after=[Path("full-screen_thongtincuatoi_01.png")],
        max_steps=6,
        wait_seconds=0,
    )
    vision = FakeVision({
        "s0": {"screen_ttct_button_open_khonggiancanhan.png"},
        "s1": {"full-screen_khonggiancanhan_01.png", "screen_kgcn_chualike.png", "screen_kgcn_button_dong.png"},
        "s2": {"full-screen_khonggiancanhan_01.png", "screen_kgcn_dalike.png", "screen_kgcn_button_dong.png"},
        "s3": {"full-screen_khonggiancanhan_01.png", "screen_kgcn_dalike.png", "screen_kgcn_button_dong.png"},
        "s4": {"full-screen_thongtincuatoi_01.png"},
    })
    inp = FakeInput()
    assert m.KhongGianCaNhanRunner(vision.next_screen, inp, vision, cfg, sleep=lambda _: None).run()
    assert inp.taps[:2] == [(25, 40), (25, 40)]


def test_target_05_fails_closed_when_like_after_missing():
    m = importlib.import_module("app.actions.dc3q.targets.05_khong-gian-ca-nhan")
    cfg = m.KhongGianCaNhanConfig(
        entry_templates=[Path("screen_ttct_button_open_khonggiancanhan.png")],
        info_markers=[Path("full-screen_thongtincuatoi_01.png")],
        personal_markers=[Path("full-screen_khonggiancanhan_01.png")],
        close_template=Path("screen_kgcn_button_dong.png"),
        home_markers=[Path("full-screen_thongtincuatoi_01.png")],
        like_before=Path("screen_kgcn_chualike.png"),
        like_after=Path("screen_kgcn_dalike.png"),
        share_before=Path("screen_ttct_chiase.png"),
        share_panel=Path("full-screen_chiase.png"),
        share_button=Path("screen_chiase_chiase.png"),
        share_after=[Path("full-screen_thongtincuatoi_01.png")],
        max_steps=4,
        wait_seconds=0,
    )
    vision = FakeVision({
        "s0": {"screen_ttct_button_open_khonggiancanhan.png"},
        "s1": {"full-screen_khonggiancanhan_01.png", "screen_kgcn_chualike.png"},
    })
    try:
        m.KhongGianCaNhanRunner(vision.next_screen, FakeInput(), vision, cfg, sleep=lambda _: None).run()
    except RuntimeError as exc:
        assert "hậu điều kiện" in str(exc)
    else:
        raise AssertionError("missing postcondition must fail closed")


def test_target_06_taps_centers_then_requires_heart_and_quick_give_postconditions():
    m = importlib.import_module("app.actions.dc3q.targets.06_xa-giao")
    cfg = m.XaGiaoConfig(
        entry_templates=[Path("screen_banbe_entry.png")],
        menu_templates=[],
        panel_markers=[Path("full-screen_banbe_listbanbe_01.png")],
        close_template=Path("screen_xg_bb_button_dong_banbe.png"),
        home_markers=[Path("home.png")],
        heart_before=Path("screen_xg_bb_tim_chuatang.png"),
        heart_after=Path("screen_xg_bb_tim_datang.png"),
        quick_before=Path("screen_xg_bb_button_tangnhanh_chuabam.png"),
        quick_after=Path("screen_xg_bb_button_tangnhanh_dabam.png"),
        max_steps=8,
        wait_seconds=0,
    )
    vision = FakeVision({
        "s0": {"screen_banbe_entry.png"},
        "s1": {"full-screen_banbe_listbanbe_01.png", "screen_xg_bb_tim_chuatang.png", "screen_xg_bb_button_tangnhanh_chuabam.png", "screen_xg_bb_button_dong_banbe.png"},
        "s2": {"full-screen_banbe_listbanbe_01.png", "screen_xg_bb_tim_datang.png", "screen_xg_bb_button_tangnhanh_chuabam.png", "screen_xg_bb_button_dong_banbe.png"},
        "s3": {"full-screen_banbe_listbanbe_01.png", "screen_xg_bb_tim_datang.png", "screen_xg_bb_button_tangnhanh_dabam.png", "screen_xg_bb_button_dong_banbe.png"},
        "s4": {"home.png"},
    })
    inp = FakeInput()
    assert m.XaGiaoRunner(vision.next_screen, inp, vision, cfg, sleep=lambda _: None).run()
    assert inp.taps == [(25, 40), (25, 40), (25, 40), (25, 40)]


def test_numbered_scripts_reference_numbered_configs():
    assert load("scripts/dc3q/targets/05_khong-gian-ca-nhan.yaml")["config"] == "config/dc3q/targets/05_khong-gian-ca-nhan.yaml"
    assert load("scripts/dc3q/targets/06_xa-giao.yaml")["config"] == "config/dc3q/targets/06_xa-giao.yaml"
