import csv
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.accounts.writer import write_account_balance
from app.vision.balance import read_balance_near_icon
from app.vision.image import load_image

ROOT = Path(__file__).parents[1]


def test_tam_quoc_lenh_resets_balance_write_guards_for_each_account_run():
    module = import_module("app.actions.dc3q.targets.01_tam-quoc-lenh")
    runner = object.__new__(module.TamQuocLenhRunner)
    runner.config = SimpleNamespace(max_steps=0)
    runner._que_balance_saved = True
    runner._nguyen_balance_saved = True

    with pytest.raises(RuntimeError, match="vượt quá số bước"):
        runner.run()

    assert runner._que_balance_saved is False
    assert runner._nguyen_balance_saved is False


def test_read_three_balances_from_supplied_reference_frames():
    cases = [
        ("data/img/templates/targets/01_tam-quoc-lenh/full screen/full-screen_tql_queboi_01.png", "config/dc3q/item/item_quelanh.png", (28, 0, 95, 42), (190, 45, 360, 160), .50, 309),
        ("data/img/templates/targets/01_tam-quoc-lenh/full screen/full-screen_tql_diembinh_01.png", "config/dc3q/item/item_nguyenlinhngoc.png", (28, 0, 110, 48), (190, 45, 360, 160), .50, 270),
        ("data/img/templates/stars/home/full screen/full-screen_base_01.png", "config/dc3q/item/item_knb.png", (82, 8, 125, 32), (750, 50, 850, 150), .45, 1590),
    ]
    for frame, icon, offset, search, threshold, expected in cases:
        assert read_balance_near_icon(load_image(ROOT / frame), ROOT / icon, offset, search_roi=search, threshold=threshold) == expected


def test_balance_write_changes_only_requested_account_cell(tmp_path):
    path = tmp_path / "accounts.csv"
    path.write_text("id,username,password,KNB,Que-Lanh,Nguyen-Linh-Ngoc\na,u,p,1,2,3\nb,x,y,4,5,6\n", encoding="utf-8")
    write_account_balance(path, "a", "Que-Lanh", 309)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert rows == [
        {"id": "a", "username": "u", "password": "p", "KNB": "1", "Que-Lanh": "309", "Nguyen-Linh-Ngoc": "3"},
        {"id": "b", "username": "x", "password": "y", "KNB": "4", "Que-Lanh": "5", "Nguyen-Linh-Ngoc": "6"},
    ]


def test_tql_saves_each_balance_once_when_its_tab_finishes():
    module = import_module("app.actions.dc3q.targets.01_tam-quoc-lenh")
    assert "save_que_balance" in module.TamQuocLenhRunner.__init__.__code__.co_varnames
    assert "save_nguyen_balance" in module.TamQuocLenhRunner.__init__.__code__.co_varnames
