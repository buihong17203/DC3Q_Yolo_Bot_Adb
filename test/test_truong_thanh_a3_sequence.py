from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit(name, confidence=1.0):
    return SimpleNamespace(found=True, confidence=confidence, name=name, x=10, y=20, width=20, height=10)


def miss(name, confidence=0.0):
    return SimpleNamespace(found=False, confidence=confidence, name=name, x=0, y=0, width=0, height=0)


def test_a3_selects_chien_ky_raises_flag_dismisses_result_then_closes_panel():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a3_phong_hau_open=["phong_hau"],
        a3_tab_closed=["chien_ky_closed"], a3_tab_open=["chien_ky_open"],
        a3_raise_flag=["raise_flag"], a3_result=["result"],
        a3_result_dismiss_point=(480, 500), a3_close_point=(926, 34),
        threshold=.70, state_margin=.05, wait_seconds=0,
    )
    runner.sleep = lambda _: None
    runner._open_home_entry = lambda: None
    runner._tap_a3_entry = lambda screen: actions.append("open_chua_cong")
    screens = iter(["hub", "phong_hau", "chien_ky", "result", "chien_ky_after", "closed"])
    runner.screen_provider = lambda: next(screens)
    actions = []
    runner.input = SimpleNamespace(tap=lambda x, y: actions.append((x, y)))
    runner._tap = lambda match: actions.append(match.name)

    def first(screen, templates, threshold=None):
        states = {
            ("phong_hau", ("chien_ky_closed",)): "chien_ky_closed",
            ("chien_ky", ("chien_ky_open",)): "chien_ky_open",
            ("chien_ky", ("raise_flag",)): "raise_flag",
            ("result", ("result",)): "result",
            ("chien_ky_after", ("chien_ky_open",)): "chien_ky_open",
        }
        name = states.get((screen, tuple(templates)))
        return hit(name) if name else None

    runner._first = first
    runner._match = lambda screen, template, threshold=None: (
        hit(template, 1.0) if first(screen, [template], threshold) else miss(template, .2)
    )
    waits = iter([
        ("phong_hau", hit("chien_ky_closed")),
        ("chien_ky", hit("chien_ky_open")),
        ("result", hit("result")),
        ("chien_ky_after", hit("chien_ky_open")),
    ])
    runner._wait_first = lambda templates, attempts=6, threshold=None: next(waits)

    runner._run_a3()

    assert actions == [
        "open_chua_cong", "chien_ky_closed", "raise_flag",
        (480, 500), (926, 34),
    ]


def test_a3_phong_hau_proof_forces_chien_ky_click_despite_open_collision():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a3_phong_hau_open=["phong_hau"], a3_tab_closed=["closed"],
        a3_tab_open=["open"], a3_raise_flag=["flag"],
        threshold=.70, state_margin=.05,
    )
    actions = []
    runner._tap = lambda match: actions.append(match.name)
    runner._first = lambda screen, templates, threshold=None: (
        hit("phong_hau") if screen == "phong_hau_screen" and templates == ["phong_hau"] else
        hit("closed", .86) if screen == "phong_hau_screen" and templates == ["closed"] else None
    )
    runner._match = lambda screen, template, threshold=None: (
        hit("open", 1.0) if template == "open" else hit("closed", .86)
    )
    runner._wait_first = lambda templates, attempts=6, threshold=None: (
        ("chien_ky_screen", hit("flag"))
    )

    screen = runner._open_a3_chien_ky("phong_hau_screen")

    assert screen == "chien_ky_screen"
    assert actions == ["closed"]


def test_a3_open_chien_ky_without_raise_flag_is_already_done():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a3_phong_hau_open=["phong_hau"], a3_tab_closed=["closed"],
        a3_tab_open=["open"], a3_raise_flag=["flag"],
        threshold=.70, state_margin=.05,
    )
    actions = []
    runner._tap = lambda match: actions.append(match.name)
    runner._first = lambda screen, templates, threshold=None: (
        hit("phong_hau") if screen == "phong_hau" and templates == ["phong_hau"] else
        hit("closed") if screen == "phong_hau" and templates == ["closed"] else None
    )
    runner._match = lambda screen, template, threshold=None: miss(template)
    runner._wait_first = lambda templates, attempts=6, threshold=None: (
        ("chien_ky_done", hit("open"))
        if templates == ["flag", "open"] else
        (_ for _ in ()).throw(AssertionError(f"unexpected wait: {templates}"))
    )

    screen = runner._open_a3_chien_ky("phong_hau")

    assert screen == "chien_ky_done"
    assert actions == ["closed"]
