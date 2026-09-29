from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_current_home_workflow_is_login_tql_activity_logout_only():
    workflow = yaml.safe_load(
        (ROOT / "scripts/dc3q/stars/dang-nhap.yaml").read_text(encoding="utf-8")
    )
    assert [Path(path).stem for path in workflow["home_targets"]] == [
        "01_tam-quoc-lenh", "02_hoat-dong",
    ]


def test_disabled_targets_are_explicit_and_enabled_targets_have_runtime_branch():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    for number, name, key in (
        (3, "cua-hang", "cua_hang"), (4, "quan-doan", "quan_doan"),
        (5, "khong-gian-ca-nhan", "khong_gian_ca_nhan"), (6, "xa-giao", "xa_giao"),
        (7, "truong-thanh", "truong_thanh"), (8, "vo-tuong", "vo_tuong"),
        (9, "quan-su", "quan_su"), (10, "nhiem-vu", "nhiem_vu"),
    ):
        config = yaml.safe_load(
            (ROOT / f"config/dc3q/targets/{number:02d}_{name}.yaml").read_text(encoding="utf-8")
        )[key]
        if config["enabled"]:
            assert f'module_name == "{number:02d}_{name}"' in main
        else:
            assert config["enabled"] is False
