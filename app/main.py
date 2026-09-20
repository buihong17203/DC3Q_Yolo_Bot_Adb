from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ============================================================
# HỖ TRỢ CHẠY TRỰC TIẾP
# ============================================================
#
# Cho phép cả:
#
#     python -m app.main
#
# và:
#
#     python app/main.py
#
# ============================================================

if __package__ in {
    None,
    "",
}:

    project_root = (
        Path(__file__)
        .resolve()
        .parents[1]
    )

    if str(project_root) not in sys.path:
        sys.path.insert(
            0,
            str(project_root),
        )


from app.adb import (
    ADBClient,
    ADBDeviceManager,
    ADBError,
    ADBNotFoundError,
)

from app.core.config import settings
from app.core.logger import (
    configure_logging,
    get_logger,
)


configure_logging()

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        prog="dc3q-yolo-bot-adb",
        description=(
            "DC3Q YOLO BOT ADB - "
            "ADB device controller"
        ),
    )

    parser.add_argument(
        "--adb-version",
        action="store_true",
        help="Hiển thị phiên bản ADB.",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help=(
            "Liệt kê tất cả thiết bị ADB "
            "kể cả offline/unauthorized."
        ),
    )

    parser.add_argument(
        "--serial",
        type=str,
        default=None,
        help=(
            "Kiểm tra một device theo serial."
        ),
    )

    parser.add_argument(
        "--require-device",
        action="store_true",
        help=(
            "Trả exit code != 0 nếu không có "
            "thiết bị online."
        ),
    )

    return parser


def print_devices(
    manager: ADBDeviceManager,
    online_only: bool,
) -> None:

    devices = manager.refresh(
        online_only=online_only
    )

    if not devices:

        print(
            "Không phát hiện thiết bị ADB."
        )

        return

    print(
        f"Phát hiện {len(devices)} thiết bị:"
    )

    for device in devices:

        info = manager.get_info(
            device.serial
        )

        if info is None:

            print(
                f"  {device.serial}"
            )

            continue

        print(
            "  "
            f"{info.serial}"
            " | "
            f"state={info.state}"
            " | "
            f"model={info.model or '-'}"
            " | "
            f"product={info.product or '-'}"
            " | "
            f"device={info.device or '-'}"
        )


def main(
    argv: list[str] | None = None,
) -> int:

    parser = build_parser()

    args = parser.parse_args(
        argv
    )

    settings.ensure_directories()

    logger.info(
        "Starting %s",
        settings.app_name,
    )

    client = ADBClient()

    try:

        # Kiểm tra ADB tồn tại.
        adb_version = client.version()

        logger.info(
            "ADB available"
        )

        # Đảm bảo ADB server đang chạy.
        client.start_server()

    except ADBNotFoundError:

        logger.error(
            "Không tìm thấy adb.exe. "
            "Hãy cài Android Platform Tools hoặc "
            "đặt ADB_PATH đúng trong môi trường."
        )

        return 2

    except ADBError as exc:

        logger.error(
            "Không thể khởi tạo ADB: %s",
            exc,
        )

        return 3

    # ========================================================
    # ADB VERSION
    # ========================================================

    if args.adb_version:

        print(
            adb_version
        )

        return 0

    manager = ADBDeviceManager(
        client=client
    )

    try:

        # ====================================================
        # KIỂM TRA DEVICE CỤ THỂ
        # ====================================================

        if args.serial:

            manager.refresh(
                online_only=False
            )

            device = manager.get(
                args.serial
            )

            if device is None:

                print(
                    f"Không tìm thấy device: "
                    f"{args.serial}"
                )

                return 4

            info = manager.get_info(
                args.serial
            )

            print(
                f"Serial: {device.serial}"
            )

            if info is not None:

                print(
                    f"State: {info.state}"
                )

                print(
                    f"Model: "
                    f"{info.model or '-'}"
                )

                print(
                    f"Product: "
                    f"{info.product or '-'}"
                )

            if device.is_online():

                try:

                    width, height = (
                        device.get_screen_size()
                    )

                    print(
                        "Screen: "
                        f"{width}x{height}"
                    )

                except ADBError as exc:

                    logger.warning(
                        "[%s] Không lấy được screen size: %s",
                        device.serial,
                        exc,
                    )

            return 0

        # ====================================================
        # LIST DEVICES
        # ====================================================

        print_devices(
            manager,
            online_only=not args.list,
        )

        online_count = (
            manager.online_count
        )

        logger.info(
            "ADB devices: total=%d online=%d",
            manager.count,
            online_count,
        )

        if (
            args.require_device
            and online_count == 0
        ):

            logger.error(
                "Không có thiết bị ADB online."
            )

            return 5

    except ADBError as exc:

        logger.error(
            "ADB error: %s",
            exc,
        )

        return 6

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )