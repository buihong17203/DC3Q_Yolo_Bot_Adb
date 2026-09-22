from __future__ import annotations

import inspect
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)


class ShutdownManager:
    """Điều phối dừng toàn bộ ứng dụng theo một stop_event dùng chung.

    Mục tiêu của lớp này:
    - Ctrl+C lần 1: yêu cầu dừng sạch toàn bộ worker/engine.
    - Nếu cleanup bị treo: có watchdog buộc process thoát sau timeout.
    - Ctrl+C lần 2: thoát ngay lập tức.
    - Với lệnh batch ``--run``: nếu toàn bộ worker đã kết thúc nhưng main process
      vẫn bị giữ bởi thread/phần cleanup khác, process sẽ tự đóng sau một khoảng
      grace ngắn để PowerShell trả lại ``PS ...>``.

    API được giữ tương thích với bản ShutdownManager cũ:
    ``stop_event``, ``is_stopping``, ``register()``, ``request_shutdown()`` và
    ``install_signal_handlers()``.
    """

    def __init__(
        self,
        *,
        force_exit_timeout: float | None = None,
        batch_exit_grace: float | None = None,
    ) -> None:
        self.stop_event = threading.Event()
        self._callbacks: list[Callable[..., Any]] = []
        self._lock = threading.RLock()
        self._shutting_down = False
        self._signal_count = 0
        self._forced_watchdog_started = False
        self._batch_watchdog_started = False
        self._installed = False
        self._previous_handlers: dict[int, Any] = {}
        self._requested_exit_code = 0

        self.force_exit_timeout = self._env_float(
            "DC3Q_FORCE_EXIT_TIMEOUT",
            force_exit_timeout if force_exit_timeout is not None else 8.0,
            minimum=1.0,
        )

        self.batch_exit_grace = self._env_float(
            "DC3Q_BATCH_EXIT_GRACE",
            batch_exit_grace if batch_exit_grace is not None else 5.0,
            minimum=0.5,
        )

    @staticmethod
    def _env_float(
        name: str,
        default: float,
        *,
        minimum: float,
    ) -> float:
        # Đọc giá trị timeout từ biến môi trường nếu có.
        raw = os.getenv(name)

        if raw is None:
            return max(minimum, float(default))

        try:
            return max(minimum, float(raw))
        except (TypeError, ValueError):
            return max(minimum, float(default))

    @property
    def is_stopping(self) -> bool:
        # Kiểm tra xem hệ thống đang trong quá trình shutdown hay chưa.
        return self.stop_event.is_set() or self._shutting_down

    @property
    def stopped(self) -> bool:
        # Alias để code cũ/ngoài dự án có thể kiểm tra theo tên quen thuộc.
        return self.is_stopping

    def register(
        self,
        callback: Callable[..., Any],
    ) -> Callable[..., Any]:
        """Đăng ký callback cleanup.

        Callback được gọi theo thứ tự ngược khi shutdown.
        """
        if not callable(callback):
            raise TypeError("shutdown callback must be callable")

        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

        return callback

    def unregister(
        self,
        callback: Callable[..., Any],
    ) -> None:
        # Hủy đăng ký một callback cleanup.
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

    def wait(
        self,
        timeout: float | None = None,
    ) -> bool:
        # Chờ cho đến khi shutdown được yêu cầu hoặc timeout.
        return self.stop_event.wait(timeout)

    def _invoke_callback(
        self,
        callback: Callable[..., Any],
    ) -> None:
        """Gọi callback tương thích cả dạng callback() và callback(stop_event)."""

        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            callback()
            return

        required_positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (
                parameter.POSITIONAL_ONLY,
                parameter.POSITIONAL_OR_KEYWORD,
            )
            and parameter.default is inspect.Parameter.empty
        ]

        if required_positional:
            callback(self.stop_event)
        else:
            callback()

    def _start_forced_exit_watchdog(
        self,
        exit_code: int,
    ) -> None:
        # Chỉ tạo watchdog một lần.
        with self._lock:
            if self._forced_watchdog_started:
                return

            self._forced_watchdog_started = True

        timeout = self.force_exit_timeout

        def watchdog() -> None:
            # Đợi tối đa timeout trước khi buộc process thoát.
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                time.sleep(
                    min(
                        0.10,
                        max(
                            0.01,
                            deadline - time.monotonic(),
                        ),
                    )
                )

            # Nếu process còn tồn tại sau timeout thì cleanup/join đang bị treo.
            try:
                logging.shutdown()
            finally:
                os._exit(int(exit_code))

        threading.Thread(
            target=watchdog,
            name="dc3q-force-exit-watchdog",
            daemon=True,
        ).start()

    @staticmethod
    def _worker_threads() -> list[threading.Thread]:
        # Tìm các thread worker của ứng dụng.
        workers: list[threading.Thread] = []

        current = threading.current_thread()

        for thread in threading.enumerate():
            if thread is current or not thread.is_alive():
                continue

            name = thread.name.lower()

            # Tên thực tế hiện tại của dự án:
            # worker-emulator-5554, device-worker, ...
            if (
                name.startswith("worker-")
                or name.startswith("device-worker")
                or "deviceworker" in name
            ):
                workers.append(thread)

        return workers

    def _start_batch_completion_watchdog(self) -> None:
        """Bảo đảm batch CLI trả prompt khi worker đã kết thúc."""

        if "--run" not in sys.argv:
            return

        with self._lock:
            if self._batch_watchdog_started:
                return

            self._batch_watchdog_started = True

        grace = self.batch_exit_grace

        def watchdog() -> None:
            # Đánh dấu đã từng phát hiện worker.
            seen_worker = False
            no_worker_since: float | None = None

            while True:
                workers = self._worker_threads()

                if workers:
                    seen_worker = True
                    no_worker_since = None

                elif seen_worker:
                    if no_worker_since is None:
                        no_worker_since = time.monotonic()

                    elif time.monotonic() - no_worker_since >= grace:
                        # Bình thường main.py sẽ tự kết thúc trước mốc này.
                        # Nếu vẫn còn sống, đây là trạng thái terminal
                        # bị giữ sau batch.
                        try:
                            LOGGER.warning(
                                "Batch workers đã dừng nhưng process vẫn còn "
                                "sống sau %.1fs; buộc kết thúc để trả "
                                "PowerShell prompt.",
                                grace,
                            )

                            logging.shutdown()

                        finally:
                            os._exit(
                                int(
                                    self._requested_exit_code
                                    or 0
                                )
                            )

                time.sleep(0.20)

        threading.Thread(
            target=watchdog,
            name="dc3q-batch-exit-watchdog",
            daemon=True,
        ).start()

    def request_shutdown(
        self,
        *args: Any,
        reason: str | None = None,
        exit_code: int | None = None,
        force_after: float | None = None,
        **kwargs: Any,
    ) -> bool:
        """Phát tín hiệu dừng và chạy toàn bộ callback cleanup đúng một lần.

        ``*args``/``**kwargs`` được chấp nhận để giữ tương thích nếu caller cũ
        truyền thêm lý do hoặc metadata.
        """

        del args, kwargs

        if exit_code is not None:
            self._requested_exit_code = int(exit_code)

        if force_after is not None:
            try:
                self.force_exit_timeout = max(
                    1.0,
                    float(force_after),
                )
            except (TypeError, ValueError):
                pass

        with self._lock:
            already_stopping = self._shutting_down

            self.stop_event.set()

            if already_stopping:
                return False

            self._shutting_down = True

            # Cleanup theo thứ tự ngược với thứ tự đăng ký.
            callbacks = list(
                reversed(self._callbacks)
            )

        if reason:
            LOGGER.info(
                "Yêu cầu dừng hệ thống: %s",
                reason,
            )

        # Khi shutdown đã bắt đầu, luôn có hard fallback
        # để không treo terminal.
        self._start_forced_exit_watchdog(
            self._requested_exit_code or 130
        )

        for callback in callbacks:
            try:
                self._invoke_callback(callback)

            except BaseException:
                # Không để một callback lỗi chặn các callback cleanup
                # còn lại.
                LOGGER.exception(
                    "Shutdown callback thất bại: %r",
                    callback,
                )

        return True

    # Các alias giữ tương thích cho caller cũ.
    shutdown = request_shutdown
    stop = request_shutdown

    def _handle_signal(
        self,
        signum: int,
        _frame: Any,
    ) -> None:
        # Tăng số lần nhận signal.
        self._signal_count += 1

        code = 128 + int(signum)

        self._requested_exit_code = code

        # Lần Ctrl+C/SIGTERM thứ hai:
        # không chờ cleanup nữa.
        if self._signal_count >= 2:
            try:
                logging.shutdown()
            finally:
                os._exit(code)

        signal_name = (
            "Ctrl+C"
            if signum == signal.SIGINT
            else f"signal {signum}"
        )

        LOGGER.warning(
            "Nhận %s - đang dừng toàn bộ hệ thống...",
            signal_name,
        )

        # Bật hard-timeout trước khi chạy callback
        # để callback bị treo vẫn thoát được.
        self._start_forced_exit_watchdog(code)

        self.request_shutdown(
            reason=signal_name,
            exit_code=code,
        )

        # Giữ hành vi KeyboardInterrupt của Python
        # để main.py hiện tại trả code 130.
        if signum == signal.SIGINT:
            raise KeyboardInterrupt

        raise SystemExit(code)

    def install_signal_handlers(self) -> None:
        """Đăng ký SIGINT/SIGTERM.

        Chỉ signal main thread mới được phép cài handler.
        """

        if self._installed:
            self._start_batch_completion_watchdog()
            return

        if threading.current_thread() is not threading.main_thread():
            LOGGER.warning(
                "Không thể cài signal handler ngoài main thread"
            )
            return

        with self._lock:
            if self._installed:
                return

            self._installed = True

        for sig in (
            signal.SIGINT,
            signal.SIGTERM,
        ):
            try:
                self._previous_handlers[sig] = signal.getsignal(
                    sig
                )

                signal.signal(
                    sig,
                    self._handle_signal,
                )

            except (
                AttributeError,
                OSError,
                RuntimeError,
                ValueError,
            ):
                # Một số platform không hỗ trợ đầy đủ
                # SIGTERM/signal API.
                LOGGER.debug(
                    "Không cài được signal handler %r",
                    sig,
                    exc_info=True,
                )

        self._start_batch_completion_watchdog()

    def restore_signal_handlers(self) -> None:
        # Khôi phục lại signal handler ban đầu.
        if threading.current_thread() is not threading.main_thread():
            return

        for sig, handler in list(
            self._previous_handlers.items()
        ):
            try:
                signal.signal(
                    sig,
                    handler,
                )

            except (
                OSError,
                RuntimeError,
                ValueError,
            ):
                pass

        self._previous_handlers.clear()
        self._installed = False

    def reset(self) -> None:
        """Chỉ dùng cho test hoặc lifecycle hoàn toàn mới."""

        with self._lock:
            self.stop_event.clear()
            self._shutting_down = False
            self._signal_count = 0
            self._forced_watchdog_started = False
            self._batch_watchdog_started = False
            self._requested_exit_code = 0


def terminate_child_processes() -> None:
    """Tương thích với code cũ đang import hàm này.

    Hàm này yêu cầu các module/process con của ứng dụng tự cleanup
    thông qua ShutdownManager thay vì kill chính process Python hiện tại.

    Việc terminate process con thực tế nên được đăng ký bằng:
        shutdown_manager.register(callback)

    để callback đó biết chính xác process nào mà nó đã tạo.
    """

    LOGGER.debug(
        "terminate_child_processes() được gọi - "
        "chờ các callback cleanup xử lý process con."
    )

    # Phát tín hiệu shutdown cho các callback đã đăng ký.
    shutdown_manager.request_shutdown(
        reason="terminate_child_processes"
    )


# Instance dùng chung cho toàn bộ ứng dụng.
shutdown_manager = ShutdownManager()