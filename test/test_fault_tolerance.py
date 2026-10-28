from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import numpy as np


def test_home_action_random_event_fallback():
    from app.actions.dc3q.stars import HomeAction
    from dataclasses import dataclass

    @dataclass
    class DummyConfig:
        home_events = [
            (
                Path("data/img/templates/random-events/pop-up_random/enemy-raid/screen/screen_dqtk_banner_dichquantapkich.png"),
                Path("data/img/templates/random-events/pop-up_random/enemy-raid/screen/screen_dqtk_button_dong.png"),
                0.75,
            )
        ]
        home_targets = []
        logged_in_confirmations = 2

    mock_input = MagicMock()
    mock_input.recover_anr_wait.return_value = False
    mock_vision = MagicMock()

    # state found = True, close found = False
    state_match = MagicMock(found=True, confidence=0.85)
    close_match = MagicMock(found=False, confidence=0.30)
    mock_vision.find_template.side_effect = lambda img, name, tpl, thresh: MagicMock(
        match=state_match if "state" in name else close_match
    )

    action = HomeAction(mock_input, mock_vision, DummyConfig())
    dummy_img = np.zeros((540, 960, 3), dtype=np.uint8)

    # Should not raise RuntimeError; should fallback tap (794, 106)
    handled = action.handle_known_event(dummy_img)
    assert handled is True
    mock_input.tap.assert_called_with(794, 106)


def test_scene_classifier_random_event_fallback():
    from app.state.scene import SceneClassifier, GameScene

    events = [
        (
            Path("data/img/templates/random-events/pop-up_random/enemy-raid/screen/screen_dqtk_banner_dichquantapkich.png"),
            Path("data/img/templates/random-events/pop-up_random/enemy-raid/screen/screen_dqtk_button_dong.png"),
            0.75,
        )
    ]
    mock_vision = MagicMock()
    state_match = MagicMock(found=True, confidence=0.85)
    close_match = MagicMock(found=False, confidence=0.30)
    mock_vision.find_template.side_effect = lambda img, name, tpl, thresh: MagicMock(
        match=state_match if "state" in name else close_match
    )

    classifier = SceneClassifier(mock_vision, home_events=events)
    dummy_img = np.zeros((540, 960, 3), dtype=np.uint8)
    res = classifier.classify(dummy_img)
    assert res.scene == GameScene.POPUP
    assert res.action_point == (794, 106)


def test_cua_hang_prestige_skip_when_popup_fails():
    # Test that CuaHangRunner._run_prestige handles missing popup without raising RuntimeError
    from dataclasses import dataclass

    @dataclass
    class DummyConfig:
        threshold = 0.70
        paid_threshold = 0.70
        state_threshold = 0.70
        prestige_tab_closed = [Path("closed.png")]
        prestige_tab_open = [Path("open.png")]
        prestige_item = Path("item.png")
        prestige_unit_price = Path("price.png")
        prestige_popup = Path("popup.png")
        prestige_slider_states = [Path("s1.png")]
        prestige_bought = Path("bought.png")
        wait_seconds = 0.01
        sidebar_swipes = 3

    from importlib import import_module
    cua_hang_mod = import_module("app.actions.dc3q.targets.03_cua-hang")
    CuaHangRunner = cua_hang_mod.CuaHangRunner

    mock_input = MagicMock()
    mock_input.recover_anr_wait.return_value = False
    mock_vision = MagicMock()
    mock_screen = MagicMock(return_value=np.zeros((540, 960, 3), dtype=np.uint8))

    runner = CuaHangRunner(mock_screen, mock_input, mock_vision, DummyConfig())
    runner._open_optional_prestige = MagicMock(return_value=(np.zeros((540, 960, 3), dtype=np.uint8), True))
    runner._find_product_state = MagicMock(return_value=(None, "available"))
    # price found, but slider/popup not found
    runner._match = MagicMock(side_effect=lambda scr, tpl, *args, **kwargs: MagicMock(
        found=(tpl == DummyConfig.prestige_item), confidence=0.85
    ))
    runner._match_below_card = MagicMock(return_value=MagicMock(found=True))
    runner._tap = MagicMock()
    runner._wait_for_paid = MagicMock(return_value=(None, None))  # popup did not open

    # Should exit cleanly and not raise RuntimeError
    runner._run_prestige(np.zeros((540, 960, 3), dtype=np.uint8))


def test_out_game_scene_classification_and_recovery():
    from app.state.scene import SceneClassifier, GameScene

    mock_vision = MagicMock()
    mock_vision.find_template.side_effect = lambda img, name, tpl, thresh: MagicMock(
        match=MagicMock(found=(name == "out_game_title"), confidence=0.95)
    )

    classifier = SceneClassifier(
        vision=mock_vision,
        out_game_title=Path("title.png"),
        out_game_confirm=Path("confirm.png"),
    )

    dummy_img = np.zeros((540, 960, 3), dtype=np.uint8)
    res = classifier.classify(dummy_img)
    assert res.scene == GameScene.OUT_GAME
    assert res.action_point == (370, 354)

    # ensure_home should tap the cancel button (370, 354)
    mock_input = MagicMock()
    mock_screen_provider = MagicMock(side_effect=[dummy_img, dummy_img])
    # On 2nd step, make it HOME
    def classify_side_effect(scr, dev=None):
        if mock_screen_provider.call_count == 1:
            return res
        return MagicMock(scene=GameScene.HOME)

    classifier.classify = MagicMock(side_effect=classify_side_effect)
    success = classifier.ensure_home(mock_screen_provider, mock_input, max_steps=2)
    assert success is True
    mock_input.tap.assert_called_with(370, 354)


def test_desktop_scene_focus_classification():
    from app.state.scene import SceneClassifier, GameScene

    mock_vision = MagicMock()
    mock_vision.find_template.return_value = MagicMock(match=MagicMock(found=False))

    classifier = SceneClassifier(vision=mock_vision)
    dummy_img = np.zeros((540, 960, 3), dtype=np.uint8)

    mock_input = MagicMock()
    # Dumpsys output where another app (launcher) is focused, though com.daichien.mobile is listed in background
    mock_input.shell.return_value = (
        "  Window #1 Window{111 com.android.launcher3/com.android.launcher3.Launcher}:\n"
        "  Window #2 Window{222 com.daichien.mobile/com.qtz.game.main.Q2}:\n"
        "  mCurrentFocus=Window{111 u0 com.android.launcher3/com.android.launcher3.Launcher}\n"
        "  mFocusedApp=AppWindowToken{111 token=Token{... com.android.launcher3/.Launcher}}\n"
    )

    res = classifier.classify(dummy_img, input_device=mock_input)
    assert res.scene == GameScene.DESKTOP


def test_truong_thanh_a3_recovery():
    from importlib import import_module
    from dataclasses import dataclass

    @dataclass
    class DummyTTConfig:
        threshold = 0.70
        state_threshold = 0.80
        wait_seconds = 0.01
        hub_markers = []
        home_markers = [Path("home.png")]
        close_templates = []
        entry_templates = [Path("entry.png")]
        menu_templates = []
        bonus_continue_templates = []
        a4_return_templates = []
        flows = []
        a3_markers = [Path("a3_marker.png")]
        a3_tab_open = [Path("a3_open.png")]
        a3_tab_closed = []
        a3_phong_hau_open = []
        a3_raise_flag = []
        a3_result = [Path("a3_result.png")]
        a3_result_dismiss_point = (480, 500)
        a3_close_point = (932, 28)

    tt_mod = import_module("app.actions.dc3q.targets.07_truong-thanh")
    TruongThanhRunner = tt_mod.TruongThanhRunner

    mock_input = MagicMock()
    mock_input.recover_anr_wait.return_value = False
    mock_vision = MagicMock()
    mock_screen = MagicMock(return_value=np.zeros((540, 960, 3), dtype=np.uint8))

    runner = TruongThanhRunner(mock_screen, mock_input, mock_vision, DummyTTConfig())
    call_state = {"a3_open": True}

    def mock_match(scr, tpl, *args, **kwargs):
        if tpl == Path("a3_marker.png"):
            return MagicMock(found=call_state["a3_open"])
        if tpl == Path("home.png"):
            return MagicMock(found=not call_state["a3_open"])
        return MagicMock(found=False)

    def mock_tap(*args, **kwargs):
        call_state["a3_open"] = False

    mock_input.tap.side_effect = mock_tap
    runner._match = MagicMock(side_effect=mock_match)

    recovered = runner.recover_home()
    assert recovered is True
    mock_input.tap.assert_called_with(932, 28)


