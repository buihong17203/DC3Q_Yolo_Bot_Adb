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
                LOGGER.exception("Automation action failed on attempt %d/%d", attempt + 1, retry + 1)

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
                return False

        if continue_on_error:
            LOGGER.warning("Continuing after failed step: %s", last_error)
            return True
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
            child = self.load_scenario(scenario_path)
            if self.run_steps(context, list(child.get("steps", []) or [])):
                return True
            detail = (
                context.last_action.message
                if context.last_action is not None
                else "unknown child step"
            )
            LOGGER.error("Child scenario failed: %s | %s", scenario_path.name, detail)
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
        self.reset_stop()
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

            return AutomationRunResult(
                True,
                name,
                time.monotonic() - started,
                completed,
                final_state=context.state,
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
