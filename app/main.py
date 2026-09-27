from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from app.adb import AdbClient, AdbError, AdbResolver
from app.adb.commands import get_android_properties


LOGGER = logging.getLogger("dc3q")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


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
    home_events = []
    enemy_raid = unexpected.get("enemy_raid", {}) or {}
    if enemy_raid.get("state") and enemy_raid.get("close"):
        home_events.append((
            _resolve_project_path(root, enemy_raid["state"]),
            _resolve_project_path(root, enemy_raid["close"]),
            float(enemy_raid.get("threshold", 0.75)),
        ))

    accounts = AccountManager(_resolve_project_path(root, workflow.get("account_file", cfg["account_file"])))
    runtime = AccountRuntime(root, reset_hour=int(workflow.get("reset_hour", 23)))
    runtime.maybe_rollover()
    loaded = accounts.load(runtime_status=runtime.statuses())
    LOGGER.info("Accounts: %d account(s) từ %s", len(loaded), _resolve_project_path(root, cfg["account_file"]))
    if not loaded:
        LOGGER.warning("accounts.csv không có account khả dụng.")
        return 0

    def coord(name):
        value = (login.get("coordinates", {}) or {}).get(name)
        return tuple(value) if value else None

    from app.actions.tai_khoan import LogoutTemplates
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
        return AccountLoginController(
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
            ),
            runtime,
        )

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
