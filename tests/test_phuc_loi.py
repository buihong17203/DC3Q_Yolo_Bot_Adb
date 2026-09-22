from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from app.accounts import AccountRepository
from app.automation import ActionRegistry, AutomationEngine
from app.core.game_day import DailyRuntimeStore, GameDayClock
from app.vision.template_matcher import TemplateMatcher


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "assets" / "templates"


def _read_image(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    assert image is not None, path
    return image


def _adb_frame(full_screen: Path) -> np.ndarray:
    image = _read_image(full_screen)
    assert image.shape[0] >= 575 and image.shape[1] >= 961
    return image[35:575, 1:961]


def test_phuc_loi_action_is_registered_and_scenario_is_in_manager() -> None:
    assert ActionRegistry().has("phuc_loi")
    manager = yaml.safe_load((ROOT / "scripts/multi_account_manager.yaml").read_text(encoding="utf-8"))
    calls = [step["run_scenario"] for step in manager["steps"] if "run_scenario" in step]
    assert calls == [
        "tasks/tam_quoc_lenh.yaml",
        "tasks/phuc_loi.yaml",
        "auth/logout.yaml",
    ]

    scenario = AutomationEngine.load_scenario(ROOT / "scripts/tasks/phuc_loi.yaml")
    assert scenario["steps"][0]["action"] == "phuc_loi"
    assert scenario["steps"][0]["skip_checkin"] is False
    assert scenario["steps"][0]["claim_checkin"] is True
    text = (ROOT / "scripts/tasks/phuc_loi.yaml").read_text(encoding="utf-8")
    assert "Ngày lễ" in text and "Hoạt động" in text


def test_runtime_default_and_migration_add_phuc_loi_without_losing_tam_quoc(tmp_path: Path) -> None:
    accounts_path = tmp_path / "accounts.json"
    accounts_path.write_text(
        json.dumps({"accounts": [{"id": "acc_001", "username": "u", "password": "p"}]}),
        encoding="utf-8",
    )
    accounts = AccountRepository(accounts_path).load()
    runtime = tmp_path / "runtime.json"
    store = DailyRuntimeStore(runtime, tmp_path / "history")

    # Mô phỏng runtime cũ: đã có Tam Quốc Lệnh nhưng chưa có Phúc lợi.
    runtime.write_text(
        json.dumps({
            "game_day": GameDayClock().key(datetime.now()),
            "reset_hour": 23,
            "accounts": [{
                "id": "acc_001",
                "status": "READY",
                "attempts": 0,
                "tasks": {
                    "tam_quoc_lenh": {
                        "status": "PARTIAL",
                        "que_boi": "DONE",
                        "diem_binh": "NOT_STARTED",
                        "error": None,
                    }
                },
            }],
            "events": [],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    store.initialize(accounts)
    raw = json.loads(runtime.read_text(encoding="utf-8"))
    tasks = raw["accounts"][0]["tasks"]
    assert tasks["tam_quoc_lenh"]["que_boi"] == "DONE"
    assert tasks["phuc_loi"] == {
        "status": "NOT_STARTED",
        "le_bao_quoc_van": "NOT_STARTED",
        "qua_online": "NOT_STARTED",
        "qua_online_claims": 0,
        "qua_online_reason": None,
        "diem_danh": "NOT_STARTED",
        "diem_danh_error": None,
        "trung_thu_thue": "NOT_STARTED",
        "trung_thu_thue_reason": None,
        "error": None,
    }
    assert tasks["workflow"]["current_step"] == "LOGIN"


def test_new_navigation_templates_match_real_captured_frames() -> None:
    matcher = TemplateMatcher(default_threshold=0.70)

    home = _adb_frame(TEMPLATES / "dc3q/start/full screen/full_screen_base_main_hall.png")
    entry = matcher.find_best(
        home,
        TEMPLATES / "dc3q/targets/Hoạt-Động/screen/home_hoat_dong_entry.png",
        threshold=0.80,
        roi=(0, 330, 130, 455),
    )
    assert entry is not None and entry.confidence >= 0.80

    welfare = _adb_frame(
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/full screen/Qùa-Online/full_screen_qua_online_daily_rewards_ready.png"
    )
    selected = matcher.find_best(
        welfare,
        TEMPLATES / "dc3q/targets/Hoạt-Động/screen/phuc_loi_selected.png",
        threshold=0.80,
        roi=(0, 115, 110, 230),
    )
    close = matcher.find_best(
        welfare,
        TEMPLATES / "dc3q/targets/Hoạt-Động/screen/event_panel_close_button.png",
        threshold=0.90,
        roi=(875, 20, 960, 115),
    )
    assert selected is not None and selected.confidence >= 0.80
    assert close is not None and close.confidence >= 0.90

    # Lễ Bao Quốc Vận phải nhận ra được cả khi đang ở trạng thái xám/inactive.
    bao_inactive = matcher.find_best(
        welfare,
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/Lễ-Bao-Quốc-Vận/screen_bao_quoc_van_title_inactive.png",
        threshold=0.85,
        roi=(90, 105, 250, 225),
    )
    assert bao_inactive is not None and bao_inactive.confidence >= 0.85


def test_supported_welfare_controls_match_their_real_screens() -> None:
    matcher = TemplateMatcher(default_threshold=0.80)

    bao = _adb_frame(
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/full screen/Lễ-Bao-Quốc-Vận/full_screen_bao_quoc_van_login_reward_page_ready.png"
    )
    assert matcher.find_best(
        bao,
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/Lễ-Bao-Quốc-Vận/screen_bao_quoc_van_free_chest_button.png",
        threshold=0.90,
    ) is not None

    online = _adb_frame(
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/full screen/Qùa-Online/full_screen_qua_online_daily_rewards_ready.png"
    )
    assert matcher.find_best(
        online,
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/Qùa-Online/screen_qua_online_claim_button.png",
        threshold=0.90,
    ) is not None

    checkin = _adb_frame(
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/full screen/Điểm-Danh/full_screen_diem_danh_checkin_reward_grid_ready.png"
    )
    assert matcher.find_best(
        checkin,
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/Điểm-Danh/screen_diem_danh_page_marker.png",
        threshold=0.90,
    ) is not None

    tax_active = _adb_frame(
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/full screen/Trưng-Thu-Thuế/full_screen_trung_thu_thue_tax_reward_page_unopened.png"
    )
    # Ở màn hình Trưng thu thuế, Điểm danh đang inactive không có badge.
    assert matcher.find_best(
        tax_active,
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/Điểm-Danh/screen_diem_danh_title_inactive.png",
        threshold=0.90,
        roi=(90, 150, 250, 310),
    ) is not None

    # Mốc menu ổn định để định vị Trưng thu thuế khi chính item Trưng thu đang inactive.
    assert matcher.find_best(
        tax_active,
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/navigation/screen_hoat_dong_gioi_han_inactive.png",
        threshold=0.90,
        roi=(90, 220, 250, 380),
    ) is not None

    assert matcher.find_best(
        tax_active,
        TEMPLATES / "dc3q/targets/Hoạt-Động/Phúc-Lợi/screen/Trưng-Thu-Thuế/screen_trung_thu_tab_button.png",
        threshold=0.90,
    ) is not None
