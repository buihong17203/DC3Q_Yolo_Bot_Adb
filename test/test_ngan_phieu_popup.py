from pathlib import Path
from unittest.mock import MagicMock
import cv2
import yaml
import pytest

from app.actions.dc3q.stars import HomeAction
from app.main import load_login_random_events


def test_ngan_phieu_templates_exist_and_match():
    p_btn = Path("data/img/templates/random-events/pop-up_random/ngan-phieu/screen/screen_nganphieu_button_dong.png")
    p_title = Path("data/img/templates/random-events/pop-up_random/ngan-phieu/screen/screen_nganphieu_title.png")
    p_tabs = Path("data/img/templates/random-events/pop-up_random/ngan-phieu/screen/screen_tainguyen_tabs.png")
    p_full_np = Path("data/img/templates/random-events/pop-up_random/ngan-phieu/full screen/full-screen_popup_nganphieu_01.png")
    p_full_tn = Path("data/img/templates/random-events/pop-up_random/ngan-phieu/full screen/full-screen_popup_tainguyen_01.png")

    assert p_btn.exists()
    assert p_title.exists()
    assert p_tabs.exists()
    assert p_full_np.exists()
    assert p_full_tn.exists()

    btn = cv2.imread(str(p_btn))
    title = cv2.imread(str(p_title))
    tabs = cv2.imread(str(p_tabs))
    full_np = cv2.imread(str(p_full_np))
    full_tn = cv2.imread(str(p_full_tn))

    # Button X matches on both popups with confidence > 0.95
    conf_np_btn = cv2.minMaxLoc(cv2.matchTemplate(full_np, btn, cv2.TM_CCOEFF_NORMED))[1]
    conf_tn_btn = cv2.minMaxLoc(cv2.matchTemplate(full_tn, btn, cv2.TM_CCOEFF_NORMED))[1]
    assert conf_np_btn > 0.95
    assert conf_tn_btn > 0.95

    # Title matches on Ngân phiếu popup
    conf_title = cv2.minMaxLoc(cv2.matchTemplate(full_np, title, cv2.TM_CCOEFF_NORMED))[1]
    assert conf_title > 0.95

    # Tabs match on Tài nguyên popup
    conf_tabs = cv2.minMaxLoc(cv2.matchTemplate(full_tn, tabs, cv2.TM_CCOEFF_NORMED))[1]
    assert conf_tabs > 0.95


def test_dang_nhap_config_loads_ngan_phieu_events():
    cfg_path = Path("config/dc3q/stars/dang-nhap.yaml")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    unexpected = cfg.get("login", {}).get("unexpected", {})

    assert "ngan_phieu" in unexpected
    assert "tai_nguyen" in unexpected

    events = load_login_random_events(Path("."), unexpected)
    event_states = [str(e[0]) for e in events]
    assert any("screen_nganphieu_title.png" in s for s in event_states)
    assert any("screen_tainguyen_tabs.png" in s for s in event_states)


def test_home_action_detects_and_closes_ngan_phieu():
    full_np = cv2.imread("data/img/templates/random-events/pop-up_random/ngan-phieu/full screen/full-screen_popup_nganphieu_01.png")
    
    mock_input = MagicMock()
    from app.vision.detector import VisionDetector
    vision = VisionDetector()

    home_action = HomeAction(
        adb_input=mock_input,
        vision=vision,
        config=MagicMock(home_events=[]),
    )

    handled = home_action.handle_known_event(full_np)
    assert handled is True
    # Button center: x ~ 929, y ~ 29
    mock_input.tap.assert_called_once()
    tap_x, tap_y = mock_input.tap.call_args[0]
    assert 925 <= tap_x <= 935
    assert 25 <= tap_y <= 35
