from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock
from importlib import import_module

quan_su = import_module("app.actions.dc3q.targets.09_quan-su")
QuanSuRunner = quan_su.QuanSuRunner
QuanSuConfig = quan_su.QuanSuConfig
from app.vision.template import MatchResult


class TestTranhBaReward(unittest.TestCase):
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

    def _make_match(self, found: bool, confidence: float = 0.9, x: int = 400, y: int = 450, w: int = 80, h: int = 40):
        res = MagicMock()
        res.match = MatchResult(found=found, confidence=confidence, x=x, y=y, width=w, height=h)
        return res

    def test_find_reward_button_template(self):
        """When template matches reward_button, returns its center coordinate."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )
        self.vision.find_template.return_value = self._make_match(True, 0.95, 396, 461, 169, 57)
        pt = runner._find_reward_button("screen", [])
        self.assertIsNotNone(pt)
        self.assertEqual(pt, (396 + 84, 461 + 28))

    def test_find_reward_button_ocr_fallback(self):
        """When template fails, OCR detects 'nhan thuong' or 'nhan va mo'."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )
        self.vision.find_template.return_value = self._make_match(False)
        items = [("nhan thuong", 480, 460), ("chi tiet thuong", 480, 100)]
        pt = runner._find_reward_button("screen", items)
        self.assertEqual(pt, (480, 460))

    def test_find_reward_button_already_claimed(self):
        """When neither template nor OCR finds reward button, returns None (already claimed)."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )
        self.vision.find_template.return_value = self._make_match(False)
        items = [("chua ket thuc", 480, 460), ("chi tiet thuong", 480, 100)]
        pt = runner._find_reward_button("screen", items)
        self.assertIsNone(pt)

    def test_close_reward_detail(self):
        """_close_reward_detail taps close button."""
        runner = QuanSuRunner(
            screen_provider=self.screen_provider,
            adb_input=self.adb_input,
            vision=self.vision,
            config=self.config,
            sleep=self.sleep,
        )
        self.vision.find_template.return_value = self._make_match(True, 0.9, 778, 69, 50, 50)
        runner._close_reward_detail("screen", [])
        self.adb_input.tap.assert_called_with(778 + 25, 69 + 25)


if __name__ == "__main__":
    unittest.main()
