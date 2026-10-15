"""The judgements of a scenario: a failed one names what was expected and what was received."""

from __future__ import annotations

from typing import Any

from .js import JSObject, is_object, len16, strict_equal, truthy


class Mismatch(Exception):
    def __init__(self, message: str, expected: Any, actual: Any) -> None:
        super().__init__(message)
        self.message = message
        self.expected = expected
        self.actual = actual


class ScenarioError(Exception):
    """A plain error of a scenario: printed with its message only, as a JavaScript Error was."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def message_of(error: BaseException) -> str:
    return getattr(error, "message", None) or str(error)


def equal(message: str, actual: Any, expected: Any) -> None:
    if not strict_equal(actual, expected):
        raise Mismatch(message, expected, actual)


def check(message: str, condition: Any, expected: Any, actual: Any) -> None:
    """Fails unless the condition is true as JavaScript tests it (an empty array or object is true)."""
    if not truthy(condition):
        raise Mismatch(message, expected, actual)


def object_(message: str, value: Any) -> JSObject:
    check(message, is_object(value), "a JSON object", value)
    return value if isinstance(value, JSObject) else JSObject(value)


def text(message: str, value: Any) -> str:
    check(message, isinstance(value, str) and len16(value) > 0, "a nonempty string", value)
    return str(value)
