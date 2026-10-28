from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock
from importlib import import_module

quan_su = import_module("app.actions.dc3q.targets.09_quan-su")
QuanSuRunner = quan_su.QuanSuRunner
QuanSuConfig = quan_su.QuanSuConfig
from app.vision.template import MatchResult


class TestGiaoTranhBaiMienChien(unittest.TestCase):
    def setUp(self):
        self.adb_input = MagicMock()
        self.vision = MagicMock()
        self.screen_provider = MagicMock(return_value="dummy_screen")
        self.sleep = MagicMock()

        self.config = MagicMock(spec=QuanSuConfig)
        self.config.threshold = 0.60
        self.config.max_steps = 20
        self.config.wait_seconds = 0.01
        self.config.battles = 5
        self.config.military_point = (51, 491)
        self.config.military_close_point = (51, 491)
        self.config.tranh_ba_entry = [Path("tranh_ba_entry.png")]
        self.config.home_markers = [Path("home_noi_chinh.png")]
        self.config.main_markers = [Path("main_tranh_ba.png")]
        self.config.detail_markers = [Path("detail_reward.png")]
        self.config.reward_tab = Path("reward_tab.png")
        self.config.reward_button = Path("reward_button.png")
        self.config.unfinished_markers = [Path("unfinished.png")]
        self.config.close_template = Path("close.png")
        self.config.tui_gam_specs = []
        self.config.gt_bai_mien_chien_title = Path("data/img/templates/targets/09_quan-su/giao-tranh/screen/screen_qs_gt_title_bai-mien-chien.png")
        self.config.gt_bai_mien_chien_confirm = Path("data/img/templates/targets/09_quan-su/giao-tranh/screen/screen_qs_gt_button_xac-nhan.png")
        self.config.gt_find_opponent = Path("gt_find_opp.png")
        self.config.gt_battles = 1

    def _make_match(self, found: bool, confidence: float = 0.9, x: int = 400, y: int = 450, w: int = 80, h: int = 40):
        res = MagicMock()
        res.match = MatchResult(found=found, confidence=confidence, x=x, y=y, width=w, height=h)
        return res

    def test_detect_and_handle_bai_mien_chien_via_template(self):
        """When template matches both title and confirm button, taps confirm button."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )

        def side_effect(screen, task, template, threshold):
            if "title_bai-mien-chien" in str(template):
                return self._make_match(True, 0.95, 260, 120, 411, 42)
            if "button_xac-nhan" in str(template):
                return self._make_match(True, 0.95, 497, 302, 184, 84)
            return self._make_match(False)

        self.vision.find_template.side_effect = side_effect

        handled = runner._handle_bai_mien_chien_popup("dummy_screen", [])
        self.assertTrue(handled)
        # Should tap center of button (497 + 92 = 589, 302 + 42 = 344)
        self.adb_input.tap.assert_called_with(589, 344)

    def test_detect_and_handle_bai_mien_chien_via_ocr(self):
        """When template fails, OCR detects 'bai mien chien' and 'xac nhan'."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )
        self.vision.find_template.return_value = self._make_match(False)
        items = [
            ("ban co bai mien chien", 480, 140),
            ("phat dong cong kich se mat bai mien chien", 480, 200),
            ("xac nhan", 590, 350),
        ]

        handled = runner._handle_bai_mien_chien_popup("dummy_screen", items)
        self.assertTrue(handled)
        self.adb_input.tap.assert_called_with(590, 350)

    def test_fallback_relative_offset_when_button_not_matched(self):
        """When title matches via template but confirm button is not matched, taps calculated offset."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )

        def side_effect(screen, task, template, threshold):
            if "title_bai-mien-chien" in str(template):
                # Title center is at (260 + 205 = 465, 120 + 21 = 141)
                return self._make_match(True, 0.95, 260, 120, 411, 42)
            return self._make_match(False)

        self.vision.find_template.side_effect = side_effect

        handled = runner._handle_bai_mien_chien_popup("dummy_screen", [])
        self.assertTrue(handled)
        # Offset is cx + 122, cy + 203 -> 465 + 122 = 587, 141 + 203 = 344
        self.adb_input.tap.assert_called_with(587, 344)

    def test_battle_casts_tui_gam_before_retreat(self):
        """Verify that run_giao_tranh casts available tui gam in BATTLE phase before retreating."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )
        runner._get_account_level = MagicMock(return_value=50)
        runner._is_home = MagicMock(return_value=False)
        runner._is_battle_ended = MagicMock(return_value=False)

        cast_calls = []
        runner._cast_tui_gam = lambda name, x, y: cast_calls.append(name)
        runner._find_uncast_gt_tui_gam = MagicMock(side_effect=[
            ("cam-lam", 500, 450),
            ("loi-kich", 600, 450),
            None,
        ])
        runner._ocr_items = MagicMock(return_value=[("thu quan", 77, 361)])
        runner._retreat_confirm = MagicMock(return_value=None)
        runner.recover_home = MagicMock(return_value=True)

        # Run 1 battle from BATTLE phase
        # It should cast cam-lam, then loi-kich, and then retreat
        runner.config.max_steps = 4
        try:
            runner.run_giao_tranh(start_phase="BATTLE", battles_completed=0)
        except Exception:
            pass

        self.assertEqual(cast_calls, ["cam-lam", "loi-kich"])



if __name__ == "__main__":
    unittest.main()
