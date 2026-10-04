from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_account_workflow_includes_truong_thanh_after_xa_giao():
    workflow = yaml.safe_load((ROOT / "scripts/dc3q/stars/dang-nhap.yaml").read_text(encoding="utf-8"))
    assert [Path(item).stem for item in workflow["home_targets"]] == [
        "01_tam-quoc-lenh", "02_hoat-dong", "03_cua-hang", "04_quan-doan",
        "05_khong-gian-ca-nhan", "06_xa-giao", "07_truong-thanh",
    ]


def test_activity_script_places_optional_newcomer_after_tax():
    script = yaml.safe_load((ROOT / "scripts/dc3q/targets/02_hoat-dong.yaml").read_text(encoding="utf-8"))
    steps = script["steps"]
    assert steps.index("trung_thu_thue_in_allowed_hours") < steps.index(
        "tan_thu_if_present_claim_safe_rewards"
    ) < steps.index("close_to_home")


def test_runtime_requires_three_stable_home_frames():
    config = yaml.safe_load((ROOT / "config/dc3q/stars/dang-nhap.yaml").read_text(encoding="utf-8"))
    assert config["login"]["logged_in_confirmations"] == 3
