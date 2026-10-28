import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.workflow.script_loader import ScriptLoader
from app.main import _project_root, _resolve_project_path, load_login_random_events
from app.accounts.manager import AccountManager
from app.workflow.account_login import AccountLoginController, AccountLoginConfig
from app.accounts.runtime import AccountRuntime
from app.actions.dc3q.stars import LogoutTemplates

def test_full_pipeline_controller_and_targets_factory():
    root = ROOT
    loader = ScriptLoader()

    multi_path = Path("scripts/multi_manager.yaml")
    multi_data = loader.load(multi_path)
    workflows = multi_data.get("workflows", [])
    assert len(workflows) > 0

    for wf_path_str in workflows:
        wf_path = _resolve_project_path(root, wf_path_str)
        workflow = loader.load(wf_path)

        config_value = workflow.get("config", "config/dc3q/stars/dang-nhap.yaml")
        config_path = _resolve_project_path(root, config_value)
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        login = cfg.get("login", {})
        templates = login.get("templates", {})
        controls = login.get("controls", {})

        logout_config_value = workflow.get("logout_config", "config/dc3q/stars/dang-xuat.yaml")
        logout_config_path = _resolve_project_path(root, logout_config_value)
        logout_cfg = (yaml.safe_load(logout_config_path.read_text(encoding="utf-8")) or {}).get("logout", {})
        unexpected = login.get("unexpected", {}) or {}
        home_events = load_login_random_events(root, unexpected)

        home_target_values = list(workflow.get("home_targets", []))
        home_target_specs = []
        for target_value in home_target_values:
            target_workflow = yaml.safe_load(
                _resolve_project_path(root, target_value).read_text(encoding="utf-8")
            ) or {}
            target_config = yaml.safe_load(
                _resolve_project_path(root, target_workflow["config"]).read_text(encoding="utf-8")
            ) or {}
            home_target_specs.append((Path(target_value).stem, target_config))

        accounts = AccountManager(_resolve_project_path(root, workflow.get("account_file", cfg["account_file"])))
        runtime = AccountRuntime(
            root,
            reset_hour=int(workflow.get("reset_hour", 23)),
            archive_dir=workflow.get("runtime_archive_dir", "docs/docs_days_runtime"),
        )

        def paths(values):
            return [_resolve_project_path(root, value) for value in values]

        def coord(name):
            value = (login.get("coordinates", {}) or {}).get(name)
            return tuple(value) if value else None

        logout_templates = LogoutTemplates(
            open_tuychon=_resolve_project_path(root, logout_cfg["templates"]["open_tuychon"]),
            open_cdnd=_resolve_project_path(root, logout_cfg["templates"]["open_cdnd"]),
            open_dtk=_resolve_project_path(root, logout_cfg["templates"]["open_dtk"]),
            confirm_dtk=_resolve_project_path(root, logout_cfg["templates"]["confirm_dtk"]),
            home_anchor_template=_resolve_project_path(root, logout_cfg["home_anchor_template"]),
            home_anchor_roi=tuple(logout_cfg.get("home_anchor_roi", (840, 480, 1000, 575))),
            avatar_mirror_offset=tuple(logout_cfg.get("avatar_mirror_offset", (-8, 21))),
            avatar_fallback_normalized=tuple(
                logout_cfg.get("avatar_fallback_normalized", (0.03125, 0.064815))
            ),
        )

        mock_adb = MagicMock()
        mock_device = MagicMock()
        mock_device.serial = "emulator-5554"

        controller = AccountLoginController(
            mock_adb, mock_device, accounts, AccountLoginConfig(
                login_templates=[_resolve_project_path(root, x) for x in templates.get("login_screen", [])],
                logged_in_templates=[_resolve_project_path(root, x) for x in templates.get("logged_in", [])],
                username_template=_resolve_project_path(root, controls["username"]),
                password_templates=[_resolve_project_path(root, x) for x in controls.get("password", [])],
                submit_template=_resolve_project_path(root, controls["submit"]),
                username=coord("username"), password=coord("password"), submit=coord("submit"),
                tiep_tuc=coord("tiep_tuc"),
                threshold=float(login.get("threshold", 0.80)),
                control_threshold=float(login.get("control_threshold", 0.72)),
                poll_seconds=float(login.get("poll_seconds", 1.0)),
                login_timeout_seconds=float(login.get("timeout_seconds", 180.0)),
                logged_in_threshold=float(login.get("logged_in_threshold", 0.55)),
                logged_in_confirmations=int(login.get("logged_in_confirmations", 3)),
                auto_logout=bool(workflow.get("auto_logout", True)),
                logout_templates=logout_templates,
                logout_threshold=float(logout_cfg.get("threshold", 0.70)),
                logout_max_attempts=int(logout_cfg.get("max_attempts", 5)),
                home_events=home_events,
                save_knb_balance=lambda account_id, value: None,
                knb_icon=_resolve_project_path(root, "config/dc3q/item/item_knb.png"),
                cutoff_hour=int(workflow.get("cutoff_hour", 22)),
                cutoff_minute=int(workflow.get("cutoff_minute", 59)),
                persistent_daily=bool(workflow.get("persistent_daily", True)),
                target_retry_limit=int(workflow.get("target_retry_limit", 3)),
                out_game_title=_resolve_project_path(
                    root, workflow.get(
                        "out_game_title",
                        "data/img/templates/stars/out_game/screen/screen_out_game_title.jpg",
                    ),
                ),
                out_game_confirm=_resolve_project_path(
                    root, workflow.get(
                        "out_game_confirm",
                        "data/img/templates/stars/out_game/screen/screen_out_game_button_xacnhan.png",
                    ),
                ),
                out_game_threshold=float(workflow.get("out_game_threshold", 0.75)),
                out_game_confirm_threshold=float(workflow.get("out_game_confirm_threshold", 0.50)),
                restart_wait_attempts=int(workflow.get("restart_wait_attempts", 60)),
                sub_screen_close_templates=[
                    _resolve_project_path(root, "data/img/templates/targets/02_hoat-dong/screen_button_dong_02hoatdong.png"),
                    _resolve_project_path(root, "data/img/templates/targets/03_cua-hang/screen_button_dong_03cuahang.png"),
                    _resolve_project_path(root, "data/img/templates/targets/04_quan-doan/screen_button_dong_04quandoan.png"),
                    _resolve_project_path(root, "data/img/templates/targets/05_khong-gian-ca-nhan/screen/screen_cb_nt_button_dong.png"),
                    _resolve_project_path(root, "data/img/templates/targets/05_khong-gian-ca-nhan/screen/screen_kgcn_button_dong.png"),
                    _resolve_project_path(root, "data/img/templates/targets/06_xa-giao/screen/screen_xg_bb_button_dong_banbe.png"),
                    _resolve_project_path(root, "data/img/templates/targets/07_truong-thanh/A2_tuong-an/screen/screen_ta_ttd_button_dong.png"),
                    _resolve_project_path(root, "data/img/templates/targets/08_vo-tuong/screen/screen_vt_button_dong.png"),
                    _resolve_project_path(root, "data/img/templates/targets/09_quan-su/tranh-ba/screen/screen_qs_tb_button_dong.png"),
                    _resolve_project_path(root, "data/img/templates/targets/10_nhiem-vu/screen/screen_nv_button_dong.png"),
                    _resolve_project_path(root, "data/img/templates/random-events/pop-up_random/homecoming_event/screen/screen_vgql_button_dong.png"),
                ],
            ),
            runtime,
        )

        from importlib import import_module
        targets = []
        for module_name, target_config in home_target_specs:
            module = import_module(f"app.actions.dc3q.targets.{module_name}")
            root_key = next(iter(target_config))
            if not bool(target_config[root_key].get("enabled", True)):
                continue

            if module_name == "01_tam-quoc-lenh":
                target_cfg = target_config["tam_quoc_lenh"]
                accounts_path = _resolve_project_path(root, workflow.get("account_file", cfg["account_file"]))
                target = module.TamQuocLenhRunner(
                    controller._screen, controller.input, controller.logout_action.vision,
                    module.TamQuocLenhConfig(
                        entry_templates=paths(target_cfg["home"]["entry"]),
                        menu_templates=paths(target_cfg["home"]["menu"]),
                        panel_markers=paths(target_cfg["panel"]["markers"]),
                        close_template=_resolve_project_path(root, target_cfg["panel"]["close"]),
                        reward_marker=_resolve_project_path(root, target_cfg["reward"]["marker"]),
                        reward_dismiss=_resolve_project_path(root, target_cfg["reward"]["dismiss"]),
                        que_boi_tabs=paths(target_cfg["que_boi"]["tabs"]),
                        que_boi_open=paths(target_cfg["que_boi"]["open"]),
                        que_boi_free=_resolve_project_path(root, target_cfg["que_boi"]["free"]),
                        que_boi_paid=_resolve_project_path(root, target_cfg["que_boi"]["paid"]),
                        diem_binh_tabs=paths(target_cfg["diem_binh"]["tabs"]),
                        diem_binh_open=paths(target_cfg["diem_binh"]["open"]),
                        diem_binh_free=_resolve_project_path(root, target_cfg["diem_binh"]["free"]),
                        diem_binh_paid=_resolve_project_path(root, target_cfg["diem_binh"]["paid"]),
                        action_roi=tuple(target_cfg["action_roi"]),
                        home_markers=paths(target_cfg["home"]["markers"]),
                        action_threshold=float(target_cfg.get("action_threshold", 0.65)),
                        advance_popup_marker=_resolve_project_path(root, target_cfg["advance_popup"]["marker"]),
                        advance_popup_close=_resolve_project_path(root, target_cfg["advance_popup"]["close"]),
                        inactivity_marker=_resolve_project_path(root, target_cfg["inactivity"]["marker"]),
                        inactivity_return=_resolve_project_path(root, target_cfg["inactivity"]["return"]),
                        threshold=float(target_cfg.get("threshold", 0.60)),
                        max_steps=int(target_cfg.get("max_steps", 30)),
                        wait_seconds=float(target_cfg.get("wait_seconds", 0.8)),
                    ),
                    save_que_balance=lambda value: None,
                    save_nguyen_balance=lambda value: None,
                )
            elif module_name == "02_hoat-dong":
                target_cfg = target_config["hoat_dong"]
                target = module.HoatDongRunner(
                    controller._screen, controller.input, controller.logout_action.vision,
                    module.HoatDongConfig(
                        entry_templates=paths(target_cfg["home"]["entry"]),
                        menu_templates=paths(target_cfg["home"]["menu"]),
                        panel_markers=paths(target_cfg["panel"]["markers"]),
                        close_template=_resolve_project_path(root, target_cfg["panel"]["close"]),
                        home_markers=paths(target_cfg["home"]["markers"]),
                        welfare_tabs=paths(target_cfg["welfare"]["tabs"]),
                        welfare_open=paths(target_cfg["welfare"]["open"]),
                        newcomer_tabs=paths(target_cfg["newcomer"]["tabs"]),
                        newcomer_open=paths(target_cfg["newcomer"]["open"]),
                        newcomer_vassal_tabs=paths(target_cfg["newcomer"]["vassal"]["tabs"]),
                        newcomer_vassal_open=paths(target_cfg["newcomer"]["vassal"]["open"]),
                        newcomer_vassal_claimable=_resolve_project_path(root, target_cfg["newcomer"]["vassal"]["claimable"]),
                        newcomer_offer_tabs=paths(target_cfg["newcomer"]["offer"]["tabs"]),
                        newcomer_offer_open=paths(target_cfg["newcomer"]["offer"]["open"]),
                        newcomer_offer_claimable=_resolve_project_path(root, target_cfg["newcomer"]["offer"]["claimable"]),
                        newcomer_offer_claimed=_resolve_project_path(root, target_cfg["newcomer"]["offer"]["claimed"]),
                        newcomer_seven_day_tabs=paths(target_cfg["newcomer"]["seven_day"]["tabs"]),
                        newcomer_seven_day_open=paths(target_cfg["newcomer"]["seven_day"]["open"]),
                        newcomer_seven_day_claimable=_resolve_project_path(root, target_cfg["newcomer"]["seven_day"]["claimable"]),
                        newcomer_seven_day_claimed=_resolve_project_path(root, target_cfg["newcomer"]["seven_day"]["claimed"]),
                        newcomer_login_tabs=paths(target_cfg["newcomer"]["login"]["tabs"]),
                        newcomer_login_open=paths(target_cfg["newcomer"]["login"]["open"]),
                        newcomer_login_claimable=_resolve_project_path(root, target_cfg["newcomer"]["login"]["claimable"]),
                        newcomer_login_claimed=_resolve_project_path(root, target_cfg["newcomer"]["login"]["claimed"]),
                        newcomer_unavailable=_resolve_project_path(root, target_cfg["newcomer"]["unavailable"]),
                        newcomer_reward_marker=_resolve_project_path(root, target_cfg["newcomer"]["reward"]["marker"]),
                        newcomer_reward_dismiss=_resolve_project_path(root, target_cfg["newcomer"]["reward"]["dismiss"]),
                        national_tabs=paths(target_cfg["national_fortune"]["tabs"]),
                        national_open=paths(target_cfg["national_fortune"]["open"]),
                        national_free=_resolve_project_path(root, target_cfg["national_fortune"]["free"]),
                        national_claimed=_resolve_project_path(root, target_cfg["national_fortune"]["claimed"]),
                        online_tabs=paths(target_cfg["online_gift"]["tabs"]),
                        online_open=paths(target_cfg["online_gift"]["open"]),
                        online_claimable=_resolve_project_path(root, target_cfg["online_gift"]["claimable"]),
                        online_unavailable=_resolve_project_path(root, target_cfg["online_gift"]["unavailable"]),
                        online_claimed=_resolve_project_path(root, target_cfg["online_gift"]["claimed"]),
                        attendance_tabs=paths(target_cfg["attendance"]["tabs"]),
                        attendance_open=paths(target_cfg["attendance"]["open"]),
                        attendance_makeup=None,
                        attendance_grid=tuple(target_cfg["attendance"]["grid"]),
                        attendance_milestone_claimable=_resolve_project_path(root, target_cfg["attendance"]["milestone"]["claimable"]),
                        attendance_milestone_locked=_resolve_project_path(root, target_cfg["attendance"]["milestone"]["locked"]),
                        attendance_milestone_claimed=_resolve_project_path(root, target_cfg["attendance"]["milestone"]["claimed"]),
                        attendance_milestone_rois=[tuple(roi) for roi in target_cfg["attendance"]["milestone"]["rois"]],
                        tax_tabs=paths(target_cfg["tax"]["tabs"]),
                        tax_open=paths(target_cfg["tax"]["open"]),
                        tax_unavailable=_resolve_project_path(root, target_cfg["tax"]["unavailable"]),
                        tax_claimable=_resolve_project_path(root, target_cfg["tax"]["claimable"]),
                        tax_claimed=_resolve_project_path(root, target_cfg["tax"]["claimed"]),
                        reward_marker=_resolve_project_path(root, target_cfg["reward"]["marker"]),
                        reward_dismiss=_resolve_project_path(root, target_cfg["reward"]["dismiss"]),
                        threshold=float(target_cfg.get("threshold", 0.65)),
                        state_threshold=float(target_cfg.get("state_threshold", 0.76)),
                        max_steps=int(target_cfg.get("max_steps", 50)),
                        wait_seconds=float(target_cfg.get("wait_seconds", 0.8)),
                        only_attendance=bool(target_cfg.get("only_attendance", False)),
                    ),
                    attendance_day=lambda: 1,
                    save_attendance_day=lambda day: None,
                    account_id=lambda: "acc_001",
                )
            elif module_name == "03_cua-hang":
                c = target_config["cua_hang"]
                target = module.CuaHangRunner(controller._screen, controller.input, controller.logout_action.vision,
                    module.CuaHangConfig(paths(c["home"]["entry"]), paths(c["home"]["menu"]),
                        paths(c["panel"]["markers"]), _resolve_project_path(root, c["panel"]["close"]),
                        paths(c["home"]["markers"]), paths(c["gift"]["tabs"]), paths(c["gift"]["open"]),
                        _resolve_project_path(root, c["gift"]["unclaimed"]), _resolve_project_path(root, c["gift"]["claimed"]),
                        _resolve_project_path(root, c["reward"]["marker"]), _resolve_project_path(root, c["reward"]["dismiss"]),
                        paths(c["limited"]["tabs"]), paths(c["limited"]["open"]),
                        [paths(period["closed"]) for period in c["limited"]["periods"]],
                        [paths(period["open"]) for period in c["limited"]["periods"]],
                        _resolve_project_path(root, c["limited"]["unclaimed"]),
                        _resolve_project_path(root, c["limited"]["claimed"]),
                        _resolve_project_path(root, c["limited"]["reward_marker"]),
                        _resolve_project_path(root, c["limited"]["reward_dismiss"]),
                        paths(c["mystic"]["tabs"]), paths(c["mystic"]["open"]),
                        _resolve_project_path(root, c["mystic"]["item"]),
                        _resolve_project_path(root, c["mystic"]["price"]),
                        _resolve_project_path(root, c["mystic"]["buy"]),
                        _resolve_project_path(root, c["mystic"]["confirm"]),
                        _resolve_project_path(root, c["mystic"]["bought"]),
                        _resolve_project_path(root, c["mystic"]["reward"]),
                        _resolve_project_path(root, c["mystic"]["dismiss"]),
                        paths(c["prestige"]["tabs"]), paths(c["prestige"]["open"]),
                        _resolve_project_path(root, c["prestige"]["item"]),
                        _resolve_project_path(root, c["prestige"]["unit_price"]),
                        _resolve_project_path(root, c["prestige"]["popup"]),
                        paths(c["prestige"]["slider_states"]),
                        _resolve_project_path(root, c["prestige"]["slider_max"]),
                        _resolve_project_path(root, c["prestige"]["total_price"]),
                        _resolve_project_path(root, c["prestige"]["bought"]),
                        int(c["prestige"].get("sidebar_swipes", 3)),
                        float(c["prestige"].get("slider_start_ratio", .18)),
                        float(c["prestige"].get("slider_end_ratio", .80)),
                        float(c.get("threshold", .65)), float(c.get("state_threshold", .76)), float(c.get("paid_threshold", .90)), int(c.get("max_steps", 30)), float(c.get("wait_seconds", .8)),
                        float(c.get("limited_wait_seconds", 2.5))))
            elif module_name == "04_quan-doan":
                c = target_config["quan_doan"]
                target = module.QuanDoanRunner(
                    controller._screen, controller.input, controller.logout_action.vision,
                    module.QuanDoanConfig(
                        paths(c["home"]["entry"]), _resolve_project_path(root, c["home"]["anchor"]),
                        paths(c["home"]["menu"]), paths(c["home"]["entrance"]),
                        paths(c["panel"]["markers"]), _resolve_project_path(root, c["panel"]["close"]),
                        paths(c["home"]["markers"]),
                        _resolve_project_path(root, c["registration"]["available"]),
                        _resolve_project_path(root, c["registration"]["done"]),
                        _resolve_project_path(root, c["prayer"]["entry"]),
                        _resolve_project_path(root, c["prayer"]["available"]),
                        _resolve_project_path(root, c["prayer"]["empty"]),
                        _resolve_project_path(root, c["prayer"]["close"]),
                        float(c.get("threshold", .65)), float(c.get("state_threshold", .76)),
                        int(c.get("max_steps", 30)), float(c.get("wait_seconds", .8)),
                        int(c.get("entrance_wait_attempts", 24)),
                        int(c.get("registration_wait_attempts", 24)),
                        float(c.get("home_control_threshold", .30)),
                        float(c.get("registration_done_threshold", .74)),
                        _resolve_project_path(root, c["home"]["route_home"]),
                    ),
                )
            elif module_name == "05_khong-gian-ca-nhan":
                c = target_config["khong_gian_ca_nhan"]
                target = module.KhongGianCaNhanRunner(
                    controller._screen, controller.input, controller.logout_action.vision,
                    module.KhongGianCaNhanConfig(
                        paths(c["home"]["entry"]), paths(c["info"]["markers"]), paths(c["personal"]["markers"]),
                        _resolve_project_path(root, c["panel"]["close"]), paths(c["home"]["markers"]),
                        _resolve_project_path(root, c["like"]["before"]), _resolve_project_path(root, c["like"]["after"]),
                        _resolve_project_path(root, c["like"]["all"]),
                        _resolve_project_path(root, c["share"]["before"]), _resolve_project_path(root, c["share"]["panel"]),
                        _resolve_project_path(root, c["share"]["button"]), paths(c["share"]["after"]),
                        _resolve_project_path(root, c["battle_report"]["entry"]),
                        _resolve_project_path(root, c["battle_report"]["mail_tab_closed"]),
                        _resolve_project_path(root, c["battle_report"]["mail_tab_open"]),
                        _resolve_project_path(root, c["battle_report"]["mail_claim"]),
                        _resolve_project_path(root, c["battle_report"]["mail_claimed"]),
                        _resolve_project_path(root, c["battle_report"]["mail_delete"]),
                        _resolve_project_path(root, c["battle_report"]["close"]),
                        float(c.get("threshold", .65)), float(c.get("state_threshold", .8)),
                        int(c.get("max_steps", 24)), float(c.get("wait_seconds", .8)),
                        int(c.get("state_wait_attempts", 24)),
                        info_close=_resolve_project_path(root, c["info"]["close"]),
                        mail_max_messages=int(c["battle_report"].get("max_messages", 30)),
                    ),
                    home_entry=lambda screen: None,
                    account_level_provider=lambda: "90",
                )
            elif module_name == "06_xa-giao":
                c = target_config["xa_giao"]
                target = module.XaGiaoRunner(controller._screen, controller.input, controller.logout_action.vision,
                    module.XaGiaoConfig(paths(c["home"]["entry"]), paths(c["home"]["menu"]), paths(c["friends"]["entry"]), paths(c["panel"]["markers"]),
                        _resolve_project_path(root, c["panel"]["close"]), paths(c["home"]["markers"]),
                        _resolve_project_path(root, c["heart"]["before"]), _resolve_project_path(root, c["heart"]["after"]),
                        _resolve_project_path(root, c["quick_give"]["before"]), _resolve_project_path(root, c["quick_give"]["after"]),
                        float(c.get("threshold", .65)), float(c.get("state_threshold", .8)),
                        int(c.get("max_steps", 24)), float(c.get("wait_seconds", .8)),
                        float(c.get("home_threshold", .65)),
                        float(c.get("social_control_threshold", .55))))
            elif module_name == "07_truong-thanh":
                c = target_config["truong_thanh"]
                flows = [module.SubFlow(x["name"], paths(x["entry"]), paths(x["free"]), paths(x["spent"]), paths(x["close"]), float(x.get("free_threshold", .90)), paths(x.get("hub_entry", [])), bool(x.get("repeat_free", False)), float(x.get("close_threshold", .70)), paths(x.get("bonus_continue", [])), tuple(x.get("bonus_tap_point", [480, 360])), paths(x.get("recall", [])), paths(x.get("reward_popup", []))) for x in c["flows"]]
                target = module.TruongThanhRunner(controller._screen, controller.input, controller.logout_action.vision,
                    module.TruongThanhConfig(paths(c["home"]["entry"]), paths(c["home"]["menu"]), paths(c["home"]["markers"]),
                        paths(c["close"]), paths(c["bonus_continue"]["templates"]),
                        tuple(c["bonus_continue"]["tap_point"]), paths(c["a4_return"]),
                        paths(c["hub_markers"]),
                        _resolve_project_path(root, c["a1"]["entry"]), _resolve_project_path(root, c["a1"]["view"]),
                        _resolve_project_path(root, c["a1"]["plus_slot"]), paths(c["a1"]["execute"]), paths(c["a1"]["running"]),
                        [tuple(point) for point in c["a1"]["card_centers"]], tuple(c["a1"]["close_point"]),
                        _resolve_project_path(root, c["a1"]["reward"]), tuple(c["a1"]["execution_count_roi"]),
                        _resolve_project_path(root, c["a1"]["locked_slot"]), _resolve_project_path(root, c["a1"]["assist"]),
                        tuple(c["a1"]["assist_count_roi"]), _resolve_project_path(root, c["a1"]["assist_popup"]),
                        _resolve_project_path(root, c["a1"]["assist_confirm"]), tuple(c["a1"]["board_swipe"]),
                        int(c["a1"].get("max_board_swipes", 2)), tuple(c["a1"]["back_point"]),
                        _resolve_project_path(root, c["a2"]["entry"]), paths(c["a2"]["open"]), paths(c["a2"]["main"]),
                        _resolve_project_path(root, c["a2"]["free"]), _resolve_project_path(root, c["a2"]["paid"]),
                        paths(c["a2"]["rewards"]), _resolve_project_path(root, c["a2"]["popup_close"]),
                        paths(c["a2"]["tab_closed"]), paths(c["a2"]["tab_open"]),
                        _resolve_project_path(root, c["a2"]["reward_close"]),
                        _resolve_project_path(root, c["a2"]["chest_glowing"]),
                        _resolve_project_path(root, c["a2"]["chest_closed"]),
                        _resolve_project_path(root, c["a2"]["chest_popup"]),
                        _resolve_project_path(root, c["a2"]["chest_popup_close"]),
                        tuple(c["a2"]["chest_popup_close_point"]),
                        _resolve_project_path(root, c["a2"]["reset_2000"]),
                        _resolve_project_path(root, c["a2"]["reset_2000_marker"]),
                        tuple(c["a2"]["reset_2000_claim_point"]),
                        _resolve_project_path(root, c["a3"]["right_anchor"]), paths(c["a3"]["markers"]), paths(c["a3"]["phong_hau_open"]),
                        paths(c["a3"]["tab_closed"]), paths(c["a3"]["tab_open"]), tuple(c["a3"]["close_point"]),
                        paths(c["a3"]["raise_flag"]), paths(c["a3"]["result"]), tuple(c["a3"]["result_dismiss_point"]),
                        paths(c["a4"]["hub_entry"]), paths(c["a4"]["entry"]), paths(c["a4"]["free"]), paths(c["a4"]["bonus_continue"]),
                        paths(c["a4"]["reward"]), paths(c["a4"]["return"]), paths(c["a4"]["paid"]),
                        tuple(c["a4"]["close_point"]), paths(c["a4"]["recall"]),
                        paths(c["a5"]["normal_free"]), paths(c["a5"]["gold_free"]),
                        _resolve_project_path(root, c["a5"]["normal_select"]),
                        _resolve_project_path(root, c["a5"]["quick"]), _resolve_project_path(root, c["a5"]["initial_close"]),
                        tuple(c["a5"]["normal_quantity_roi"]), tuple(c["a5"]["normal_free_roi"]),
                        tuple(c["a5"]["gold_quantity_roi"]), tuple(c["a5"]["gold_free_roi"]),
                        tuple(c["a5"]["reward_dismiss_point"]), int(c["a5"].get("max_adjustments", 10)),
                        _resolve_project_path(root, c["a5"]["harvest"]),
                        _resolve_project_path(root, c["a5"]["sell_home"]),
                        _resolve_project_path(root, c["a5"]["sell_many"]),
                        _resolve_project_path(root, c["a5"]["sell_action"]),
                        _resolve_project_path(root, c["a5"]["sell_popup"]),
                        _resolve_project_path(root, c["a5"]["sell_confirm"]),
                        _resolve_project_path(root, c["a5"]["sell_close"]),
                        [tuple(point) for point in c["a5"]["quality_points"]],
                        [tuple(point) for point in c["a5"]["protection_points"]],
                        tuple(c["a7"]["free_label_roi"]),
                        float(c.get("state_threshold", .8)), float(c.get("state_margin", .05)),
                        list(c.get("skipped_subflows", [])), flows,
                        float(c.get("threshold", .7)), int(c.get("max_steps", 60)), float(c.get("wait_seconds", .8))))
            elif module_name == "08_vo-tuong":
                c = target_config["vo_tuong"]
                target = module.VoTuongRunner(controller._screen, controller.input, controller.logout_action.vision,
                    module.VoTuongConfig(
                        paths(c["home"]["entry"]), paths(c["home"]["menu"]), paths(c["home"]["markers"]),
                        paths(c["kho"]["markers"]), _resolve_project_path(root, c["kho"]["point_button"]),
                        paths(c["point"]["markers"]),
                        _resolve_project_path(root, c["thien_van"]["banner"]), paths(c["thien_van"]["markers"]),
                        _resolve_project_path(root, c["thien_van"]["paid"]),
                        _resolve_project_path(root, c["nhan_duc"]["banner"]), paths(c["nhan_duc"]["markers"]),
                        _resolve_project_path(root, c["nhan_duc"]["free"]), _resolve_project_path(root, c["nhan_duc"]["paid"]),
                        _resolve_project_path(root, c["chiem_tinh"]["banner"]), paths(c["chiem_tinh"]["markers"]),
                        paths(c["chiem_tinh"]["plus"]), paths(c["chiem_tinh"]["popup"]),
                        _resolve_project_path(root, c["chiem_tinh"]["slider_max"]), tuple(c["chiem_tinh"]["confirm_point"]),
                        tuple(c["chiem_tinh"]["slider_start"]), tuple(c["chiem_tinh"]["slider_end"]),
                        tuple(c["chiem_tinh"]["quantity_plus_point"]),
                        paths(c["chiem_tinh"]["reward"]), tuple(c["chiem_tinh"]["reward_dismiss_point"]),
                        _resolve_project_path(root, c["close"]), _resolve_project_path(root, c["reward"]["marker"]),
                        _resolve_project_path(root, c["reward"]["dismiss"]), float(c.get("threshold", .7)),
                        float(c.get("action_threshold", .8)), float(c.get("state_margin", .05)),
                        float(c.get("close_threshold", .54)), int(c.get("max_steps", 40)),
                        float(c.get("wait_seconds", .8))))
            elif module_name == "09_quan-su":
                c = target_config["quan_su"]
                tg_cfg = c.get("tui_gam", {})
                tg_specs = [
                    module.TuiGamSpec(
                        name=item["name"],
                        chua_tha=_resolve_project_path(root, item["chua_tha"]),
                        da_tha=_resolve_project_path(root, item["da_tha"]),
                    )
                    for item in tg_cfg.get("items", [])
                ]
                gt_cfg = c.get("giao_tranh", {})
                gt_tg_cfg = gt_cfg.get("tui_gam", {})
                gt_tg_specs = [
                    module.TuiGamSpec(
                        name=item["name"],
                        chua_tha=_resolve_project_path(root, item["chua_tha"]),
                        da_tha=_resolve_project_path(root, item["da_tha"]),
                    )
                    for item in gt_tg_cfg.get("items", [])
                ]
                target = module.QuanSuRunner(controller._screen, controller.input, controller.logout_action.vision,
                    module.QuanSuConfig(tuple(c["home"]["military_point"]),
                        tuple(c["home"]["military_close_point"]), paths(c["home"]["tranh_ba_entry"]),
                        paths(c["home"]["markers"]), paths(c["panel"]["main_markers"]),
                        paths(c["panel"]["detail_markers"]), _resolve_project_path(root, c["reward"]["tab"]),
                        _resolve_project_path(root, c["reward"]["button"]), paths(c["reward"]["unfinished"]),
                        _resolve_project_path(root, c["panel"]["close"]), float(c.get("threshold", .6)),
                        int(c.get("max_steps", 60)), float(c.get("wait_seconds", .8)),
                        battles=int(c.get("battles", 5)),
                        tui_gam_specs=tg_specs,
                        tui_gam_threshold=float(tg_cfg.get("threshold", 0.68)),
                        giao_tranh_entry=paths(c["home"].get("giao_tranh_entry", [])),
                        gt_battles=int(gt_cfg.get("battles", 5)),
                        gt_tui_gam_specs=gt_tg_specs,
                        gt_tui_gam_threshold=float(gt_tg_cfg.get("threshold", 0.68)),
                        gt_find_opponent=_resolve_project_path(root, gt_cfg.get("find_opponent")) if gt_cfg.get("find_opponent") else None,
                        gt_result_continue=_resolve_project_path(root, gt_cfg.get("result_continue")) if gt_cfg.get("result_continue") else None,
                        gt_result_banner=_resolve_project_path(root, gt_cfg.get("result_banner")) if gt_cfg.get("result_banner") else None,
                        gt_bai_mien_chien_title=_resolve_project_path(root, gt_cfg.get("bai_mien_chien_title")) if gt_cfg.get("bai_mien_chien_title") else None,
                        gt_bai_mien_chien_confirm=_resolve_project_path(root, gt_cfg.get("bai_mien_chien_confirm")) if gt_cfg.get("bai_mien_chien_confirm") else None,
                        gt_main_markers=paths(gt_cfg.get("main_markers", [])),
                    ),
                    account_level_provider=lambda: "90",
                )
            elif module_name == "10_nhiem-vu":
                c = target_config["nhiem_vu"]
                target = module.NhiemVuRunner(
                    controller._screen, controller.input, controller.logout_action.vision,
                    module.NhiemVuConfig(
                        paths(c["home"]["entry"]), paths(c["home"]["menu"]),
                        paths(c["home"]["markers"]), paths(c["panel"]["markers"]),
                        tuple(c["panel"]["close_point"]),
                        _resolve_project_path(root, c["panel"]["close_template"]),
                        tuple(c["blocked_popup"]["close_point"]),
                        _resolve_project_path(root, c["blocked_popup"]["den"]),
                        _resolve_project_path(root, c["panel"]["daily_open"]),
                        _resolve_project_path(root, c["panel"]["daily_closed"]),
                        _resolve_project_path(root, c["reward"]["claim_button"]),
                        paths(c["reward"]["available"]), paths(c["reward"]["claimed"]),
                        paths(c["reward"]["unavailable"]), float(c.get("threshold", .6)),
                        float(c.get("state_threshold", .76)), int(c.get("max_steps", 30)),
                        float(c.get("wait_seconds", .8)),
                        tuple(c["reward"].get("dismiss_point", (480, 430))),
                    )
                )

            assert target is not None
            targets.append(target)
            print(f"Instantiated target {module_name} successfully!")

        controller.config.home_targets = targets
        assert len(targets) == 10
        print(f"\nAll 10 targets instantiated and wired to controller successfully!")

if __name__ == "__main__":
    test_full_pipeline_controller_and_targets_factory()
