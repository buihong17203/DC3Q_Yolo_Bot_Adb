from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings
from app.core.game_day import GameDayRollover

from .actions import ActionRegistry, ActionResult, ActionStopRequested
from .conditions import ConditionRegistry, ConditionResult
from .recovery import RecoveryManager
from .state_machine import StateMachine, StateMachineResult

LOGGER = logging.getLogger(__name__)


class AutomationError(RuntimeError):
    pass


class StepExecutionError(AutomationError):
    pass


@dataclass(slots=True)
class AutomationContext:
    device: Any
    vision: Any
    account: Any = None
    variables: dict[str, Any] = field(default_factory=dict)
    current_scenario: str | None = None
    state: str | None = None
    step_index: int = -1
    last_action: ActionResult | None = None
    last_condition: ConditionResult | None = None
    stop_event: threading.Event | None = None


@dataclass(slots=True)
class AutomationRunResult:
    success: bool
    scenario: str
    elapsed: float
    steps_completed: int
    final_state: str | None = None
    error: str | None = None


class AutomationEngine:
    """Executes declarative scenarios using Device + VisionEngine abstractions."""

    def __init__(
        self,
        device: Any,
        vision: Any,
        *,
        actions: ActionRegistry | None = None,
        conditions: ConditionRegistry | None = None,
        poll_interval: float = 0.25,
    ) -> None:
        self.device = device
        self.vision = vision
        self.actions = actions or ActionRegistry()
        self.conditions = conditions or ConditionRegistry()
        self.poll_interval = max(0.01, float(poll_interval))
        self.recovery = RecoveryManager(
            [],
            action_executor=self.execute_actions,
            condition_checker=self.check_conditions,
        )
        self._stop_event = threading.Event()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self) -> None:
        self._stop_event.set()

    def reset_stop(self) -> None:
        self._stop_event.clear()

    def _wait_or_stopped(self, seconds: float) -> bool:
        """Wait interruptibly; return True when a stop was requested."""
        return self._stop_event.wait(max(0.0, float(seconds)))

    @staticmethod
    def load_scenario(path: str | Path) -> dict[str, Any]:
        scenario_path = Path(path).expanduser().resolve()
        if not scenario_path.is_file():
            raise FileNotFoundError(f"Scenario file not found: {scenario_path}")
        try:
            import yaml
        except ImportError as exc:
            raise AutomationError("PyYAML is required to load YAML scenarios") from exc

        with scenario_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise AutomationError(f"Scenario root must be a mapping: {scenario_path}")
        return data

    def create_context(
        self,
        *,
        account: Any = None,
        variables: Mapping[str, Any] | None = None,
        scenario_name: str | None = None,
    ) -> AutomationContext:
        merged = dict(variables or {})

        # Kịch bản có thể dùng ${account.username}, ${account.password}, ...
        # mà không cần mỗi caller tự chuyển Account thành dict.
        if account is not None and "account" not in merged:
            to_variables = getattr(account, "to_variables", None)
            if callable(to_variables):
                merged["account"] = to_variables()
            elif isinstance(account, Mapping):
                merged["account"] = dict(account)
            else:
                merged["account"] = {
                    key: getattr(account, key)
                    for key in ("id", "username", "password", "status")
                    if hasattr(account, key)
                }

        return AutomationContext(
            device=self.device,
            vision=self.vision,
            account=account,
            variables=merged,
            current_scenario=scenario_name,
            stop_event=self._stop_event,
        )

    def execute_action(self, context: AutomationContext, spec: Any) -> ActionResult:
        if self.stopped:
            return ActionResult(False, "stopped", "Stop requested")
        result = self.actions.execute(context, spec)
        context.last_action = result
        return result

    def execute_actions(self, context: AutomationContext, specs: list[Any]) -> bool:
        for spec in specs:
            if self.stopped:
                return False
            result = self.execute_action(context, spec)
            if not result.success:
                return False
        return True

    def check_condition(self, context: AutomationContext, spec: Any) -> ConditionResult:
        result = self.conditions.check(context, spec)
        context.last_condition = result
        return result

    def check_conditions(self, context: AutomationContext, specs: list[Any], mode: str = "all") -> bool:
        if not specs:
            return True
        mode = mode.lower()
        if mode == "all":
            return all(self.check_condition(context, spec).met for spec in specs)
        if mode == "any":
            return any(self.check_condition(context, spec).met for spec in specs)
        raise ValueError(f"Unsupported condition mode: {mode}")

    def wait_until(
        self,
        context: AutomationContext,
        condition: Any,
        *,
        timeout: float = 10.0,
        interval: float | None = None,
    ) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        sleep_interval = self.poll_interval if interval is None else max(0.01, float(interval))
        while not self.stopped:
            if self.check_condition(context, condition).met:
                return True
            if time.monotonic() >= deadline:
                return False
            if self._wait_or_stopped(sleep_interval):
                return False
        return False

    def configure_recovery(self, config: Any) -> None:
        self.recovery = RecoveryManager.from_config(
            config,
            action_executor=self.execute_actions,
            condition_checker=self.check_conditions,
        )

    def _recover(self, context: AutomationContext, reason: Exception | str) -> bool:
        if not self.recovery.rules:
            return False
        result = self.recovery.try_recover(context, reason=reason)
        return result.recovered

    def _is_critical_step(self, context: AutomationContext, action_name: str) -> bool:
        """Xác định bước không được phép nuốt lỗi, chủ yếu là đăng nhập."""
        action = action_name.casefold().strip()
        scenario = str(context.current_scenario or "").casefold()
        critical_actions = {
            "ensure_login_screen",
            "login_credentials",
            "prepare_account_session",
            "set_workflow_step",
            "tam_quoc_lenh",
            "phuc_loi",
            "cua_hang",
            "complete_account_flow",
        }
        if action in critical_actions:
            return True
        if "login" in scenario and action not in {"logout_account"}:
            return True
        return False

    def _recover_function_failure(
        self,
        context: AutomationContext,
        reason: Exception | str,
    ) -> bool:
        """Recovery sau lỗi function; chỉ thành công khi xác nhận HOME."""
        try:
            if self._recover(context, reason):
                home = self.execute_action(
                    context,
                    {
                        "action": "recover_to_home",
                        "timeout": 60,
                        "interval": 0.8,
                    },
                )
                if home.success:
                    return True
        except ActionStopRequested:
            return False
        except Exception:
            LOGGER.exception("Recovery rule failed after function error")

        try:
            result = self.execute_action(
                context,
                {
                    "action": "recover_to_home",
                    "timeout": 60,
                    "interval": 0.8,
                },
            )
            return bool(result.success)
        except ActionStopRequested:
            return False
        except Exception:
            LOGGER.exception("Direct HOME recovery failed after function error")
            return False

    def _run_action_step(self, context: AutomationContext, step: Mapping[str, Any]) -> bool:
        step_copy = dict(step)
        retry = max(0, int(step_copy.pop("retry", 0)))
        retry_delay = max(0.0, float(step_copy.pop("retry_delay", 0.5)))
        continue_on_error = bool(step_copy.pop("continue_on_error", False))
        delay_after = max(0.0, float(step_copy.pop("delay_after", 0.0)))
        when = step_copy.pop("when", None)
        unless = step_copy.pop("unless", None)

        if when is not None and not self.check_condition(context, when).met:
            return True
        if unless is not None and self.check_condition(context, unless).met:
            return True

        action_name = str(
            step_copy.get("action", step_copy.get("type", step_copy.get("name", "")))
        )
        critical = self._is_critical_step(context, action_name)

        last_error: Exception | str | None = None
        for attempt in range(retry + 1):
            if self.stopped:
                return False
            try:
                result = self.execute_action(context, step_copy)
                if result.success:
                    if delay_after and self._wait_or_stopped(delay_after):
                        return False
                    return True
                last_error = result.message or f"Action failed: {result.action}"
            except GameDayRollover:
                raise
            except ActionStopRequested:
                return False
            except Exception as exc:
                last_error = exc
                LOGGER.exception(
                    "Automation action failed on attempt %d/%d",
                    attempt + 1,
                    retry + 1,
                )

            if self._recover(context, last_error):
                try:
                    result = self.execute_action(context, step_copy)
                    if result.success:
                        if delay_after and self._wait_or_stopped(delay_after):
                            return False
                        return True
                except ActionStopRequested:
                    return False
                except Exception as exc:
                    last_error = exc

            if attempt < retry and self._wait_or_stopped(retry_delay):
                continue

        if continue_on_error:
            LOGGER.warning("Continuing after failed step: %s", last_error)
            return True

        if critical:
            LOGGER.error(
                "Critical function failed; account cannot continue safely: action=%s error=%s",
                action_name,
                last_error,
            )
            return False

        # Function không critical: ghi nhận lỗi, recovery về HOME rồi cho phép
        # scenario chạy tiếp function kế tiếp.
        failed = context.variables.setdefault("_failed_functions", [])
        if isinstance(failed, list):
            failed.append(
                {
                    "function": action_name or "unknown",
                    "error": str(last_error),
                }
            )

        recovered = self._recover_function_failure(context, last_error or "function failed")
        if recovered:
            LOGGER.warning(
                "Non-critical function failed but account recovered to HOME; continuing: %s",
                last_error,
            )
            return True

        LOGGER.error(
            "Non-critical function failed and HOME recovery was impossible: %s",
            last_error,
        )
        return False

    def _run_control_step(self, context: AutomationContext, step: Mapping[str, Any]) -> bool | None:
        if "wait_until" in step:
            raw = step["wait_until"]
            if isinstance(raw, Mapping):
                condition = raw.get("condition", raw.get("when"))
                timeout = float(raw.get("timeout", 10.0))
                interval = float(raw.get("interval", self.poll_interval))
            else:
                condition = raw
                timeout = float(step.get("timeout", 10.0))
                interval = float(step.get("interval", self.poll_interval))
            if condition is None:
                raise ValueError("wait_until requires a condition")
            return self.wait_until(context, condition, timeout=timeout, interval=interval)

        if "if" in step:
            condition = step["if"]
            branch = step.get("then", []) if self.check_condition(context, condition).met else step.get("else", [])
            return self.run_steps(context, list(branch or []))

        if "repeat" in step:
            raw = step["repeat"]
            if isinstance(raw, Mapping):
                times = max(0, int(raw.get("times", 1)))
                nested = list(raw.get("steps", []) or [])
            else:
                times = max(0, int(raw))
                nested = list(step.get("steps", []) or [])
            for _ in range(times):
                if self.stopped or not self.run_steps(context, nested):
                    return False
            return True

        if "while" in step:
            condition = step["while"]
            nested = list(step.get("steps", []) or [])
            max_iterations = max(1, int(step.get("max_iterations", 100)))
            for _ in range(max_iterations):
                if self.stopped:
                    return False
                if not self.check_condition(context, condition).met:
                    return True
                if not self.run_steps(context, nested):
                    return False
            return False

        if "run_scenario" in step:
            scenario_path = Path(str(step["run_scenario"])).expanduser()
            if not scenario_path.is_absolute():
                scenario_path = settings.automation.scripts_dir / scenario_path
            child_name = scenario_path.stem.casefold()

            # Login và toàn bộ nhiệm vụ bắt buộc của account đều phải fail-closed.
            # Không được nuốt lỗi Phúc lợi/Cửa hàng rồi đánh dấu account DONE.
            critical_child = any(token in child_name for token in (
                "login", "prepare", "ensure_login", "auth",
                "tam_quoc", "phuc_loi", "cua_hang", "multi_account_manager",
            ))
            continue_on_error = bool(step.get("continue_on_error", not critical_child))
            child = self.load_scenario(scenario_path)

            parent_scenario = context.current_scenario
            context.current_scenario = str(child.get("name", scenario_path.stem))
            try:
                child_ok = self.run_steps(context, list(child.get("steps", []) or []))
            finally:
                context.current_scenario = parent_scenario

            if child_ok:
                return True

            detail = (
                context.last_action.message
                if context.last_action is not None
                else "unknown child step"
            )
            LOGGER.error("Child scenario failed: %s | %s", scenario_path.name, detail)

            if not continue_on_error:
                return False

            failed = context.variables.setdefault("_failed_functions", [])
            if isinstance(failed, list):
                failed.append({
                    "function": scenario_path.stem,
                    "error": str(detail),
                })

            # Lỗi function chỉ ảnh hưởng function đó. Trước khi đi tiếp,
            # đưa session về HOME và xác minh HOME.
            recovered = self._recover_function_failure(context, detail)
            if recovered:
                return True

            context.variables["_recovery_failed"] = True
            LOGGER.error(
                "Child scenario %s failed and HOME recovery failed",
                scenario_path.name,
            )
            return False

        if "state_machine" in step:
            result = self.run_state_machine(context, step["state_machine"])
            return result.success

        return None

    def run_steps(self, context: AutomationContext, steps: list[Any]) -> bool:
        for index, raw_step in enumerate(steps):
            if self.stopped:
                return False
            context.step_index = index

            if isinstance(raw_step, str):
                raw_step = {"action": raw_step}
            if not isinstance(raw_step, Mapping):
                raise TypeError(f"Step must be a mapping or action string: {raw_step!r}")

            control_result = self._run_control_step(context, raw_step)
            if control_result is not None:
                if not control_result:
                    return False
                continue

            if not self._run_action_step(context, raw_step):
                return False
        return True

    def run_state_machine(
        self,
        context: AutomationContext,
        config: Mapping[str, Any],
    ) -> StateMachineResult:
        machine = StateMachine.from_dict(
            config,
            action_executor=self.execute_actions,
            condition_checker=self.check_conditions,
            poll_interval=float(config.get("poll_interval", self.poll_interval)),
        )
        max_duration = config.get("max_duration")
        return machine.run(
            context,
            max_duration=float(max_duration) if max_duration is not None else None,
            stop_predicate=lambda: self.stopped,
        )

    def run(
        self,
        scenario: Mapping[str, Any] | str | Path,
        *,
        account: Any = None,
        variables: Mapping[str, Any] | None = None,
    ) -> AutomationRunResult:
        # Không tự clear stop_event ở đầu mỗi scenario.
        # Nếu Ctrl+C/shutdown vừa được phát ra giữa hai account thì việc clear tại đây
        # sẽ làm mất tín hiệu dừng và worker có thể chạy tiếp account/scenario mới.
        data = self.load_scenario(scenario) if isinstance(scenario, (str, Path)) else deepcopy(dict(scenario))
        name = str(data.get("name", Path(scenario).stem if isinstance(scenario, (str, Path)) else "scenario"))

        merged_variables = dict(data.get("variables", {}) or {})
        if variables:
            merged_variables.update(variables)
        context = self.create_context(account=account, variables=merged_variables, scenario_name=name)
        self.configure_recovery(data.get("recovery"))

        started = time.monotonic()
        completed = 0
        try:
            steps = list(data.get("steps", []) or [])
            if steps:
                success = self.run_steps(context, steps)
                completed = context.step_index + 1 if context.step_index >= 0 else 0
                if not success:
                    if self.stopped:
                        return AutomationRunResult(
                            False, name, time.monotonic() - started, completed,
                            final_state=context.state, error="Stopped by request",
                        )
                    raise StepExecutionError("Scenario steps did not complete successfully")

            state_machine_config = data.get("state_machine")
            if state_machine_config:
                sm_result = self.run_state_machine(context, state_machine_config)
                if not sm_result.success:
                    if self.stopped:
                        return AutomationRunResult(
                            False, name, time.monotonic() - started, completed,
                            final_state=context.state, error="Stopped by request",
                        )
                    raise StepExecutionError(sm_result.message or "State machine failed")

            failed_functions = context.variables.get("_failed_functions", [])
            failed_text = "; ".join(
                f"{item.get('scenario', 'unknown')}: {item.get('error', '')}"
                for item in failed_functions
                if isinstance(item, Mapping)
            ) or None
            return AutomationRunResult(
                True,
                name,
                time.monotonic() - started,
                completed,
                final_state=context.state,
                error=failed_text,
            )
        except GameDayRollover:
            raise
        except Exception as exc:
            LOGGER.exception("Scenario failed: %s", name)
            self._recover(context, exc)
            return AutomationRunResult(
                False,
                name,
                time.monotonic() - started,
                completed,
                final_state=context.state,
                error=str(exc),
            )