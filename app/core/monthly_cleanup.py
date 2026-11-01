from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

LOGGER = logging.getLogger("dc3q")

DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DEFAULT_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")


class MonthlyCleanup:
    """Quản lý việc dọn dẹp định kỳ hàng tháng cho thư mục docs và logs.

    Vào lần đầu chạy của mùng 1 hàng tháng (hoặc lần đầu chạy trong tháng mới),
    hệ thống sẽ tự động quét và xóa toàn bộ phần ghi chép/logs của các tháng cũ
    trong docs/docs_days_runtime và logs/logs_days_runtime.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        docs_dir: str | Path | None = None,
        logs_dir: str | Path | None = None,
        state_file: str | Path | None = None,
        timezone: ZoneInfo = DEFAULT_TIMEZONE,
    ) -> None:
        self.root = (
            Path(root).resolve()
            if root
            else Path(__file__).resolve().parents[2]
        )
        self.docs_dir = (
            Path(docs_dir)
            if docs_dir and Path(docs_dir).is_absolute()
            else self.root / (docs_dir or "docs/docs_days_runtime")
        )
        self.logs_dir = (
            Path(logs_dir)
            if logs_dir and Path(logs_dir).is_absolute()
            else self.root / (logs_dir or "logs/logs_days_runtime")
        )
        self.state_file = (
            Path(state_file)
            if state_file and Path(state_file).is_absolute()
            else self.root / (state_file or "data/accounts/monthly_cleanup.json")
        )
        self.timezone = timezone

    def get_state(self) -> dict:
        """Đọc trạng thái dọn dẹp gần nhất."""
        if not self.state_file.exists():
            return {}
        try:
            with self.state_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            LOGGER.warning("Không thể đọc file trạng thái cleanup %s: %s", self.state_file, exc)
            return {}

    def save_state(self, state: dict) -> None:
        """Ghi nhận trạng thái dọn dẹp."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with self.state_file.open("w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            LOGGER.warning("Không thể ghi file trạng thái cleanup %s: %s", self.state_file, exc)

    def get_record_year_month(self, file_path: Path) -> tuple[int, int] | None:
        """Trích xuất (năm, tháng) của file ghi chép.

        1. Ưu tiên tìm chuỗi ngày YYYY-MM-DD trong tên file.
        2. Nếu không có trong tên, lấy thời gian sửa đổi (mtime) của file.
        """
        match = DATE_PATTERN.search(file_path.name)
        if match:
            try:
                return int(match.group(1)), int(match.group(2))
            except ValueError:
                pass

        try:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=self.timezone)
            return mtime.year, mtime.month
        except OSError:
            return None

    def is_old_month_file(
        self, file_path: Path, current_year: int, current_month: int
    ) -> bool:
        """Kiểm tra xem file có thuộc về tháng cũ (trước tháng hiện tại) hay không."""
        if not file_path.is_file():
            return False

        # Không bao giờ xóa file hệ thống / giữ chỗ
        if file_path.name in (".gitkeep", ".gitignore", "readme.md", "README.md"):
            return False

        ym = self.get_record_year_month(file_path)
        if ym is None:
            return False

        return ym < (current_year, current_month)

    def clean_directory(
        self, directory: Path, current_year: int, current_month: int
    ) -> list[Path]:
        """Quét và xóa tất cả file thuộc tháng cũ trong thư mục chỉ định."""
        if not directory.exists() or not directory.is_dir():
            return []

        deleted: list[Path] = []
        for item in directory.rglob("*"):
            if self.is_old_month_file(item, current_year, current_month):
                try:
                    item.unlink()
                    deleted.append(item)
                    LOGGER.info("  [Cleanup] Đã xóa file cũ: %s", item.relative_to(self.root))
                except Exception as exc:
                    LOGGER.warning("  [Cleanup] Không thể xóa file %s: %s", item, exc)

        return deleted

    def should_run(self, now: datetime | None = None, force: bool = False) -> bool:
        """Xác định xem có cần thực hiện dọn dẹp tháng cũ hay không.

        Quy tắc:
        - Nếu force=True: Luôn chạy.
        - Nếu tháng hiện tại đã được dọn dẹp: Bỏ qua (không chạy lại trong cùng tháng).
        - Nếu hôm nay là mùng 1 (now.day == 1): Chạy lần đầu của mùng 1.
        - Nếu lần đầu chạy trong tháng mới (do mùng 1 máy tính chưa bật): Tự động bù dọn dẹp.
        """
        target_now = now or datetime.now(self.timezone)
        current_month_str = f"{target_now.year:04d}-{target_now.month:02d}"

        if force:
            return True

        state = self.get_state()
        last_cleaned = state.get("last_cleanup_month")

        # Đã dọn dẹp trong tháng này rồi -> không dọn lại
        if last_cleaned == current_month_str:
            return False

        # Lần đầu chạy của mùng 1 hàng tháng
        if target_now.day == 1:
            return True

        # Nếu mùng 1 chưa chạy (ví dụ tắt máy hoặc cài mới vào đầu tháng)
        if last_cleaned is None or last_cleaned < current_month_str:
            return True

        return False

    def clean(self, now: datetime | None = None) -> dict[str, list[Path]]:
        """Thực hiện xóa toàn bộ ghi chép tháng cũ trong docs và logs."""
        target_now = now or datetime.now(self.timezone)
        cur_y, cur_m = target_now.year, target_now.month
        current_month_str = f"{cur_y:04d}-{cur_m:02d}"

        # 1. Đảm bảo rollover runtime để lưu bản ghi ngày trước nếu có
        try:
            from app.accounts.runtime import AccountRuntime
            runtime = AccountRuntime(self.root, archive_dir=self.docs_dir)
            runtime.maybe_rollover(target_now)
        except Exception as exc:
            LOGGER.warning("[Cleanup] Rollover runtime trước dọn dẹp gặp cảnh báo: %s", exc)

        LOGGER.info(
            "[Cleanup] Đang quét và dọn dẹp ghi chép các tháng trước %s...",
            current_month_str,
        )

        deleted_docs = self.clean_directory(self.docs_dir, cur_y, cur_m)
        deleted_logs = self.clean_directory(self.logs_dir, cur_y, cur_m)

        total = len(deleted_docs) + len(deleted_logs)
        LOGGER.info(
            "[Cleanup] Hoàn tất dọn dẹp: Đã xóa %d file trong docs, %d file trong logs (tổng cộng: %d).",
            len(deleted_docs),
            len(deleted_logs),
            total,
        )

        self.save_state({
            "last_cleanup_month": current_month_str,
            "last_cleanup_at": target_now.isoformat(timespec="seconds"),
            "deleted_docs_count": len(deleted_docs),
            "deleted_logs_count": len(deleted_logs),
        })

        return {"docs": deleted_docs, "logs": deleted_logs}

    def maybe_run(
        self, now: datetime | None = None, force: bool = False
    ) -> dict[str, list[Path]] | None:
        """Kiểm tra điều kiện và thực thi dọn dẹp nếu đủ điều kiện."""
        target_now = now or datetime.now(self.timezone)
        if not self.should_run(target_now, force=force):
            return None

        LOGGER.info(
            "=== [Monthly Cleanup] Kích hoạt dọn dẹp định kỳ hàng tháng (tháng %02d/%04d) ===",
            target_now.month,
            target_now.year,
        )
        return self.clean(target_now)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DC3Q Monthly Cleanup - Dọn dẹp ghi chép docs & logs của tháng cũ"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bắt buộc dọn dẹp ngay mà không cần đợi mùng 1",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    cleaner = MonthlyCleanup()
    res = cleaner.maybe_run(force=args.force)
    if res is None:
        LOGGER.info("Chưa đến hạn dọn dẹp tháng mới (hoặc tháng này đã được dọn dẹp).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
