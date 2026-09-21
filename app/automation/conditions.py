from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .actions import resolve_value


class ConditionContext(Protocol):
    device: Any
    vision: Any
    variables: dict[str, Any]


@dataclass(slots=True)
class ConditionResult:
    met: bool
    condition: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.met


ConditionHandler = Callable[[ConditionContext, dict[str, Any]], ConditionResult]


class ConditionRegistry:
    def __init__(self, register_defaults: bool = True) -> None:
        self._handlers: dict[str, ConditionHandler] = {}
        if register_defaults:
            self._register_defaults()

    def register(self, name: str, handler: ConditionHandler, *, replace: bool = False) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("Condition name cannot be empty")
        if key in self._handlers and not replace:
            raise KeyError(f"Condition already registered: {name}")
        self._handlers[key] = handler

    def has(self, name: str) -> bool:
        return name.strip().lower() in self._handlers

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def check(self, context: ConditionContext, spec: bool | str | Mapping[str, Any]) -> ConditionResult:
        if isinstance(spec, bool):
            return ConditionResult(spec, "literal")

        if isinstance(spec, str):
            name = spec
            params: dict[str, Any] = {}
        elif isinstance(spec, Mapping):
            raw = dict(spec)
            if "all" in raw:
                children = raw["all"]
                met = all(self.check(context, child).met for child in children)
                return ConditionResult(met, "all")
            if "any" in raw:
                children = raw["any"]
                met = any(self.check(context, child).met for child in children)
                return ConditionResult(met, "any")
            if "not" in raw:
                child = self.check(context, raw["not"])
                return ConditionResult(not child.met, "not", data={"inner": child})

            name = str(raw.pop("condition", raw.pop("type", raw.pop("name", "")))).strip()
            if not name:
                raise ValueError(f"Condition specification has no condition/type/name: {spec!r}")
            params = raw
        else:
            raise TypeError(f"Unsupported condition specification: {type(spec)!r}")

        key = name.lower()
        handler = self._handlers.get(key)
        if handler is None:
            raise KeyError(f"Unknown condition: {name}")

        params = resolve_value(params, context.variables)
        result = handler(context, params)
        if not isinstance(result, ConditionResult):
            raise TypeError(f"Condition handler {name} returned {type(result)!r}")
        return result

    def _register_defaults(self) -> None:
        defaults: dict[str, ConditionHandler] = {
            "always": self._always,
            "never": self._never,
            "template_exists": self._template_exists,
            "template_not_exists": self._template_not_exists,
            "yolo_exists": self._yolo_exists,
            "yolo_not_exists": self._yolo_not_exists,
            "variable_equals": self._variable_equals,
            "variable_not_equals": self._variable_not_equals,
            "variable_truthy": self._variable_truthy,
            "variable_falsy": self._variable_falsy,
            "variable_exists": self._variable_exists,
        }
        for name, handler in defaults.items():
            self.register(name, handler)

    @staticmethod
    def _always(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        return ConditionResult(True, "always")

    @staticmethod
    def _never(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        return ConditionResult(False, "never")

    @staticmethod
    def _template_exists(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        template = params.get("template", params.get("path"))
        if template is None:
            raise ValueError("template_exists requires 'template' or 'path'")
        match = context.vision.find_template(
            template,
            threshold=params.get("threshold"),
            roi=params.get("roi"),
            scales=params.get("scales"),
            refresh=True,
        )
        return ConditionResult(
            match is not None,
            "template_exists",
            data={"match": match, "template": str(template)},
        )

    @classmethod
    def _template_not_exists(cls, context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        result = cls._template_exists(context, params)
        return ConditionResult(not result.met, "template_not_exists", data=result.data)

    @staticmethod
    def _yolo_exists(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        class_name = params.get("class_name", params.get("class", params.get("target")))
        detection = context.vision.detect_one(
            class_name,
            confidence=params.get("confidence"),
            iou=params.get("iou"),
            roi=params.get("roi"),
            refresh=True,
        )
        return ConditionResult(
            detection is not None,
            "yolo_exists",
            data={"detection": detection, "class_name": class_name},
        )

    @classmethod
    def _yolo_not_exists(cls, context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        result = cls._yolo_exists(context, params)
        return ConditionResult(not result.met, "yolo_not_exists", data=result.data)

    @staticmethod
    def _variable_equals(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        key = str(params.get("key", ""))
        if not key:
            raise ValueError("variable_equals requires 'key'")
        expected = params.get("value")
        actual = context.variables.get(key)
        return ConditionResult(actual == expected, "variable_equals", data={"key": key, "actual": actual, "expected": expected})

    @staticmethod
    def _variable_not_equals(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        key = str(params.get("key", ""))
        if not key:
            raise ValueError("variable_not_equals requires 'key'")
        expected = params.get("value")
        actual = context.variables.get(key)
        return ConditionResult(actual != expected, "variable_not_equals", data={"key": key, "actual": actual, "expected": expected})

    @staticmethod
    def _variable_truthy(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        key = str(params.get("key", ""))
        if not key:
            raise ValueError("variable_truthy requires 'key'")
        actual = context.variables.get(key)
        return ConditionResult(bool(actual), "variable_truthy", data={"key": key, "actual": actual})

    @staticmethod
    def _variable_falsy(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        key = str(params.get("key", ""))
        if not key:
            raise ValueError("variable_falsy requires 'key'")
        actual = context.variables.get(key)
        return ConditionResult(not bool(actual), "variable_falsy", data={"key": key, "actual": actual})

    @staticmethod
    def _variable_exists(context: ConditionContext, params: dict[str, Any]) -> ConditionResult:
        key = str(params.get("key", ""))
        if not key:
            raise ValueError("variable_exists requires 'key'")
        return ConditionResult(key in context.variables, "variable_exists", data={"key": key})
