from __future__ import annotations

import argparse
from datetime import date
import logging
import signal
import sys
from pathlib import Path

from app.adb import AdbClient, AdbError, AdbResolver
from app.adb.commands import get_android_properties


LOGGER = logging.getLogger("dc3q")


def configure_logging(root: Path | None = None, *, day: date | None = None) -> Path:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    log_dir = root / "logs" / "logs_days_runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"dc3q_{(day or date.today()):%Y-%m-%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )
    return log_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DC3Q Bot - ADB bootstrap/runtime entrypoint"
    )
    parser.add_argument(
        "--run",
        default=None,
        help="Đường dẫn YAML workflow; login_only.yaml và multi_manager.yaml hiện chạy luồng đăng nhập/account.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Số worker tối đa; tầng ADB bootstrap chưa chạy workflow song song.",
    )
    parser.add_argument(
        "--adb-path",
        default="adb",
        help="Đường dẫn adb.exe hoặc adb trong PATH.",
    )
    parser.add_argument(
        "--no-server-start",
        action="store_true",
        help="Không tự gọi 'adb start-server'.",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Đọc thêm thông tin Android từ thiết bị ready.",
    )
    return parser


def install_ctrl_c_handler() -> None:
    def _handle_ctrl_c(signum: int, frame: object) -> None:
        LOGGER.warning("Nhận Ctrl+C -> dừng chương trình...")
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle_ctrl_c)


def run(args: argparse.Namespace) -> int:
    from app.workflow.script_loader import ScriptLoader

    adb = AdbClient(args.adb_path)
    resolver = AdbResolver(adb)

    LOGGER.info("ADB: %s", args.adb_path)
    LOGGER.info("Kiểm tra ADB executable...")
    LOGGER.info("%s", adb.version())

    if not args.no_server_start:
        LOGGER.info("Khởi động/đảm bảo ADB server...")
        resolver.ensure_server()

    devices = resolver.list_devices()
    if not devices:
        LOGGER.warning("ADB đang hoạt động nhưng chưa tìm thấy thiết bị nào.")
        LOGGER.info("Hãy kiểm tra bằng: adb devices -l")
        return 0

    LOGGER.info("Tìm thấy %d thiết bị:", len(devices))
    for index, device in enumerate(devices, start=1):
        status = "READY" if device.is_ready else device.state.upper()
        LOGGER.info(
            "  [%d] %s | state=%s | model=%s | product=%s",
            index, device.serial, status, device.model or "-", device.product or "-",
        )
        if args.inspect and device.is_ready:
            try:
                props = get_android_properties(adb, device)
                LOGGER.info(
                    "      Android=%s | SDK=%s | Manufacturer=%s | Model=%s",
                    props.get("android", "-"), props.get("sdk", "-"),
                    props.get("manufacturer", "-"), props.get("model", "-"),
                )
            except AdbError as exc:
                LOGGER.warning("      Không đọc được properties: %s", exc)

    ready = resolver.find_ready()
    LOGGER.info("Thiết bị READY: %d/%d", len(ready), len(devices))

    if not args.run:
        LOGGER.info("ADB bootstrap hoàn tất. Chưa chạy workflow.")
        return 0

    workflow_path = Path(args.run).resolve()
    if not workflow_path.is_file():
        LOGGER.warning("Workflow chưa tồn tại: %s", workflow_path)
        return 1

    LOGGER.info("Workflow được yêu cầu: %s", workflow_path)
    loader = ScriptLoader()
    workflow = loader.load(workflow_path)

    if workflow.get("name") == "multi_manager":
        return run_multi_manager(adb, ready, workflow_path, workflow, args.max_workers)

    if workflow.get("type") == "account_login":
        return run_account_login_workflow(adb, ready, workflow_path, workflow, args.max_workers)

    LOGGER.info("Workflow chưa có executor: %s", workflow_path.name)
    return 1


def _project_root(workflow_path: Path) -> Path:
    # app.main được chạy từ project root trong workflow CLI; resolve upward
    # cũng giúp chạy bằng đường dẫn tuyệt đối từ thư mục khác.
    for candidate in (Path.cwd().resolve(), workflow_path.parent.parent.resolve()):
        if (candidate / "app").is_dir() and (candidate / "config").is_dir():
            return candidate
    return Path.cwd().resolve()


def _resolve_project_path(root: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


def run_multi_manager(adb: AdbClient, devices, workflow_path: Path, workflow: dict, max_workers: int) -> int:
    from app.workflow.script_loader import ScriptLoader

    entries = workflow.get("workflows", [])
    if not isinstance(entries, list) or not entries:
        raise ValueError("multi_manager.workflows phải là danh sách workflow con")

    root = _project_root(workflow_path)
    loader = ScriptLoader()
    LOGGER.info("Multi-manager: %d workflow con.", len(entries))

    # Hiện tại mỗi device chạy chuỗi workflow theo thứ tự; max_workers chỉ
    # giới hạn số device được cấp worker. Không tự tạo workflow login riêng.
    selected = list(devices[:max_workers])
    if not selected:
        LOGGER.warning("Không có thiết bị READY để chạy multi-manager.")
        return 0

    from app.workflow.account_login import AccountLoginController

    login_jobs = []
    for entry in entries:
        child_path = _resolve_project_path(root, entry)
        child = loader.load(child_path)
        LOGGER.info("Workflow con: %s", child_path)
        if child.get("type") != "account_login":
            raise ValueError(f"Workflow con chưa có executor: {child_path}")
        login_jobs.append((child_path, child))

    # AccountLoginController hiện là stateful theo device và account queue.
    # Chạy tuần tự trên từng device để không lấy trùng account khi max_workers=1.
    if len(login_jobs) == 1:
        return run_account_login_workflow(adb, selected, login_jobs[0][0], login_jobs[0][1], max_workers)

    raise ValueError("multi_manager hiện chỉ hỗ trợ 1 workflow account_login trong một chuỗi")


def load_login_random_events(root: Path, unexpected: dict) -> list[tuple[Path, Path, float]]:
    import yaml

    events = []
    for event in unexpected.values():
        if not isinstance(event, dict):
            continue
        if event.get("state") and event.get("close"):
            events.append((
                _resolve_project_path(root, event["state"]),
                _resolve_project_path(root, event["close"]),
                float(event.get("threshold", 0.75)),
            ))
    for config_value in unexpected.get("event_configs", []):
        config_path = _resolve_project_path(root, config_value)
        event_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        for step in (event_config.get("random_event", {}) or {}).get("steps", []):
            events.append((
                _resolve_project_path(root, step["state"]),
                _resolve_project_path(root, step["close"]),
                float(step.get("threshold", 0.75)),
            ))
    return events


def run_account_login_workflow(adb: AdbClient, devices, workflow_path: Path, workflow: dict, max_workers: int) -> int:
    import yaml
    from concurrent.futures import ThreadPoolExecutor
    from app.accounts.manager import AccountManager
    from app.workflow.account_login import AccountLoginController, AccountLoginConfig
    from app.accounts.runtime import AccountRuntime

    root = _project_root(workflow_path)
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
    if not home_target_values and workflow.get("home_target"):
        home_target_values.append(workflow["home_target"])

    def paths(values):
        return [_resolve_project_path(root, value) for value in values]

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
    runtime.maybe_rollover()
    task_by_module = {
        "01_tam-quoc-lenh": ["Tam_Quoc_Lenh"],
        "02_hoat-dong": ["Hoat_Dong"],
        "03_cua-hang": ["Cua_Hang"],
        "04_quan-doan": ["Quan_Doan"],
        "05_khong-gian-ca-nhan": ["Khong_Gian_Ca_Nhan"],
        "06_xa-giao": ["Xa_Giao"],
    }
    active_tasks = []
    for module_name, target_config in home_target_specs:
        if module_name == "07_truong-thanh":
            skipped = set(target_config["truong_thanh"].get("skipped_subflows", []))
            active_tasks.append("TT_A1_Bao_Vat")
            if "A2_tuong-an" not in skipped:
                active_tasks.append("TT_A2_Tuong_An")
        else:
            active_tasks.extend(task_by_module.get(module_name, []))
    loaded = accounts.load(
        runtime_status=runtime.statuses(),
        limit=(int(workflow["account_limit"]) if workflow.get("account_limit") is not None else None),
        active_tasks=active_tasks,
    )
    LOGGER.info("Accounts: %d account(s) từ %s", len(loaded), _resolve_project_path(root, cfg["account_file"]))
    if not loaded:
        LOGGER.warning("accounts.csv không có account khả dụng.")
        return 0

    def coord(name):
        value = (login.get("coordinates", {}) or {}).get(name)
        return tuple(value) if value else None

    from app.actions.dc3q.stars import LogoutTemplates
    logout_templates = LogoutTemplates(
        open_tuychon=_resolve_project_path(root, logout_cfg["templates"]["open_tuychon"]),
        open_cdnd=_resolve_project_path(root, logout_cfg["templates"]["open_cdnd"]),
        open_dtk=_resolve_project_path(root, logout_cfg["templates"]["open_dtk"]),
        confirm_dtk=_resolve_project_path(root, logout_cfg["templates"]["confirm_dtk"]),
        home_anchor_template=_resolve_project_path(root, logout_cfg["home_anchor_template"]),
        home_anchor_roi=tuple(logout_cfg.get("home_anchor_roi", (840, 480, 1000, 575))),
        avatar_mirror_offset=tuple(logout_cfg.get("avatar_mirror_offset", (-8, 21))),
    )

    def make(device):
        controller = AccountLoginController(
            adb, device, accounts, AccountLoginConfig(
                login_templates=[_resolve_project_path(root, x) for x in templates.get("login_screen", [])],
                logged_in_templates=[_resolve_project_path(root, x) for x in templates.get("logged_in", [])],
                username_template=_resolve_project_path(root, controls["username"]),
                password_templates=[_resolve_project_path(root, x) for x in controls.get("password", [])],
                submit_template=_resolve_project_path(root, controls["submit"]),
                username=coord("username"), password=coord("password"), submit=coord("submit"),
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
                save_knb_balance=lambda account_id, value: __import__(
                    "app.accounts.writer", fromlist=["write_account_balance"]
                ).write_account_balance(
                    _resolve_project_path(root, workflow.get("account_file", cfg["account_file"])),
                    account_id, "KNB", value,
                ),
                knb_icon=_resolve_project_path(root, "config/dc3q/item/item_knb.png"),
                cutoff_hour=int(workflow.get("cutoff_hour", 22)),
                cutoff_minute=int(workflow.get("cutoff_minute", 59)),
                persistent_daily=bool(workflow.get("persistent_daily", True)),
            ),
            runtime,
        )
        from importlib import import_module
        targets = []
        for module_name, target_config in home_target_specs:
            module = import_module(f"app.actions.dc3q.targets.{module_name}")
            root_key = next(iter(target_config))
            if not bool(target_config[root_key].get("enabled", True)):
                LOGGER.info("Bỏ qua target đã tắt: %s", module_name)
                continue
            if module_name == "01_tam-quoc-lenh":
                from app.accounts.writer import write_account_balance

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
                        action_threshold=float(target_cfg.get("action_threshold", 0.85)),
                        advance_popup_marker=_resolve_project_path(root, target_cfg["advance_popup"]["marker"]),
                        advance_popup_close=_resolve_project_path(root, target_cfg["advance_popup"]["close"]),
                        inactivity_marker=_resolve_project_path(root, target_cfg["inactivity"]["marker"]),
                        inactivity_return=_resolve_project_path(root, target_cfg["inactivity"]["return"]),
                        threshold=float(target_cfg.get("threshold", 0.60)),
                        max_steps=int(target_cfg.get("max_steps", 30)),
                        wait_seconds=float(target_cfg.get("wait_seconds", 0.8)),
                    ),
                    save_que_balance=lambda value, ctl=controller, path=accounts_path: (
                        write_account_balance(path, ctl.current.id, "Que-Lanh", value)
                        if ctl.current else (_ for _ in ()).throw(RuntimeError("Thiếu account hiện tại"))
                    ),
                    save_nguyen_balance=lambda value, ctl=controller, path=accounts_path: (
                        write_account_balance(path, ctl.current.id, "Nguyen-Linh-Ngoc", value)
                        if ctl.current else (_ for _ in ()).throw(RuntimeError("Thiếu account hiện tại"))
                    ),
                )
            elif module_name == "02_hoat-dong":
                from app.accounts.writer import read_attendance_day, write_attendance_day

                target_cfg = target_config["hoat_dong"]
                accounts_path = _resolve_project_path(root, workflow.get("account_file", cfg["account_file"]))
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
                        attendance_makeup=(
                            _resolve_project_path(root, target_cfg["attendance"]["makeup"])
                            if target_cfg["attendance"].get("makeup") else None
                        ),
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
                    ),
                    attendance_day=lambda ctl=controller, path=accounts_path: (
                        read_attendance_day(path, ctl.current.id) if ctl.current else None
                    ),
                    save_attendance_day=lambda day, ctl=controller, path=accounts_path: (
                        write_attendance_day(path, ctl.current.id, day)
                        if ctl.current else (_ for _ in ()).throw(RuntimeError("Thiếu account hiện tại"))
                    ),
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
                        float(c.get("threshold", .65)), float(c.get("state_threshold", .8)),
                        int(c.get("max_steps", 24)), float(c.get("wait_seconds", .8)),
                        int(c.get("state_wait_attempts", 24)),
                        info_close=_resolve_project_path(root, c["info"]["close"]),
                    ),
                    home_entry=lambda screen: controller.logout_action._avatar_from_noi_chinh(
                        screen, logout_templates, controller.config.logout_threshold,
                    ),
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
                flows = [module.SubFlow(x["name"], paths(x["entry"]), paths(x["free"]), paths(x["spent"]), paths(x["close"]), float(x.get("free_threshold", .90)), paths(x.get("hub_entry", [])), bool(x.get("repeat_free", False)), float(x.get("close_threshold", .70)), paths(x.get("bonus_continue", [])), tuple(x.get("bonus_tap_point", [480, 360]))) for x in c["flows"]]
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
                        _resolve_project_path(root, c["a2"]["chest_popup"]),
                        _resolve_project_path(root, c["a2"]["chest_popup_close"]),
                        tuple(c["a2"]["chest_popup_close_point"]),
                        _resolve_project_path(root, c["a2"]["reset_2000"]),
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
                        float(c.get("state_threshold", .8)), float(c.get("state_margin", .05)),
                        list(c.get("skipped_subflows", [])), flows,
                        float(c.get("threshold", .7)), int(c.get("max_steps", 60)), float(c.get("wait_seconds", .8))))
            elif module_name == "08_vo-tuong":
                c = target_config["vo_tuong"]
                target = module.VoTuongRunner(controller._screen, controller.input, controller.logout_action.vision,
                    module.VoTuongConfig(paths(c["home"]["entry"]), paths(c["home"]["menu"]), paths(c["home"]["markers"]),
                        paths(c["panel"]["markers"]), _resolve_project_path(root, c["panel"]["close"]),
                        _resolve_project_path(root, c["reward"]["marker"]), _resolve_project_path(root, c["reward"]["dismiss"]),
                        paths(c["safe_actions"]), paths(c["forbidden_actions"]), float(c.get("threshold", .6)), int(c.get("max_steps", 20)), float(c.get("wait_seconds", .8))))
            elif module_name == "09_quan-su":
                c = target_config["quan_su"]
                target = module.QuanSuRunner(controller._screen, controller.input, controller.logout_action.vision,
                    module.QuanSuConfig(paths(c["home"]["entry"]), paths(c["home"]["menu"]), paths(c["home"]["markers"]),
                        paths(c["panel"]["markers"]), _resolve_project_path(root, c["panel"]["close"]),
                        _resolve_project_path(root, c["reward"]["button"]), paths(c["reward"]["claimed"]),
                        paths(c["forbidden"]["unfinished_battle"]), float(c.get("threshold", .6)), int(c.get("max_steps", 16)), float(c.get("wait_seconds", .8))))
            else:
                raise ValueError(f"Home target chưa hỗ trợ: {module_name}")
            if module_name == "07_truong-thanh":
                targets.append(module.TruongThanhRuntimeStep(target, "TT_A1_BAO_VAT", "_run_a1"))
                skipped = set(target.config.skipped_subflows)
                if "A2_tuong-an" not in skipped:
                    targets.append(module.TruongThanhRuntimeStep(target, "TT_A2_TUONG_AN", "_run_a2"))
                if "A3_chua-cong" not in skipped:
                    targets.append(module.TruongThanhRuntimeStep(target, "TT_A3_CHUA_CONG", "_run_a3"))
                if "A4_ve-tuong" not in skipped:
                    targets.append(module.TruongThanhRuntimeStep(target, "TT_A4_VE_TUONG", "_run_a4"))
            else:
                targets.append(target)
        controller.config.home_targets = targets
        return controller

    worker_count = max(1, min(int(max_workers), len(devices)))
    LOGGER.info("Account-login: %d device(s), tối đa %d worker(s).", len(devices), worker_count)
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = []
        for device in devices[:worker_count]:
            LOGGER.info("Login workflow: %s -> %s", device.serial, workflow_path)
            futures.append(pool.submit(make(device).run))
        for future in futures:
            future.result()
    LOGGER.info("Account-login workflow kết thúc: %s", workflow_path.name)
    return 0

def main() -> int:
    configure_logging()
    install_ctrl_c_handler()
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run(args)
    except KeyboardInterrupt:
        LOGGER.warning("Đã dừng sạch bởi Ctrl+C.")
        return 130
    except AdbError as exc:
        LOGGER.error("%s", exc)
        return 1
    except Exception:
        LOGGER.exception("Lỗi không mong muốn.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
