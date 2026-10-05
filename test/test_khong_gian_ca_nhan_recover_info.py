from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.05_khong-gian-ca-nhan")


class Input:
    def __init__(self):
        self.taps = []

    def tap(self, x, y):
        self.taps.append((x, y))


class Vision:
    def find_template(self, screen, name, template, threshold):
        found = str(template) in screen
        return SimpleNamespace(match=SimpleNamespace(
            found=found, confidence=1.0 if found else 0.0,
            x=900, y=10, width=58, height=60,
        ))


def test_recover_closes_verified_info_screen_then_proves_home():
    screens = iter([{"info", "info_close"}, {"home"}])
    adb = Input()
    config = module.KhongGianCaNhanConfig(
        entry_templates=[], info_markers=[Path("info")], personal_markers=[],
        close_template=Path("personal_close"), home_markers=[Path("home")],
        like_before=Path("before"), like_after=Path("after"), like_all=Path("all"),
        share_before=Path("share"), share_panel=Path("panel"), share_button=Path("button"),
        share_after=[Path("info")], info_close=Path("info_close"),
    )
    runner = module.KhongGianCaNhanRunner(
        lambda: next(screens), adb, Vision(), config, sleep=lambda _: None,
    )

    assert runner.recover_home() is True
    assert adb.taps == [(929, 40)]
