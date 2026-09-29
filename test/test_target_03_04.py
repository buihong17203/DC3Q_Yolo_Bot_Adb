from importlib import import_module
from pathlib import Path
from types import SimpleNamespace


class Match:
    def __init__(self, found=False, confidence=0.0, x=10, y=20, width=30, height=40):
        self.found = found
        self.confidence = confidence
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class Vision:
    def find_template(self, screen, _group, template, threshold):
        name = Path(template).name
        found = name in screen
        return SimpleNamespace(match=Match(found, 0.99 if found else 0.0))


class Input:
    def __init__(self):
        self.taps = []
    def tap(self, x, y):
        self.taps.append((x, y))


def seq(*screens):
    items = list(screens)
    last = items[-1]
    def provider():
        return items.pop(0) if items else last
    return provider


def test_cua_hang_claims_daily_gift_only_then_closes_home():
    module = import_module("app.actions.dc3q.targets.03_cua-hang")
    taps = Input()
    cfg = module.CuaHangConfig(
        entry_templates=[Path("screen_cua-hang_01.png")],
        menu_templates=[Path("screen_home_morong_chamthan.png")],
        panel_markers=[Path("screen_ch_cuahanggoiy_open_01.png")],
        close_template=Path("screen_button_dong_03cuahang.png"),
        home_markers=[Path("screen_noi-chinh_01.png")],
        gift_tab_closed=[Path("screen_ch_cuahanggoiy_close_01.png")],
        gift_tab_open=[Path("screen_ch_cuahanggoiy_open_01.png")],
        daily_unclaimed=Path("screen_ch_chgy_button_quahangngay_chuamua.png"),
        daily_claimed=Path("screen_ch_chgy_button_quahangngay_damua.png"),
        reward_marker=Path("screen_ch_chgy_chucmungnhandc.png"),
        reward_dismiss=Path("screen_ch_chgy_anvaochotrongdethoat.png"),
        wait_seconds=0,
    )
    runner = module.CuaHangRunner(seq(
        {"screen_home_morong_chamthan.png"},
        {"screen_cua-hang_01.png"},
        {"screen_ch_cuahanggoiy_open_01.png", "screen_ch_chgy_button_quahangngay_chuamua.png"},
        {"screen_ch_chgy_chucmungnhandc.png", "screen_ch_chgy_anvaochotrongdethoat.png"},
        {"screen_ch_cuahanggoiy_open_01.png", "screen_ch_chgy_button_quahangngay_damua.png", "screen_button_dong_03cuahang.png"},
        {"screen_noi-chinh_01.png"},
    ), taps, Vision(), cfg, sleep=lambda _: None)
    assert runner.run() is True
    assert len(taps.taps) == 5


def test_cua_hang_fails_closed_on_unproven_paid_shop_state():
    module = import_module("app.actions.dc3q.targets.03_cua-hang")
    cfg = module.CuaHangConfig(
        entry_templates=[Path("screen_cua-hang_01.png")],
        menu_templates=[], panel_markers=[Path("screen_ch_cuahanggoiy_open_01.png")],
        close_template=Path("screen_button_dong_03cuahang.png"), home_markers=[Path("screen_noi-chinh_01.png")],
        gift_tab_closed=[], gift_tab_open=[Path("screen_ch_cuahanggoiy_open_01.png")],
        daily_unclaimed=Path("screen_ch_chgy_button_quahangngay_chuamua.png"),
        daily_claimed=Path("screen_ch_chgy_button_quahangngay_damua.png"),
        reward_marker=Path("screen_ch_chgy_chucmungnhandc.png"),
        reward_dismiss=Path("screen_ch_chgy_anvaochotrongdethoat.png"), max_steps=3, wait_seconds=0,
    )
    runner = module.CuaHangRunner(seq({"screen_cua-hang_01.png"}, {"screen_ch_cuahanggoiy_open_01.png", "screen_ch_ttb_3chieuhienlenh_chuamua.png"}), Input(), Vision(), cfg, sleep=lambda _: None)
    try:
        runner.run()
    except RuntimeError as exc:
        assert "không xác định" in str(exc) or "không an toàn" in str(exc)
    else:
        raise AssertionError("expected fail closed")


def test_quan_doan_runs_free_cau_van_when_available_then_closes_home():
    module = import_module("app.actions.dc3q.targets.04_quan-doan")
    taps = Input()
    cfg = module.QuanDoanConfig(
        entry_templates=[Path("screen_quan-doan_01.png")],
        menu_templates=[Path("screen_home_morong_chamthan.png")],
        panel_markers=[Path("screen_button_dong_04quandoan.png")],
        close_template=Path("screen_button_dong_04quandoan.png"),
        home_markers=[Path("screen_noi-chinh_01.png")],
        prayer_tabs=[Path("screen_qd_tab_cauvanquandoan_01.png")],
        prayer_open=[Path("screen_qd_tab_cauvanquandoan_02.png")],
        prayer_available=Path("screen_qd_cvqd_button_10cauvan.png"),
        prayer_empty=Path("screen_qd_cvqd_button_0cauvan.png"),
        prayer_close=Path("screen_qd_cvqd_button_dong.png"),
        wait_seconds=0,
    )
    runner = module.QuanDoanRunner(seq(
        {"screen_home_morong_chamthan.png"},
        {"screen_quan-doan_01.png"},
        {"screen_button_dong_04quandoan.png", "screen_qd_tab_cauvanquandoan_01.png"},
        {"screen_qd_tab_cauvanquandoan_02.png", "screen_qd_cvqd_button_10cauvan.png", "screen_qd_cvqd_button_dong.png"},
        {"screen_qd_tab_cauvanquandoan_02.png", "screen_qd_cvqd_button_0cauvan.png", "screen_qd_cvqd_button_dong.png"},
        {"screen_button_dong_04quandoan.png"},
        {"screen_noi-chinh_01.png"},
    ), taps, Vision(), cfg, sleep=lambda _: None)
    assert runner.run() is True
    assert len(taps.taps) == 6


def test_quan_doan_recover_home_closes_known_layers_only():
    module = import_module("app.actions.dc3q.targets.04_quan-doan")
    taps = Input()
    cfg = module.QuanDoanConfig(
        entry_templates=[], menu_templates=[], panel_markers=[Path("screen_button_dong_04quandoan.png")],
        close_template=Path("screen_button_dong_04quandoan.png"), home_markers=[Path("screen_noi-chinh_01.png")],
        prayer_tabs=[], prayer_open=[], prayer_available=Path("screen_qd_cvqd_button_10cauvan.png"),
        prayer_empty=Path("screen_qd_cvqd_button_0cauvan.png"), prayer_close=Path("screen_qd_cvqd_button_dong.png"), wait_seconds=0,
    )
    runner = module.QuanDoanRunner(seq({"screen_qd_cvqd_button_dong.png"}, {"screen_button_dong_04quandoan.png"}, {"screen_noi-chinh_01.png"}), taps, Vision(), cfg, sleep=lambda _: None)
    assert runner.recover_home() is True
    assert len(taps.taps) == 2
