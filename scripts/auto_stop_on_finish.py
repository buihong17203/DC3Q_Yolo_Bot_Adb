"""Monitor bot progress and automatically stop the process once all accounts are finished.
"""

from __future__ import annotations
import csv
import os
import signal
import sys
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "accounts" / "account_runtime.csv"


def get_pending_accounts() -> tuple[int, int, int]:
    """Trả về (số acc còn lại [READY + LOGGED_IN], số acc DONE, số acc ERROR)."""
    if not CSV_PATH.exists():
        return 0, 0, 0
    ready = 0
    logged_in = 0
    done = 0
    error = 0
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                st = (row.get("status") or "").strip().upper()
                if st == "READY":
                    ready += 1
                elif st == "LOGGED_IN":
                    logged_in += 1
                elif st == "DONE":
                    done += 1
                elif st == "ERROR":
                    error += 1
    except Exception as e:
        print(f"[!] Lỗi đọc CSV: {e}")
        return 999, 0, 0
    return (ready + logged_in), done, error


def find_bot_pids() -> list[int]:
    """Tìm PID các tiến trình đang chạy app.main."""
    pids = []
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "app.main" in cmdline and proc.pid != os.getpid():
                pids.append(proc.pid)
    except Exception:
        import subprocess
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*app.main*' } | Select-Object -ExpandProperty ProcessId"],
                text=True,
            )
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit() and int(line) != os.getpid():
                    pids.append(int(line))
        except Exception:
            pass
    return pids


def main():
    print("[*] Bắt đầu theo dõi tiến độ chạy tài khoản DC3Q Bot...", flush=True)
    last_pending = -1

    while True:
        pending, done, error = get_pending_accounts()
        if pending != last_pending:
            print(f"[{time.strftime('%H:%M:%S')}] Tiến độ: Còn {pending} acc chưa hoàn tất | Đã xong: {done} | Lỗi: {error}", flush=True)
            last_pending = pending

        bot_pids = find_bot_pids()
        if not bot_pids:
            print("[INFO] Không thấy tiến trình bot nào đang chạy. Tự động kết thúc trình theo dõi.", flush=True)
            break

        if pending == 0:
            print(f"[!] TẤT CẢ TÀI KHOẢN ĐÃ CHẠY XONG! Đang tiến hành dừng chương trình (PIDs: {bot_pids})...", flush=True)
            for pid in bot_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    print(f"[OK] Đã gửi tín hiệu dừng tới PID {pid}", flush=True)
                except Exception as ex:
                    print(f"[!] Không thể dừng PID {pid}: {ex}", flush=True)
            print("[OK] Đã dừng toàn bộ bot theo đúng yêu cầu!", flush=True)
            break

        time.sleep(15)


if __name__ == "__main__":
    main()
