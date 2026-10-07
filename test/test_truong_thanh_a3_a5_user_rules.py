from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=1.0, x=10, y=20, width=20, height=10)


def test_a3_clicks_raise_flag_then_requires_result():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a3_raise_flag=["flag"], a3_result=["result"],
        a3_result_dismiss_point=(480, 500), a3_tab_open=["open"], wait_seconds=0,
    )
    taps = []
    runner._first = lambda screen, templates, threshold=None: hit() if templates == ["flag"] else None
    runner._tap = taps.append
    runner._wait_first = lambda templates, attempts=6, threshold=None: (object(), hit())
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))
    runner.sleep = lambda _: None

    runner._a3_raise_flag(object())

    assert len(taps) == 2


def test_a5_runtime_checkpoint_accepts_no_flow_argument():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow("A5_trai-ngua", [], [], [], [])
    runner.config = SimpleNamespace(flows=[flow])
    runner._open_home_entry = lambda: None
    runner.screen_provider = lambda: object()
    runner._first = lambda screen, templates, threshold=None: None

    runner._run_a5()


def test_a5_fast_skips_when_both_free_states_absent():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a5_normal_free=["normal"], a5_gold_free=["gold"],
        a5_normal_select="select",
        a5_normal_quantity_roi=(0, 0, 1, 1), a5_normal_free_roi=(0, 0, 1, 1),
        a5_gold_quantity_roi=(0, 0, 1, 1), a5_gold_free_roi=(0, 0, 1, 1),
    )
    runner.screen_provider = lambda: object()
    runner._first = lambda screen, templates, threshold=None: None
    taps = []
    runner._tap = taps.append

    runner._a5_fast_claim(object())

    assert taps == []


def test_a5_gold_reduces_quantity_to_free_count_before_claim():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(
        a5_normal_free=["normal"], a5_gold_free=["gold"], a5_normal_select="select",
        a5_normal_quantity_roi=(0, 0, 1, 1), a5_normal_free_roi=(0, 0, 1, 1),
        a5_gold_quantity_roi=(100, 100, 120, 120), a5_gold_free_roi=(0, 0, 1, 1),
        a5_max_adjustments=10, a5_reward_dismiss_point=(480, 500), wait_seconds=0,
    )
    runner.sleep = lambda _: None
    runner.screen_provider = lambda: object()
    runner._first = lambda screen, templates, threshold=None: hit() if templates == ["gold"] else None
    values = iter([1, 3, 2, 1, 1, 1, 0])  # initial; adjusted; fresh free/quantity; terminal
    runner._read_roi_number = lambda screen, roi: next(values)
    taps = []
    runner._tap = taps.append
    runner.input = SimpleNamespace(tap=lambda *point: taps.append(point))

    runner._a5_fast_claim(object())

    assert len(taps) == 4  # minus, minus, Ngựa vàng, dismiss reward
