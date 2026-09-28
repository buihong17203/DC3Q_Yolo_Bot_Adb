from importlib import import_module
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_numbered_runtime_modules_own_actions():
    stars = import_module("app.actions.dc3q.stars")
    assert stars.AccountLoginAction.__module__.endswith("01-0_dang-nhap")
    assert stars.AccountLogoutAction.__module__.endswith("01-2_dang-xuat")
    assert stars.HomeAction.__module__.endswith("01-4_home")

    tql = import_module("app.actions.dc3q.targets.01_tam-quoc-lenh")
    assert tql.TamQuocLenhConfig.__module__.endswith("01_tam-quoc-lenh")
    assert tql.TamQuocLenhRunner.__module__.endswith("01_tam-quoc-lenh")


def test_login_and_tql_active_assets_exist():
    login = yaml.safe_load((ROOT / "config/dc3q/stars/dang-nhap.yaml").read_text(encoding="utf-8"))
    target = yaml.safe_load((ROOT / "config/dc3q/targets/01_tam-quoc-lenh.yaml").read_text(encoding="utf-8"))
    values = [
        *login["login"]["templates"]["login_screen"],
        *login["login"]["templates"]["logged_in"],
        login["login"]["controls"]["username"],
        *login["login"]["controls"]["password"],
        login["login"]["controls"]["submit"],
        login["login"]["unexpected"]["profile_update"]["state"],
        login["login"]["unexpected"]["profile_update"]["close"],
        login["login"]["unexpected"]["enemy_raid"]["state"],
        login["login"]["unexpected"]["enemy_raid"]["close"],
        target["tam_quoc_lenh"]["que_boi"]["free"],
        target["tam_quoc_lenh"]["que_boi"]["paid"],
        target["tam_quoc_lenh"]["diem_binh"]["free"],
        target["tam_quoc_lenh"]["diem_binh"]["paid"],
    ]
    assert not [value for value in values if not (ROOT / value).is_file()]
