from importlib import import_module
from pathlib import Path
from types import SimpleNamespace


module = import_module("app.actions.dc3q.targets.01_tam-quoc-lenh")


def found(score, name):
    return SimpleNamespace(
        found=True, confidence=score, x=10, y=20, width=20, height=10,
        name=name,
    )


def runner():
    value = object.__new__(module.TamQuocLenhRunner)
    value.config = SimpleNamespace(
        menu_templates=[Path("closed.png"), Path("open.png")],
        entry_templates=[Path("entry.png")], threshold=.60,
    )
    value.input = SimpleNamespace(tap=lambda x, y: None)
    value.sleep = lambda _: None
    return value


def test_closed_menu_is_tapped_even_when_open_template_false_positive_scores_higher():
    value = runner()
    answers = {
        "closed.png": found(.812, "closed"),
        "open.png": found(1.0, "open-false-positive"),
    }
    value._match = lambda screen, template, threshold=None: answers[template.name]
    tapped = []
    value._tap = tapped.append

    assert value._ensure_home_menu("home") == "opened"
    assert tapped == [answers["closed.png"]]


def test_open_menu_is_not_tapped_again():
    value = runner()
    answers = {
        "closed.png": SimpleNamespace(found=False, confidence=.2),
        "open.png": found(1.0, "open"),
    }
    value._match = lambda screen, template, threshold=None: answers[template.name]
    tapped = []
    value._tap = tapped.append

    assert value._ensure_home_menu("home") == "already_open"
    assert tapped == []
