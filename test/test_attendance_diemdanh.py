from importlib import import_module
from pathlib import Path
from PIL import Image
import numpy as np
import pytest

hoat_dong = import_module("app.actions.dc3q.targets.02_hoat-dong")
cua_hang = import_module("app.actions.dc3q.targets.03_cua-hang")


class DummyInput:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, *args):
        pass


def test_ocr_center_defined_on_runners():
    """Verify _find_ocr_center exists on both runners to prevent AttributeError."""
    assert hasattr(hoat_dong.HoatDongRunner, "_find_ocr_center")
    assert hasattr(cua_hang.CuaHangRunner, "_find_ocr_center")


def test_tick_pixels_detection():
    """Verify that _tick_pixels properly counts green tick marks on RGB PIL image inputs."""
    img_path = Path("data/img/templates/targets/02_hoat-dong/phuc-loi/full screen/full-screen_hd_pl_diemdanh_01.png")
    if not img_path.is_file():
        pytest.skip("Test image not found")

    pil_img = Image.open(img_path).convert("RGB")
    # Grid offset by 35px title bar on window capture
    grid = [238, 199 + 35, 913, 500 + 35]
    x1, y1, x2, y2 = grid
    width, height = x2 - x1, y2 - y1

    # Cell 0 (Day 1) has a green checkmark
    c0 = pil_img.crop((x1, y1, x1 + round(width / 9), y1 + round(height / 4)))
    c0_ticks = hoat_dong.HoatDongRunner._tick_pixels(c0)
    assert c0_ticks >= 150, f"Expected Day 1 to have >= 150 tick pixels, got {c0_ticks}"

    # Cell 26 (Day 27) does not have a green checkmark
    row, col = divmod(26, 9)
    left = x1 + round(col * width / 9)
    right = x1 + round((col + 1) * width / 9)
    top = y1 + round(row * height / 4)
    bottom = y1 + round((row + 1) * height / 4)
    c26 = pil_img.crop((left, top, right, bottom))
    c26_ticks = hoat_dong.HoatDongRunner._tick_pixels(c26)
    assert c26_ticks < 150, f"Expected Day 27 to have < 150 tick pixels, got {c26_ticks}"


def test_qua_online_not_falsely_detected_as_attendance_open():
    """Verify that on Quà Online screen, _tab_state returns 'closed' with high confidence for Điểm danh."""
    qua_path = Path("data/img/templates/targets/02_hoat-dong/phuc-loi/full screen/full-screen_hd_pl_quaonline_01.png")
    if not qua_path.is_file():
        pytest.skip("Test image not found")

    from app.vision.detector import VisionDetector
    vision = VisionDetector()
    dummy_input = DummyInput()

    class Config:
        threshold = 0.65
        attendance_tabs = [
            Path("data/img/templates/targets/02_hoat-dong/phuc-loi/screen/screen_hd_pl_tab_diemdanh_close_01.png"),
            Path("data/img/templates/targets/02_hoat-dong/phuc-loi/screen/screen_hd_pl_tab_diemdanh_close_02.png"),
        ]
        attendance_open = [
            Path("data/img/templates/targets/02_hoat-dong/phuc-loi/screen/screen_hd_pl_tab_diemdanh_open_01.png"),
            Path("data/img/templates/targets/02_hoat-dong/phuc-loi/screen/screen_hd_pl_tab_diemdanh_open_02.png"),
        ]

    runner = hoat_dong.HoatDongRunner(
        screen_provider=lambda: None,
        adb_input=dummy_input,
        vision=vision,
        config=Config(),
    )

    screen = Image.open(qua_path)
    state, open_match, closed_match = runner._tab_state(screen, Config.attendance_tabs, Config.attendance_open)
    assert state == "closed", f"Expected tab state 'closed' on Quà Online screen, got '{state}'"
    assert closed_match.confidence >= 0.90, f"Expected closed match >= 0.90, got {closed_match.confidence}"
    assert closed_match.y >= 350, f"Expected closed match y >= 350, got {closed_match.y}"
