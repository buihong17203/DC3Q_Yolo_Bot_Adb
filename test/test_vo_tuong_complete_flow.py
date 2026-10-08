from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.08_vo-tuong")


def test_chiem_tinh_readiness_uses_stable_plus_controls():
    import yaml
    from pathlib import Path

    config = yaml.safe_load(Path("config/dc3q/targets/08_vo-tuong.yaml").read_text(encoding="utf-8"))["vo_tuong"]
    markers = config["chiem_tinh"]["markers"]
    assert config["chiem_tinh"]["plus"][0].endswith("screen_vt_chiemtinh_button_cong_02.jpg")
    assert all("soluong_5" not in actuator for actuator in config["chiem_tinh"]["plus"])
    assert all("full screen" not in marker for marker in markers)


def hit(name):
    return SimpleNamespace(found=True, confidence=1.0, x=10, y=20, width=20, height=10, name=name)


def test_complete_flow_preserves_user_order_and_never_taps_paid_controls():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(
        entry_templates=["home_entry"], menu_templates=["menu"], home_markers=["home"],
        kho_markers=["kho"], point_button="point", point_markers=["point_screen"],
        thien_van_banner="thien_van", thien_van_markers=["thien_free", "one_order"],
        thien_van_paid="one_order", nhan_duc_banner="nhan_duc",
        nhan_duc_markers=["nhan_free", "25_soul"], nhan_duc_free="nhan_free",
        nhan_duc_paid="25_soul", chiem_tinh_banner="chiem_tinh",
        chiem_tinh_markers=["chiem_screen"], chiem_tinh_plus=["plus_full", "plus"],
        exchange_popup=["popup_title", "popup_full"], exchange_slider_max="slider_max",
        exchange_confirm_point=(482, 405), exchange_slider_start=(400, 332),
        exchange_slider_end=(610, 332), exchange_reward=["reward_title", "reward_exit"],
        exchange_reward_dismiss_point=(760, 430), close_template="x",
        reward_marker="draw_reward", reward_dismiss="return", threshold=.7,
        action_threshold=.8, state_margin=.05, close_threshold=.54,
        max_steps=40, wait_seconds=0,
    )
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: "screen"
    taps = []
    runner._tap = lambda m: taps.append(m.name)
    runner.input = SimpleNamespace(
        tap=lambda x, y: taps.append((x, y)),
        swipe=lambda x1, y1, x2, y2, duration_ms=500: taps.append((x1, y1, x2, y2)),
    )
    runner._first = lambda screen, templates, threshold=None: hit(templates[0])
    runner._match = lambda screen, template, threshold=None: hit(template)
    runner._wait_first = lambda templates, attempts=12, threshold=None: ("screen", hit(templates[0]))
    runner._thien_van_free = lambda: ("screen", hit("thien_free"))
    runner._nhan_duc_free = lambda: ("screen", hit("nhan_free"))
    runner._close_layer = lambda expected: "screen"
    runner._run_exchange = lambda: (
        runner._tap(hit("plus_full")),
        runner.input.swipe(400, 332, 610, 332),
        runner.input.tap(482, 405),
        runner.input.tap(760, 430),
    )
    runner._close_to_home = lambda: True

    assert runner.run() is True
    assert taps == [
        "home_entry", "point",
        "thien_van", "thien_free", "return",
        "nhan_duc", "nhan_free", "return",
        "chiem_tinh", "plus_full",
        (400, 332, 610, 332), (482, 405), (760, 430),
    ]
    assert "one_order" not in taps
    assert "25_soul" not in taps


def test_exchange_retries_plus_once_only_while_plus_screen_remains_proven():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(
        chiem_tinh_markers=["screen"], chiem_tinh_plus=["plus"],
        exchange_popup=["popup"], exchange_slider_max="slider",
        exchange_slider_start=(1, 2), exchange_slider_end=(3, 4),
        exchange_confirm_point=(5, 6), exchange_reward=["reward"],
        exchange_reward_dismiss_point=(7, 8), wait_seconds=0,
    )
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: "fresh"
    taps = []
    runner._tap = lambda found: taps.append(found.name)
    runner.input = SimpleNamespace(swipe=lambda *args: None, tap=lambda *args: None)
    waits = iter([("screen", hit("screen")), ("reward", hit("reward"))])
    popups = iter([("screen", None), ("popup", hit("popup"))])
    runner._wait_first = lambda *args, **kwargs: next(waits)
    runner._wait_exchange_popup = lambda attempts=4: next(popups)
    runner._has_exchange_popup_text = lambda screen: True
    runner._has_insufficient_exchange_text = lambda screen: False
    runner._first = lambda screen, templates, threshold=None: (
        None if templates == ["reward"] else hit(templates[0])
    )
    runner._match = lambda *args, **kwargs: hit("slider")

    runner._run_exchange()

    assert taps == ["plus", "plus"]


def test_exchange_treats_insufficient_orders_as_safe_terminal_without_retry():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(
        chiem_tinh_markers=["screen"], chiem_tinh_plus=["open_popup"],
    )
    taps = []
    runner._wait_first = lambda *args, **kwargs: ("screen", hit("screen"))
    runner._first = lambda screen, templates, threshold=None: hit(templates[0])
    runner._tap = lambda found: taps.append(found.name)
    runner._wait_exchange_popup = lambda attempts=4: ("insufficient", False)
    runner._has_insufficient_exchange_text = lambda screen: screen == "insufficient"

    assert runner._run_exchange() == "insufficient"
    assert taps == ["open_popup"]


def test_popup_waiter_latches_transient_insufficient_orders_message():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(exchange_popup=["popup"], wait_seconds=0)
    screens = iter(["normal", "insufficient", "normal"])
    runner.screen_provider = lambda: next(screens)
    runner._first = lambda *args, **kwargs: None
    runner._has_exchange_popup_text = lambda screen: False
    runner._has_insufficient_exchange_text = lambda screen: screen == "insufficient"
    runner.sleep = lambda _: None

    assert runner._wait_exchange_popup(attempts=3) == ("insufficient", False)


def test_exchange_falls_back_to_exactly_two_popup_plus_taps_without_rechecking_max():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(
        chiem_tinh_markers=["screen"], chiem_tinh_plus=["open_popup"],
        exchange_popup=["popup"], exchange_slider_max="slider_max",
        exchange_slider_start=(1, 2), exchange_slider_end=(3, 4),
        exchange_quantity_plus_point=(643, 297), exchange_confirm_point=(5, 6),
        exchange_reward=["reward"], exchange_reward_dismiss_point=(7, 8), wait_seconds=0,
    )
    actions = []
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: "fresh"
    runner.input = SimpleNamespace(
        swipe=lambda *args: actions.append(("swipe", args)),
        tap=lambda *point: actions.append(("tap", point)),
    )
    runner._tap = lambda found: actions.append(("open", found.name))
    runner._wait_exchange_popup = lambda attempts=4: ("popup", hit("popup"))
    waits = iter([("screen", hit("screen")), ("reward", hit("reward"))])
    runner._wait_first = lambda *args, **kwargs: next(waits)
    runner._first = lambda screen, templates, threshold=None: (
        None if templates == ["reward"] else hit(templates[0])
    )
    slider_checks = []
    runner._match = lambda screen, template, threshold=None: (
        slider_checks.append(template) or SimpleNamespace(found=False)
    )
    runner._has_exchange_popup_text = lambda screen: True

    runner._run_exchange()

    assert slider_checks == ["slider_max"]
    assert actions == [
        ("open", "open_popup"),
        ("swipe", (1, 2, 3, 4, 700)),
        ("tap", (643, 297)),
        ("tap", (643, 297)),
        ("tap", (5, 6)),
        ("tap", (7, 8)),
    ]


def test_paid_draw_states_use_return_without_tapping_currency_controls():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(
        thien_van_paid="one_order", nhan_duc_paid="25_soul",
        reward_dismiss="return", point_markers=["point_screen"],
    )
    taps = []
    runner._tap = lambda m: taps.append(m.name)
    runner._match = lambda screen, template, threshold=None: hit(template)
    runner._wait_first = lambda templates, attempts=12, threshold=None: ("point", hit(templates[0]))

    runner._leave_paid_draw("screen", "one_order", "Thiên Vận")
    runner._leave_paid_draw("screen", "25_soul", "Nhân Đức")

    assert taps == ["return", "return"]


def test_chiem_tinh_failure_is_optional_and_does_not_fail_vo_tuong():
    runner = object.__new__(module.VoTuongRunner)
    runner.config = SimpleNamespace(chiem_tinh_banner="chiem")
    runner.screen_provider = lambda: "point_screen"
    runner._match = lambda *args, **kwargs: hit("chiem")
    runner._tap = lambda found: None
    runner._run_exchange = lambda: (_ for _ in ()).throw(RuntimeError("popup không mở"))

    assert runner._run_optional_exchange() is False
