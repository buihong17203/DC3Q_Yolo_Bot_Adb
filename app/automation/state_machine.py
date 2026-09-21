from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


ActionExecutor = Callable[[Any, list[Any]], bool]
ConditionChecker = Callable[[Any, list[Any], str], bool]


@dataclass(slots=True)
class Transition:
    target: str
    conditions: list[Any] = field(default_factory=list)
    actions: list[Any] = field(default_factory=list)
    mode: str = "all"
    priority: int = 0


@dataclass(slots=True)
class StateDefinition:
    name: str
    on_enter: list[Any] = field(default_factory=list)
    on_tick: list[Any] = field(default_factory=list)
    on_exit: list[Any] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    timeout: float | None = None
    timeout_target: str | None = None
    on_timeout: list[Any] = field(default_factory=list)
    terminal: bool = False


@dataclass(slots=True)
class StateMachineResult:
    success: bool
    final_state: str
    transitions: int
    elapsed: float
    message: str = ""


class StateMachine:
    """Config-driven state machine for LOGIN/HOME/TASK/LOGOUT or custom states."""

    def __init__(
        self,
        states: Mapping[str, StateDefinition],
        initial_state: str,
        *,
        action_executor: ActionExecutor,
        condition_checker: ConditionChecker,
        poll_interval: float = 0.25,
    ) -> None:
        self.states = dict(states)
        if initial_state not in self.states:
            raise KeyError(f"Initial state does not exist: {initial_state}")
        self.initial_state = initial_state
        self.action_executor = action_executor
        self.condition_checker = condition_checker
        self.poll_interval = max(0.01, float(poll_interval))

        self.current_state = initial_state
        self.started_at = 0.0
        self.entered_at = 0.0
        self.transition_count = 0
        self._started = False

    @classmethod
    def from_dict(
        cls,
        config: Mapping[str, Any],
        *,
        action_executor: ActionExecutor,
        condition_checker: ConditionChecker,
        poll_interval: float = 0.25,
    ) -> "StateMachine":
        initial = str(config.get("initial", config.get("initial_state", ""))).strip()
        raw_states = config.get("states")
        if not isinstance(raw_states, Mapping) or not raw_states:
            raise ValueError("state_machine.states must be a non-empty mapping")
        if not initial:
            initial = str(next(iter(raw_states)))

        states: dict[str, StateDefinition] = {}
        for name, raw_definition in raw_states.items():
            raw = dict(raw_definition or {})
            transitions: list[Transition] = []
            for raw_transition in raw.get("transitions", []) or []:
                tr = dict(raw_transition)
                target = str(tr.get("target", tr.get("to", ""))).strip()
                if not target:
                    raise ValueError(f"State {name!r} has transition without target")
                conditions = tr.get("conditions", tr.get("when", []))
                if conditions and not isinstance(conditions, list):
                    conditions = [conditions]
                transitions.append(
                    Transition(
                        target=target,
                        conditions=list(conditions or []),
                        actions=list(tr.get("actions", []) or []),
                        mode=str(tr.get("mode", "all")).lower(),
                        priority=int(tr.get("priority", 0)),
                    )
                )
            transitions.sort(key=lambda item: item.priority, reverse=True)

            timeout = raw.get("timeout")
            states[str(name)] = StateDefinition(
                name=str(name),
                on_enter=list(raw.get("on_enter", []) or []),
                on_tick=list(raw.get("on_tick", []) or []),
                on_exit=list(raw.get("on_exit", []) or []),
                transitions=transitions,
                timeout=float(timeout) if timeout is not None else None,
                timeout_target=raw.get("timeout_target"),
                on_timeout=list(raw.get("on_timeout", []) or []),
                terminal=bool(raw.get("terminal", False)),
            )

        for state in states.values():
            if state.timeout_target and state.timeout_target not in states:
                raise KeyError(f"State {state.name!r} timeout_target does not exist: {state.timeout_target}")
            for transition in state.transitions:
                if transition.target not in states:
                    raise KeyError(f"State {state.name!r} transition target does not exist: {transition.target}")

        return cls(
            states,
            initial,
            action_executor=action_executor,
            condition_checker=condition_checker,
            poll_interval=poll_interval,
        )

    def start(self, context: Any) -> None:
        self.current_state = self.initial_state
        self.started_at = time.monotonic()
        self.entered_at = self.started_at
        self.transition_count = 0
        self._started = True
        context.state = self.current_state
        self.action_executor(context, self.states[self.current_state].on_enter)

    def _transition(self, context: Any, target: str, actions: list[Any] | None = None) -> None:
        current = self.states[self.current_state]
        if not self.action_executor(context, current.on_exit):
            raise RuntimeError(f"on_exit failed for state {current.name}")
        if actions and not self.action_executor(context, actions):
            raise RuntimeError(f"transition actions failed: {self.current_state} -> {target}")

        self.current_state = target
        context.state = target
        self.entered_at = time.monotonic()
        self.transition_count += 1

        if not self.action_executor(context, self.states[target].on_enter):
            raise RuntimeError(f"on_enter failed for state {target}")

    def tick(self, context: Any) -> bool:
        if not self._started:
            self.start(context)

        state = self.states[self.current_state]
        if state.terminal:
            return True

        now = time.monotonic()
        if state.timeout is not None and now - self.entered_at >= state.timeout:
            if state.on_timeout and not self.action_executor(context, state.on_timeout):
                raise RuntimeError(f"on_timeout failed for state {state.name}")
            if state.timeout_target:
                self._transition(context, state.timeout_target)
                return self.states[self.current_state].terminal
            raise TimeoutError(f"State timed out: {state.name} after {state.timeout:.2f}s")

        if state.on_tick and not self.action_executor(context, state.on_tick):
            raise RuntimeError(f"on_tick failed for state {state.name}")

        for transition in state.transitions:
            if not transition.conditions:
                matched = True
            else:
                matched = self.condition_checker(context, transition.conditions, transition.mode)
            if matched:
                self._transition(context, transition.target, transition.actions)
                return self.states[self.current_state].terminal

        return False

    def run(
        self,
        context: Any,
        *,
        max_duration: float | None = None,
        stop_predicate: Callable[[], bool] | None = None,
    ) -> StateMachineResult:
        if not self._started:
            self.start(context)
        started = time.monotonic()

        while True:
            if stop_predicate and stop_predicate():
                return StateMachineResult(
                    False,
                    self.current_state,
                    self.transition_count,
                    time.monotonic() - started,
                    "Stopped by request",
                )

            if max_duration is not None and time.monotonic() - started >= max_duration:
                return StateMachineResult(
                    False,
                    self.current_state,
                    self.transition_count,
                    time.monotonic() - started,
                    f"State machine exceeded max_duration={max_duration}",
                )

            if self.tick(context):
                return StateMachineResult(
                    True,
                    self.current_state,
                    self.transition_count,
                    time.monotonic() - started,
                    "Terminal state reached",
                )

            time.sleep(self.poll_interval)
