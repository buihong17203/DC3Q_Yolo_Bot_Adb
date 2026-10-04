from importlib import import_module
from types import SimpleNamespace

module = import_module("app.actions.dc3q.targets.07_truong-thanh")


def test_subflow_free_threshold_overrides_navigation_threshold():
    runner = object.__new__(module.TruongThanhRunner)
    runner.config = SimpleNamespace(threshold=.70)
    runner.vision = SimpleNamespace(
        find_template=lambda screen, purpose, template, threshold: SimpleNamespace(
            match=SimpleNamespace(found=threshold <= .919, confidence=.919)
        )
    )
    flow = module.SubFlow("A4", [], ["free"], [], [], .95)

    assert runner._first(screen=object(), templates=flow.free, threshold=flow.free_threshold) is None
