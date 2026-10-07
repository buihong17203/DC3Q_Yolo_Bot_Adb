from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def hit():
    return SimpleNamespace(found=True, confidence=1.0, x=10, y=20, width=20, height=10)


def test_a6_rechecks_free_marker_before_every_tap_then_closes():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow("A6", [], ["free"], ["reward"], ["close"], repeat_free=True)
    initial, reward1, reward2, final_reward = object(), object(), object(), object()
    runner.screen_provider = lambda: initial

    def first(screen, templates, threshold=None):
        if templates == ["free"] and screen in (initial, reward1, reward2):
            return hit()
        if templates == ["reward"] and screen in (reward1, reward2, final_reward):
            return hit()
        return None

    runner._first = first
    waits = iter([
        (reward1, hit()), (reward2, hit()), (final_reward, hit()),
        (final_reward, hit()),
    ])
    runner._wait_first = lambda templates, attempts=6, threshold=None: next(waits)
    taps = []
    runner._tap = lambda match: taps.append("tap")
    runner.config = SimpleNamespace()

    runner._run_flow(flow)

    assert taps == ["tap", "tap", "tap", "tap"]  # 3 FREE + Trở về.


def test_a6_new_one_jade_draw_is_configured_only_as_paid_stop():
    from pathlib import Path
    import yaml

    root = Path(__file__).parents[1]
    config = yaml.safe_load((root / "config/dc3q/targets/07_truong-thanh.yaml").read_text(encoding="utf-8"))
    flow = next(item for item in config["truong_thanh"]["flows"] if item["name"] == "A6_than-binh")
    paid = "data/img/templates/targets/07_truong-thanh/A6_than-binh/screen/screen_tb_tambinhmichbao_button_1lan_1ngocbai.png"

    assert paid in flow["spent"]
    assert paid not in flow["free"]


def test_a6_recovery_never_taps_when_paid_jade_state_is_visible():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow("A6_than-binh", [], [], ["one_jade"], ["false_return"])
    runner.config = SimpleNamespace(
        flows=[flow], a4_return_templates=[], hub_markers=[], home_markers=[],
        entry_templates=[], close_templates=[], wait_seconds=0,
    )
    runner.screen_provider = lambda: "paid"
    runner._first = lambda screen, templates, threshold=None: (
        hit() if templates == ["one_jade"] or templates == ["false_return"] else None
    )
    taps = []
    runner._tap = taps.append
    runner.sleep = lambda _: None

    assert runner.recover_home() is False
    assert taps == []


def test_non_repeat_flow_never_taps_without_free():
    runner = object.__new__(module.TruongThanhRunner)
    flow = module.SubFlow("A7", [], ["free"], ["spent"], ["close"])
    paid = object()
    runner.screen_provider = lambda: paid
    runner._first = lambda screen, templates, threshold=None: hit() if templates == ["close"] else None
    taps = []
    runner._tap = lambda match: taps.append("close")
    runner.config = SimpleNamespace()

    runner._run_flow(flow)

    assert taps == ["close"]


def test_fresh_free_gate_rejects_stale_free_when_fresh_frame_is_paid():
    runner = object.__new__(module.TruongThanhRunner)
    stale, paid = object(), object()
    runner.screen_provider = lambda: paid
    runner.config = SimpleNamespace(state_threshold=.80, state_margin=.05)

    def match(screen, template, threshold=None):
        scores = {(paid, "free"): .84, (paid, "paid"): .99}
        score = scores.get((screen, template), 0.0)
        return SimpleNamespace(found=score >= (0.0 if threshold == 0.0 else (threshold or .70)), confidence=score)

    runner._match = match

    screen, free = runner._fresh_proven_free(["free"], ["paid"], .80)

    assert screen is paid
    assert free is None


def test_fresh_free_gate_accepts_only_clear_free_winner():
    runner = object.__new__(module.TruongThanhRunner)
    fresh = object()
    runner.screen_provider = lambda: fresh
    runner.config = SimpleNamespace(state_threshold=.80, state_margin=.05)

    def match(screen, template, threshold=None):
        score = {"free": .98, "paid": .84}[template]
        return SimpleNamespace(found=True, confidence=score)

    runner._match = match

    screen, free = runner._fresh_proven_free(["free"], ["paid"], .95)

    assert screen is fresh
    assert free.confidence == .98
