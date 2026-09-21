from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

LOGGER = logging.getLogger(__name__)

ActionExecutor = Callable[[Any, list[Any]], bool]
ConditionChecker = Callable[[Any, list[Any], str], bool]


@dataclass(slots=True)
class RecoveryRule:
    name: str
    conditions: list[Any] = field(default_factory=list)
    actions: list[Any] = field(default_factory=list)
    mode: str = "all"
    priority: int = 0
    cooldown: float = 0.0
    max_attempts: int = 3


@dataclass(slots=True)
class RecoveryResult:
    recovered: bool
    rule: str | None = None
    message: str = ""


class RecoveryManager:
    """Runs prioritized recovery rules for popups, network errors and stuck states."""

    def __init__(
        self,
        rules: list[RecoveryRule] | None = None,
        *,
        action_executor: ActionExecutor,
        condition_checker: ConditionChecker,
    ) -> None:
        self.rules = sorted(rules or [], key=lambda item: item.priority, reverse=True)
        self.action_executor = action_executor
        self.condition_checker = condition_checker
        self._attempts: dict[str, int] = {}
        self._last_run: dict[str, float] = {}

    @classmethod
    def from_config(
        cls,
        config: list[Mapping[str, Any]] | Mapping[str, Any] | None,
        *,
        action_executor: ActionExecutor,
        condition_checker: ConditionChecker,
    ) -> "RecoveryManager":
        if config is None:
            raw_rules: list[Mapping[str, Any]] = []
        elif isinstance(config, Mapping):
            raw_rules = list(config.get("rules", []) or [])
        else:
            raw_rules = list(config)

        rules: list[RecoveryRule] = []
        for index, raw_rule in enumerate(raw_rules):
            raw = dict(raw_rule)
            conditions = raw.get("conditions", raw.get("when", []))
            if conditions and not isinstance(conditions, list):
                conditions = [conditions]
            rules.append(
                RecoveryRule(
                    name=str(raw.get("name", f"recovery_{index + 1}")),
                    conditions=list(conditions or []),
                    actions=list(raw.get("actions", []) or []),
                    mode=str(raw.get("mode", "all")).lower(),
                    priority=int(raw.get("priority", 0)),
                    cooldown=max(0.0, float(raw.get("cooldown", 0.0))),
                    max_attempts=max(1, int(raw.get("max_attempts", 3))),
                )
            )

        return cls(rules, action_executor=action_executor, condition_checker=condition_checker)

    def reset(self, rule_name: str | None = None) -> None:
        if rule_name is None:
            self._attempts.clear()
            self._last_run.clear()
            return
        self._attempts.pop(rule_name, None)
        self._last_run.pop(rule_name, None)

    def try_recover(self, context: Any, *, reason: Exception | str | None = None) -> RecoveryResult:
        now = time.monotonic()
        if reason is not None:
            context.variables["last_error"] = str(reason)

        for rule in self.rules:
            attempts = self._attempts.get(rule.name, 0)
            if attempts >= rule.max_attempts:
                continue

            last_run = self._last_run.get(rule.name, 0.0)
            if rule.cooldown > 0 and now - last_run < rule.cooldown:
                continue

            try:
                matched = not rule.conditions or self.condition_checker(context, rule.conditions, rule.mode)
            except Exception as exc:
                LOGGER.warning("Recovery condition failed for %s: %s", rule.name, exc)
                continue

            if not matched:
                continue

            self._attempts[rule.name] = attempts + 1
            self._last_run[rule.name] = now
            try:
                success = self.action_executor(context, rule.actions)
            except Exception as exc:
                LOGGER.exception("Recovery rule %s raised an error", rule.name)
                return RecoveryResult(False, rule.name, str(exc))

            if success:
                LOGGER.info("Recovery rule succeeded: %s", rule.name)
                return RecoveryResult(True, rule.name, "Recovery actions completed")
            return RecoveryResult(False, rule.name, "Recovery actions failed")

        return RecoveryResult(False, None, "No recovery rule matched")
