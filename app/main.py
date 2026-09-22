from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from app.accounts import AccountManager, AccountRepository
from app.adb import ADBClient, ADBDeviceManager, ADBError, ADBNotFoundError
from app.automation import AutomationEngine
from app.core.config import settings
from app.core.game_day import DailyRuntimeStore, GameDayClock
from app.core.logger import configure_logging, get_logger
from app.core.shutdown import terminate_child_processes
from app.devices import DeviceManager, WorkerState

configure_logging()
logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dc3q-yolo-bot-adb",
        description="DC3Q YOLO BOT ADB - multi-device ADB + Vision + Automation runner",
    )
    parser.add_argument("--version", action="store_true", help="Hiển thị phiên bản chương trình.")
    parser.add_argument("--adb-version", action="store_true", help="Hiển thị phiên bản ADB.")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Liệt kê tất cả thiết bị ADB, kể cả offline/unauthorized.",
    )
    parser.add_argument("--serial", type=str, default=None, help="Kiểm tra một device theo serial.")
    parser.add_argument(
        "--require-device",
        action="store_true",
        help="Trả exit code != 0 nếu không có thiết bị online.",
    )
    parser.add_argument(
        "--run",
        metavar="SCENARIO",
        type=str,
        default=None,
        help="Chạy một kịch bản YAML trên tất cả thiết bị online.",
    )
    parser.add_argument(
        "--validate-scenario",
        metavar="SCENARIO",
        type=str,
        default=None,
        help="Đọc và kiểm tra cấu trúc YAML cơ bản, không cần ADB/device.",
    )
    parser.add_argument(
        "--accounts",
        type=str,
        default=None,
        help="File tài khoản .xlsx/.csv/.json. Mặc định lấy từ config.yaml.",
    )
    parser.add_argument(
        "--no-accounts",
        action="store_true",
        help="Không dùng account queue; mỗi device chỉ chạy scenario một lần.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Giới hạn số device worker chạy đồng thời.",
    )
    return parser


def _resolve_scenario(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()

    candidates = [settings.root_dir / raw]
    # `--run foo.yaml` means scripts/foo.yaml; `--run scripts/foo.yaml`
    # is already project-relative and must not become scripts/scripts/foo.yaml.
    if not raw.parts or raw.parts[0].casefold() != settings.automation.scripts_dir.name.casefold():
        candidates.append(settings.automation.scripts_dir / raw)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def print_devices(manager: ADBDeviceManager, online_only: bool) -> None:
    devices = manager.refresh(online_only=online_only)
    if not devices:
        print("Không phát hiện thiết bị ADB.")
        return

    print(f"Phát hiện {len(devices)} thiết bị:")
    for device in devices:
        info = manager.get_info(device.serial)
        if info is None:
            print(f"  {device.serial}")
            continue
        print(
            f"  {info.serial} | state={info.state} | model={info.model or '-'} "
            f"| product={info.product or '-'} | device={info.device or '-'}"
        )


def _validate_scenario(path: Path) -> int:
    try:
        data = AutomationEngine.load_scenario(path)
    except Exception as exc:
        logger.error("Scenario không hợp lệ: %s", exc)
        return 7

    steps = data.get("steps", []) or []
    state_machine = data.get("state_machine")
    print(f"Scenario: {data.get('name', path.stem)}")
    print(f"Path: {path}")
    print(f"Steps: {len(steps) if isinstance(steps, list) else 'INVALID'}")
    print(f"State machine: {'yes' if state_machine else 'no'}")
    if not isinstance(steps, list):
        logger.error("scenario.steps phải là list")
        return 7
    return 0


def _build_account_manager(args: argparse.Namespace) -> AccountManager | None:
    if args.no_accounts:
        return None

    explicit = args.accounts is not None
    source = Path(args.accounts).expanduser() if explicit else settings.accounts.source_file
    if not source.is_absolute():
        source = settings.root_dir / source

    if not source.is_file():
        if explicit:
            raise FileNotFoundError(f"Không tìm thấy file tài khoản: {source}")
        logger.info(
            "Không có file tài khoản mặc định %s; chạy mỗi device một lần không dùng account queue.",
            source,
        )
        return None

    repository = AccountRepository(source)
    runtime_store = DailyRuntimeStore(
        settings.accounts.runtime_file,
        settings.accounts.archive_dir,
        clock=GameDayClock(settings.accounts.reset_hour),
    )
    manager = AccountManager(
        repository,
        persist_status=True,
        retry_failed=settings.accounts.retry_failed_login,
        max_attempts=settings.accounts.login_retry_count,
        runtime_store=runtime_store,
    )
    stats = manager.stats
    logger.info(
        "Accounts loaded: total=%d ready=%d done=%d failed=%d disabled=%d",
        stats.total,
        stats.ready,
        stats.done,
        stats.failed,
        stats.disabled,
    )
    return manager


def _run_automation(
    args: argparse.Namespace,
    adb_manager: ADBDeviceManager,
) -> int:
    scenario = _resolve_scenario(args.run)
    validation = _validate_scenario(scenario)
    if validation != 0:
        return validation

    try:
        account_manager = _build_account_manager(args)
    except Exception as exc:
        logger.error("Không thể tải accounts: %s", exc)
        return 8

    manager = DeviceManager(
        scenario,
        adb_manager=adb_manager,
        account_manager=account_manager,
        max_workers=args.max_workers,
    )
    snapshots = manager.run_until_complete()
    if not snapshots:
        logger.error("Không có thiết bị ADB online để chạy automation.")
        return 5

    print("\nKết quả worker:")
    for item in snapshots:
        print(
            f"  {item.serial} | state={item.state.value} | completed={item.completed_accounts} "
            f"| failed_runs={item.failed_runs} | error={item.last_error or '-'}"
        )

    failed = any(item.state == WorkerState.ERROR for item in snapshots)
    if account_manager is not None:
        stats = account_manager.stats
        print(
            "Accounts: "
            f"total={stats.total} ready={stats.ready} in_use={stats.in_use} "
            f"done={stats.done} failed={stats.failed} disabled={stats.disabled}"
        )
        failed = failed or stats.failed > 0

    if manager.interrupted:
        return 130
    return 9 if failed else 0


def _main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings.ensure_directories()

    if args.version:
        print(f"{settings.app_name} {settings.version}")
        return 0

    if args.validate_scenario:
        return _validate_scenario(_resolve_scenario(args.validate_scenario))

    logger.info("Starting %s", settings.app_name)
    client = ADBClient()

    try:
        adb_version = client.version()
        logger.info("ADB available")
        client.start_server()
    except ADBNotFoundError:
        logger.error(
            "Không tìm thấy adb.exe. Hãy cài Android Platform Tools hoặc đặt ADB_PATH đúng trong môi trường."
        )
        return 2
    except ADBError as exc:
        logger.error("Không thể khởi tạo ADB: %s", exc)
        return 3

    if args.adb_version:
        print(adb_version)
        return 0

    manager = ADBDeviceManager(client=client)

    if args.run:
        return _run_automation(args, manager)

    try:
        if args.serial:
            manager.refresh(online_only=False)
            device = manager.get(args.serial)
            if device is None:
                print(f"Không tìm thấy device: {args.serial}")
                return 4

            info = manager.get_info(args.serial)
            print(f"Serial: {device.serial}")
            if info is not None:
                print(f"State: {info.state}")
                print(f"Model: {info.model or '-'}")
                print(f"Product: {info.product or '-'}")

            if device.is_online():
                try:
                    width, height = device.get_screen_size()
                    print(f"Screen: {width}x{height}")
                except ADBError as exc:
                    logger.warning("[%s] Không lấy được screen size: %s", device.serial, exc)
            return 0

        print_devices(manager, online_only=not args.list)
        online_count = manager.online_count
        logger.info("ADB devices: total=%d online=%d", manager.count, online_count)
        if args.require_device and online_count == 0:
            logger.error("Không có thiết bị ADB online.")
            return 5
    except ADBError as exc:
        logger.error("ADB error: %s", exc)
        return 6

    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        # Ctrl+C kết thúc Python theo đường thoát bình thường để PowerShell
        # nhận lại prompt hiện tại, không cần mở terminal mới.
        logger.warning("Nhận Ctrl+C: dừng toàn bộ child process của project")
        terminate_child_processes(timeout=1.0)
        return 130
    except Exception as exc:
        # Không để exception chưa bắt làm văng traceback ra ngoài CLI.
        # Cleanup rồi trả exit code để PowerShell nhận lại prompt.
        logger.exception("Lỗi không xử lý được ở CLI: %s", exc)
        terminate_child_processes(timeout=1.0)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
