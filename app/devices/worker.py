from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from app.accounts import Account, AccountManager
from app.automation import AutomationEngine, AutomationRunResult
from app.core.config import settings
from app.core.game_day import GameDayClock, GameDayRollover
from app.core.logger import get_logger
from app.vision import TemplateMatcher, VisionEngine, YOLODetector

logger = get_logger(__name__)


class WorkerState(str, Enum):
    CREATED = "CREATED"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING_ACCOUNT = "WAITING_ACCOUNT"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class WorkerSnapshot:
    serial: str
    state: WorkerState
    alive: bool
    current_account: str | None
    completed_accounts: int
    failed_runs: int
    heartbeat_age: float
    last_error: str | None


VisionFactory = Callable[[Any], Any]
EngineFactory = Callable[[Any, Any], AutomationEngine]


class DeviceWorker:
    """Runs one automation pipeline for exactly one ADB device."""

    def __init__(
        self,
        device: Any,
        scenario: Mapping[str, Any] | str | Path,
        *,
        account_manager: AccountManager | None = None,
        vision_factory: VisionFactory | None = None,
        engine_factory: EngineFactory | None = None,
        stop_when_no_accounts: bool = True,
        name: str | None = None,
    ) -> None:
        self.device = device
        self.serial = str(device.serial)
        self.scenario = scenario
        self.account_manager = account_manager
        self.stop_when_no_accounts = bool(stop_when_no_accounts)
        self.name = name or f"worker-{self.serial}"

        self.vision = (vision_factory or self._default_vision_factory)(device)
        self.engine = (engine_factory or self._default_engine_factory)(device, self.vision)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = WorkerState.CREATED
        self._state_lock = threading.RLock()
        self._heartbeat = time.monotonic()
        self._current_account: Account | None = None
        self._completed_accounts = 0
        self._failed_runs = 0
        self._last_error: str | None = None
        self._last_result: AutomationRunResult | None = None
        self._game_clock = GameDayClock(settings.accounts.reset_hour)
        self._active_game_day = self._game_clock.key()
        self._rollover_event = threading.Event()
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        guard = getattr(self.device, "set_action_guard", None)
        if callable(guard):
            guard(self._assert_game_day)

    def _assert_game_day(self) -> None:
        if self._rollover_event.is_set() or self._game_clock.key() != self._active_game_day:
            raise GameDayRollover("Game day changed at 23:00")

    def _watch_game_day(self) -> None:
        while not self._watchdog_stop.wait(0.25):
            if self._game_clock.key() != self._active_game_day:
                self._rollover_event.set()
                self.engine.request_stop()
                return

    def _start_game_day_watchdog(self) -> None:
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watch_game_day,
            name=f"rollover-{self.serial}",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _stop_game_day_watchdog(self) -> None:
        self._watchdog_stop.set()
        thread = self._watchdog_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._watchdog_thread = None

    def _wait_for_rollover_after_failure(self) -> bool:
        """Fail closed for the current day but keep the 23:00 service alive."""
        self._set_state(WorkerState.WAITING_ACCOUNT)
        while not self._stop_event.wait(0.5):
            if self._rollover_event.is_set() or self._game_clock.key() != self._active_game_day:
                self._handle_rollover(None)
                self._last_error = None
                self._set_state(WorkerState.IDLE)
                return True
        return False

    def _handle_rollover(self, account: Account | None) -> None:
        logger.warning("[%s] Đến 23:00: dừng luồng hiện tại, chuẩn hóa HOME và đăng xuất", self.serial)
        guard = getattr(self.device, "set_action_guard", None)
        if callable(guard):
            guard(None)
        self._stop_game_day_watchdog()
        self.engine.reset_stop()
        context = self.engine.create_context(account=account, variables=self._scenario_variables(account))
        result = self.engine.actions.execute(context, {
            "action": "reset_day_logout",
            "package": "com.daichien.mobile",
            "activity": "com.qtz.game.main.Logo",
            "home_timeout": 180,
            "logout_timeout": 60,
        })
        if not result.success:
            raise RuntimeError(f"23:00 logout failed: {result.message}")
        if account is not None and self.account_manager is not None:
            self.account_manager.release(account, worker_id=self.serial)
            self._current_account = None
        if self.account_manager is not None:
            self.account_manager.rollover()
        self._active_game_day = self._game_clock.key()
        self._rollover_event.clear()
        self.engine.reset_stop()
        if callable(guard):
            guard(self._assert_game_day)
        self._start_game_day_watchdog()
        logger.info("[%s] Ngày game mới %s; queue bắt đầu lại từ acc_001", self.serial, self._active_game_day)

    @staticmethod
    def _default_vision_factory(device: Any) -> VisionEngine:
        scales = settings.vision.scales if settings.vision.multi_scale else (1.0,)
        matcher = TemplateMatcher(
            default_threshold=settings.vision.template_threshold,
            grayscale=settings.vision.grayscale,
            default_scales=scales,
        )

        yolo = None
        if settings.yolo.enabled and settings.yolo.model_path.is_file():
            yolo = YOLODetector(
                model_path=settings.yolo.model_path,
                confidence=settings.yolo.confidence,
                iou=settings.yolo.iou,
                device=settings.yolo.runtime_device,
                image_size=settings.yolo.image_size,
            )
        elif settings.yolo.enabled:
            logger.warning(
                "[%s] Không tìm thấy YOLO model: %s. Worker vẫn chạy Template Matching.",
                getattr(device, "serial", "unknown"),
                settings.yolo.model_path,
            )

        return VisionEngine(
            device,
            template_matcher=matcher,
            yolo_detector=yolo,
            template_dir=settings.vision.templates_dir,
            frame_cache_seconds=0.0,
        )

    @staticmethod
    def _default_engine_factory(device: Any, vision: Any) -> AutomationEngine:
        return AutomationEngine(
            device,
            vision,
            poll_interval=settings.automation.loop_interval,
        )

    @property
    def state(self) -> WorkerState:
        with self._state_lock:
            return self._state

    @property
    def alive(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    @property
    def last_result(self) -> AutomationRunResult | None:
        return self._last_result

    def _set_state(self, state: WorkerState) -> None:
        with self._state_lock:
            self._state = state
            self._heartbeat = time.monotonic()

    def _touch(self) -> None:
        with self._state_lock:
            self._heartbeat = time.monotonic()

    def start(self) -> None:
        if self.alive:
            return
        if self.state not in {WorkerState.CREATED, WorkerState.STOPPED, WorkerState.ERROR}:
            raise RuntimeError(f"Cannot start worker {self.serial} from state={self.state}")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._set_state(WorkerState.STOPPING)
        self.engine.request_stop()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _wait_for_device(self) -> bool:
        try:
            if self.device.is_online():
                return True
        except Exception:
            pass

        attempts = max(1, settings.adb.reconnect_attempts)
        for attempt in range(attempts):
            if self._stop_event.is_set():
                return False
            try:
                if self.device.wait_until_online(timeout=max(1.0, settings.adb.reconnect_delay)):
                    return True
            except Exception as exc:
                self._last_error = str(exc)
            if attempt + 1 < attempts:
                if self._stop_event.wait(settings.adb.reconnect_delay):
                    return False
        return False

    def _claim_account(self) -> Account | None:
        if self.account_manager is None:
            return None
        return self.account_manager.claim_next(self.serial)

    def _scenario_variables(self, account: Account | None) -> dict[str, Any]:
        variables: dict[str, Any] = {
            "device": {"serial": self.serial},
            "worker": {"id": self.serial},
        }
        if account is not None:
            variables["account"] = account.to_variables()
        return variables

    def run_once(self, account: Account | None = None) -> AutomationRunResult:
        self._set_state(WorkerState.RUNNING)
        self._current_account = account
        self._touch()
        result = self.engine.run(
            self.scenario,
            account=account,
            variables=self._scenario_variables(account),
        )
        self._last_result = result
        self._touch()
        return result

    def run(self) -> None:
        logger.info("[%s] Worker started", self.serial)
        self._set_state(WorkerState.IDLE)
        self._start_game_day_watchdog()
        try:
            if not self._wait_for_device():
                raise RuntimeError(f"Device {self.serial} is not online")

            # No account source means run the scenario once for this device.
            if self.account_manager is None:
                if not self._stop_event.is_set():
                    result = self.run_once(None)
                    if result.success:
                        self._completed_accounts += 1
                    else:
                        self._failed_runs += 1
                        self._last_error = result.error
                return

            while not self._stop_event.is_set():
                account = self._claim_account()
                if account is None:
                    self._set_state(WorkerState.WAITING_ACCOUNT)
                    if self.stop_when_no_accounts:
                        # Thuế có 3 khung/ngày. Sau khi toàn bộ account đã xong
                        # khung hiện tại, giữ worker sống tới khung kế tiếp để
                        # AccountManager requeue lại đúng các account chưa claim slot.
                        wait_for_tax = None
                        seconds_fn = getattr(self.account_manager, "seconds_until_next_tax_window", None)
                        if callable(seconds_fn):
                            wait_for_tax = seconds_fn()
                        if wait_for_tax is None:
                            break
                        if self._stop_event.wait(min(1.0, max(0.1, settings.automation.loop_interval))):
                            break
                        continue
                    if self._game_clock.key() != self._active_game_day:
                        self._handle_rollover(None)
                        self._set_state(WorkerState.IDLE)
                        continue
                    if self._stop_event.wait(min(1.0, max(0.1, settings.automation.loop_interval))):
                        break
                    continue

                self._current_account = account
                try:
                    if not self._wait_for_device():
                        raise RuntimeError(f"Device {self.serial} disconnected")

                    result = self.run_once(account)
                    if self._rollover_event.is_set() or self._game_clock.key() != self._active_game_day:
                        self._handle_rollover(account)
                        continue
                    if result.success:
                        self.account_manager.mark_done(account, worker_id=self.serial)
                        self._completed_accounts += 1
                        if result.error:
                            # Account vẫn hoàn tất; error chỉ là chức năng con đã lỗi
                            # nhưng được cấu hình continue_on_error.
                            logger.warning(
                                "[%s] account-%s hoàn tất với chức năng lỗi có thể phục hồi: %s",
                                self.serial,
                                account.id,
                                result.error,
                            )
                        else:
                            logger.info(
                                "[%s] Hoàn thành account-%s elapsed=%.2fs",
                                self.serial,
                                account.id,
                                result.elapsed,
                            )
                    else:
                        if self._stop_event.is_set():
                            # Dừng thủ công không được tính là lỗi của account.
                            self.account_manager.release(account, worker_id=self.serial)
                            break

                        # Không để session/popup của account lỗi làm bẩn account kế tiếp.
                        # Chỉ chuyển sang account mới sau khi đã cố gắng chuẩn hóa HOME và
                        # đăng xuất; nếu không chuẩn hóa được thì account kế tiếp vẫn được
                        # phép chạy, nhưng lỗi hiện tại phải được ghi FAILED rõ ràng.
                        try:
                            cleanup_context = self.engine.create_context(
                                account=account,
                                variables=self._scenario_variables(account),
                            )
                            home_result = self.engine.execute_action(cleanup_context, {
                                "action": "recover_to_home",
                                "timeout": 90,
                                "interval": 0.8,
                            })
                            if home_result.success:
                                self.engine.execute_action(cleanup_context, {
                                    "action": "logout_account",
                                    "timeout": 60,
                                    "interval": 0.8,
                                    "threshold": 0.75,
                                })
                        except Exception:
                            logger.exception(
                                "[%s] Cleanup sau account-%s thất bại; vẫn ghi FAILED và tiếp tục queue",
                                self.serial, account.id,
                            )

                        self._failed_runs += 1
                        self._last_error = result.error
                        self.account_manager.mark_failed(
                            account,
                            result.error or "Automation failed",
                            worker_id=self.serial,
                        )
                        logger.error(
                            "[%s] account-%s không thể recovery: %s. Bỏ qua account này và tiếp tục account kế tiếp.",
                            self.serial,
                            account.id,
                            result.error or "unknown error",
                        )
                        # Chỉ account hiện tại bị FAILED. Worker vẫn phải lấy account
                        # kế tiếp; không được dừng cả batch vì một account lỗi.
                        continue
                except GameDayRollover:
                    self._handle_rollover(account)
                    continue
                except Exception as exc:
                    self._failed_runs += 1
                    self._last_error = str(exc)
                    logger.exception(
                        "[%s] Worker run failed for account id=%s; bỏ qua account và tiếp tục",
                        self.serial,
                        account.id,
                    )
                    self.account_manager.mark_failed(account, exc, worker_id=self.serial)
                    # Lỗi runtime của một account không được làm chết worker/batch.
                    continue
                finally:
                    self._current_account = None
                    self._touch()
                    if not self._stop_event.is_set():
                        self._set_state(WorkerState.IDLE)

        except Exception as exc:
            self._last_error = str(exc)
            self._set_state(WorkerState.ERROR)
            logger.exception("[%s] Worker fatal error", self.serial)
            return
        finally:
            self._stop_game_day_watchdog()
            # Return a leased account if shutdown interrupted it before status update.
            account = self._current_account
            if account is not None and self.account_manager is not None:
                try:
                    self.account_manager.release(account, worker_id=self.serial)
                except Exception:
                    logger.exception("[%s] Không thể trả account lease", self.serial)
                self._current_account = None

            if self.state != WorkerState.ERROR:
                self._set_state(WorkerState.STOPPED)
            logger.info("[%s] Worker stopped", self.serial)

    def snapshot(self) -> WorkerSnapshot:
        with self._state_lock:
            account = self._current_account
            return WorkerSnapshot(
                serial=self.serial,
                state=self._state,
                alive=self.alive,
                current_account=account.id if account else None,
                completed_accounts=self._completed_accounts,
                failed_runs=self._failed_runs,
                heartbeat_age=max(0.0, time.monotonic() - self._heartbeat),
                last_error=self._last_error,
            )
