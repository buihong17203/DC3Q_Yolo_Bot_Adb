from importlib import import_module
from types import SimpleNamespace

from PIL import Image, ImageDraw


module = import_module("app.actions.dc3q.targets.02_hoat-dong")


def test_candidate_is_after_ticks_and_makeup_not_first_blank():
    states = ["tick"] * 9 + ["makeup"] * 20 + ["blank"]
    assert module.HoatDongRunner.next_attendance_index(states) == 29


def test_makeup_ribbon_and_tick_are_both_handled():
    image = Image.new("RGB", (900, 400), (50, 50, 50))
    draw = ImageDraw.Draw(image)
    # First 29 cells: first 9 green tick-like, remaining 20 pale ribbon + green border.
    for index in range(29):
        row, col = divmod(index, 9)
        left, top = col * 100, row * 100
        if index < 9:
            draw.rectangle((left + 20, top + 20, left + 79, top + 79), fill=(117, 135, 29))
        else:
            draw.rectangle((left + 8, top + 18, left + 91, top + 58), fill=(220, 220, 210))
            draw.rectangle((left + 8, top + 18, left + 91, top + 58), outline=(20, 150, 80), width=4)
    runner = module.HoatDongRunner.__new__(module.HoatDongRunner)
    runner.config = SimpleNamespace(attendance_grid=(0, 0, 900, 400), attendance_makeup=None)
    states = runner._attendance_states(SimpleNamespace(data=image))
    assert states[:9] == ["tick"] * 9
    assert states[9:29] == ["makeup"] * 20
    assert states[29] == "blank"
    assert runner._attendance_candidate(image, states) == 29
