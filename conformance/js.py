"""JavaScript's values, as the TypeScript suite saw them (DRV-5, DRV-D36).

The scenarios judge JSON from a Driver with JavaScript's strict meaning: `true` is not `1`, an absent field
is not a field set to `null`, numbers are doubles, and JSON text is parsed, measured and printed as
JavaScript does. Values are plain Python ones: `None` is `null`, `UNDEFINED` is `undefined`, numbers are
`float` (an `int` written in a scenario counts as the same number), objects are `JSObject` and arrays are
`JSArray`, which read an absent field or index as `UNDEFINED`.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable, Iterable, Iterator
from json import decoder
from typing import Any


class Undefined:
    """JavaScript's `undefined`: what an absent field reads as. Distinct from `None`, which is `null`."""

    _instance: Undefined | None = None

    def __new__(cls) -> Undefined:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "undefined"

    def __bool__(self) -> bool:
        return False


UNDEFINED = Undefined()


class JSObject(dict[str, Any]):
    """A JSON object: a missing key reads as `undefined`, as in JavaScript; `obj[1]` reads the key "1"."""

    def __missing__(self, key: Any) -> Any:
        if not isinstance(key, str) and (key is None or key is UNDEFINED or isinstance(key, bool | int | float)):
            return self.get(text_of(key), UNDEFINED)
        return UNDEFINED


class JSArray(list[Any]):
    """A JSON array: an index outside it, negative ones included, reads as `undefined`, as in JavaScript; a slice
    is a JSArray too."""

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, slice):
            return JSArray(super().__getitem__(index))
        if not isinstance(index, int) or isinstance(index, bool):
            return get(self, index)
        if not 0 <= index < len(self):
            return UNDEFINED
        return super().__getitem__(index)


# JavaScript's \s and String.prototype.trim(): the same set, which is not Python's str.isspace().
SPACE = "\t\n\v\f\r              " \
    "    　﻿"
SPACE_CLASS = "[" + re.escape(SPACE) + "]"


def trim(text: str) -> str:
    return text.strip(SPACE)


def is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def is_object(value: object) -> bool:
    """`value !== null && typeof value === 'object' && !Array.isArray(value)`."""
    return isinstance(value, dict)


def typeof(value: object) -> str:
    if value is UNDEFINED:
        return "undefined"
    if value is None or isinstance(value, dict | list):
        return "object"
    if isinstance(value, bool):
        return "boolean"
    if is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    if callable(value):
        return "function"
    return "object"


def get(value: Any, key: str | int | float) -> Any:
    """`value?.[key]` on any JSON value: `undefined` where JavaScript gives it, also for null and undefined."""
    name = key if isinstance(key, str) else text_of(key)
    if isinstance(value, dict):
        return value.get(name, UNDEFINED)
    if isinstance(value, list | str):
        if name == "length":
            return len(value) if isinstance(value, list) else len16(value)
        if not INDEX_KEY.fullmatch(name):
            return UNDEFINED
        index = int(name)
        if isinstance(value, list):
            return value[index] if index < len(value) else UNDEFINED
        units = value.encode("utf-16-le", "surrogatepass")[2 * index:2 * index + 2]
        return units.decode("utf-16-le", "surrogatepass") if units else UNDEFINED
    return UNDEFINED


def len16(text: str) -> int:
    """The length of a string in UTF-16 units, as JavaScript counts it."""
    return len(text) + sum(1 for character in text if ord(character) > 0xFFFF)


def utf8_length(text: str) -> int:
    """Buffer.byteLength(text): UTF-8 bytes, with a lone surrogate counting as U+FFFD."""
    return len(well_formed(text).encode("utf-8"))


LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def well_formed(text: str) -> str:
    """The text with each lone surrogate replaced by U+FFFD, as Node writes it out."""
    return LONE_SURROGATE.sub("�", text)


# --- Equality --------------------------------------------------------------------------------------------


def same_value(a: object, b: object) -> bool:
    """Object.is for primitives: NaN is NaN, and -0 is not +0."""
    if is_number(a) and is_number(b):
        x, y = float(a), float(b)  # type: ignore[arg-type]
        if math.isnan(x) and math.isnan(y):
            return True
        return x == y and math.copysign(1.0, x) == math.copysign(1.0, y)
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if a is None or b is None or a is UNDEFINED or b is UNDEFINED:
        return a is b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return a is b


def strict_equal(actual: object, expected: object) -> bool:
    """util.isDeepStrictEqual for JSON values: kinds must match, absent is not undefined-valued.

    One Python frame per level of nesting (no generator), so the depth it reaches before RecursionError (about 1000)
    is near Node's (about 930 nested arrays, 1170 nested objects) before its RangeError."""
    if isinstance(actual, list | tuple) or isinstance(expected, list | tuple):
        if not (isinstance(actual, list | tuple) and isinstance(expected, list | tuple)) or len(actual) != len(expected):
            return False
        for a, b in zip(actual, expected, strict=True):
            if not strict_equal(a, b):
                return False
        return True
    if isinstance(actual, dict) or isinstance(expected, dict):
        if not (isinstance(actual, dict) and isinstance(expected, dict)) or set(actual) != set(expected):
            return False
        for key in actual:
            if not strict_equal(actual[key], expected[key]):
                return False
        return True
    return same_value(actual, expected)


def loose_includes(items: Iterable[object], value: object) -> bool:
    """Array.prototype.includes: SameValueZero, so -0 equals +0 and NaN finds NaN."""
    for item in items:
        if is_number(item) and is_number(value):
            x, y = float(item), float(value)  # type: ignore[arg-type]
            if x == y or (math.isnan(x) and math.isnan(y)):
                return True
        elif same_value(item, value):
            return True
    return False


# --- JSON.parse ------------------------------------------------------------------------------------------


class JSONError(ValueError):
    """JSON.parse refused the text."""


def _refuse_constant(name: str) -> object:
    raise JSONError(f'"{name}" is not valid JSON')


def _arrays(value: Any) -> Any:
    """The parsed value with every list made a JSArray, without recursion (JSON.parse has no depth limit)."""
    root = JSArray(value) if isinstance(value, list) else value
    pending = [root] if isinstance(root, list | dict) else []
    while pending:
        node = pending.pop()
        entries = enumerate(node) if isinstance(node, list) else node.items()
        for key, item in list(entries):
            if isinstance(item, list):
                item = node[key] = JSArray(item)
            if isinstance(item, list | dict):
                pending.append(item)
    return root


def parse(text: str) -> Any:
    """JSON.parse: strict JSON, every number a double, the last of duplicate keys at the first one's place."""
    try:
        value = json.loads(text, parse_constant=_refuse_constant, parse_int=float, object_pairs_hook=_object)
    except JSONError:
        raise
    except RecursionError:
        return _parse_deep(text)  # nested deeper than the json module goes; V8 has no such limit
    except ValueError as error:
        raise JSONError(str(error)) from None
    return _arrays(value)


def _parse_deep(text: str) -> Any:
    try:
        return _parse_iteratively(text)
    except JSONError:
        raise
    except ValueError as error:
        raise JSONError(str(error)) from None


# The json module's string scanner: the text after an opening quote, read as json.loads reads a string.
_scanstring: Callable[[str, int, bool], tuple[str, int]] = decoder.scanstring  # type: ignore[attr-defined]
_SPACE = re.compile(r"[ \t\n\r]*")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_LITERALS = {"true": True, "false": False, "null": None}


def _parse_iteratively(text: str) -> Any:
    """JSON.parse without recursion: the same grammar and values as `parse`, at any depth."""
    containers: list[Any] = []  # the arrays and objects still open, outermost first
    names: list[str] = []  # for each open object, the name its next value takes
    index = _SPACE.match(text).end()  # type: ignore[union-attr]

    def name(at: int) -> int:
        if text[at:at + 1] != '"':
            raise JSONError(f"Expected property name at position {at}")
        key, at = _scanstring(text, at + 1, True)
        at = _SPACE.match(text, at).end()  # type: ignore[union-attr]
        if text[at:at + 1] != ":":
            raise JSONError(f"Expected ':' after property name at position {at}")
        names.append(key)
        return _SPACE.match(text, at + 1).end()  # type: ignore[union-attr]

    while True:
        value: Any
        character = text[index:index + 1]
        if character in ("[", "{"):
            index = _SPACE.match(text, index + 1).end()  # type: ignore[union-attr]
            closing = "]" if character == "[" else "}"
            if text[index:index + 1] != closing:
                containers.append(JSArray() if character == "[" else JSObject())
                if character == "{":
                    index = name(index)
                continue
            value = JSArray() if character == "[" else JSObject()
            index += 1
        elif character == '"':
            value, index = _scanstring(text, index + 1, True)
        elif (number := _NUMBER.match(text, index)) is not None:
            value, index = float(number.group()), number.end()
        elif (word := next((word for word in _LITERALS if text.startswith(word, index)), None)) is not None:
            value, index = _LITERALS[word], index + len(word)
        else:
            raise JSONError(f"Unexpected token at position {index}")
        while True:
            index = _SPACE.match(text, index).end()  # type: ignore[union-attr]
            if not containers:
                if index != len(text):
                    raise JSONError(f"Unexpected non-whitespace character after JSON at position {index}")
                return value
            parent = containers[-1]
            if isinstance(parent, list):
                parent.append(value)
            else:
                parent[names.pop()] = value
            character = text[index:index + 1]
            if character == ",":
                index = _SPACE.match(text, index + 1).end()  # type: ignore[union-attr]
                if isinstance(parent, dict):
                    index = name(index)
                break
            if character != ("]" if isinstance(parent, list) else "}"):
                raise JSONError(f"Expected ',' or '{']' if isinstance(parent, list) else '}'}' at position {index}")
            value = containers.pop()
            index += 1


def _object(pairs: list[tuple[str, Any]]) -> JSObject:
    result = JSObject()
    for key, value in pairs:
        result[key] = value
    return result


# --- Keys, numbers and JSON.stringify -------------------------------------------------------------------

INDEX_KEY = re.compile(r"0|[1-9][0-9]*")


def keys(value: dict[str, Any]) -> list[str]:
    """Object.keys order: array-index keys ascending, then the others in insertion order."""
    indexes = sorted((key for key in value if INDEX_KEY.fullmatch(key) and int(key) < 2**32 - 1), key=int)
    index_set = set(indexes)
    return indexes + [key for key in value if key not in index_set]


def number_text(value: float) -> str:
    """Number.prototype.toString(): the shortest round-trip digits, laid out as JavaScript does."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exponent = repr(abs(float(value))).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = whole + fraction
    point = len(whole) + (int(exponent) if exponent else 0)  # the decimal point sits after this many digits
    significant = digits.lstrip("0")
    point -= len(digits) - len(significant)
    significant = significant.rstrip("0") or "0"
    k, n = len(significant), point
    if k <= n <= 21:
        text = significant + "0" * (n - k)
    elif 0 < n <= 21:
        text = significant[:n] + "." + significant[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + significant
    else:
        text = significant[0] + ("." + significant[1:] if k > 1 else "") + f"e{'+' if n - 1 >= 0 else '-'}{abs(n - 1)}"
    return sign + text


_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def quote(text: str) -> str:
    """A string as JSON.stringify writes it."""
    out = []
    for character in text:
        code = ord(character)
        if character in _ESCAPES:
            out.append(_ESCAPES[character])
        elif code < 0x20 or 0xD800 <= code <= 0xDFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(character)
    return '"' + "".join(out) + '"'


def _json_scalar(value: Any) -> str | Undefined | None:
    """JSON.stringify of a value that is not an array or object; None for one that is."""
    if value is UNDEFINED or callable(value):
        return UNDEFINED
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if is_number(value):
        number = float(value)
        return "null" if not math.isfinite(number) else number_text(number)
    if isinstance(value, str):
        return quote(value)
    if isinstance(value, list | tuple | dict):
        return None
    raise TypeError(f"Cannot convert {type(value).__name__} to JSON")


def stringify(value: Any) -> str | Undefined:
    """JSON.stringify(value) without spacing; `undefined` for a value it leaves out. A loop, not recursion, so any
    depth works, as in V8 up to about 6000 levels."""
    top = _json_scalar(value)
    if top is not None:
        return top
    out: list[str] = []
    stack: list[tuple[Any, Iterator[Any], list[bool]]] = []

    def open_(container: Any) -> None:
        if isinstance(container, dict):
            out.append("{")
            stack.append((container, iter(keys(container)), [True]))
        else:
            out.append("[")
            stack.append((None, iter(container), [True]))

    open_(value)
    while stack:
        container, entries, first = stack[-1]
        entry: Any = next(entries, _END)
        if entry is _END:
            out.append("]" if container is None else "}")
            stack.pop()
            continue
        item = entry if container is None else container[entry]
        text = _json_scalar(item)
        if container is not None and text is UNDEFINED:
            continue
        if not first[0]:
            out.append(",")
        first[0] = False
        if container is not None:
            out.append(f"{quote(entry)}:")
        if text is None:
            open_(item)
        else:
            out.append("null" if text is UNDEFINED else str(text))
    return "".join(out)


_END = object()


def _text_scalar(value: Any) -> str:
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if is_number(value):
        return number_text(float(value))
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "toString" in value:  # JSON can only set it to a value that is not a function
            raise TypeError("Cannot convert object to primitive value")
        return "[object Object]"
    return str(value)


def text_of(value: Any) -> str:
    """String(value) for the values a scenario prints. An array joins its items with commas, null and undefined as
    nothing; a loop, not recursion, so any depth works, as in V8 up to about 2800 levels."""
    if not isinstance(value, list | tuple):
        return _text_scalar(value)
    out: list[str] = []
    stack: list[Iterator[Any]] = [iter(value)]
    first = [True]
    while stack:
        item = next(stack[-1], _END)
        if item is _END:
            stack.pop()
            first.pop()
            continue
        if not first[-1]:
            out.append(",")
        first[-1] = False
        if isinstance(item, list | tuple):
            stack.append(iter(item))
            first.append(True)
        elif item is not None and item is not UNDEFINED:
            out.append(_text_scalar(item))
    return "".join(out)


# --- Node's path functions ------------------------------------------------------------------------------


def _normalize_string(path: str, allow_above_root: bool) -> str:
    """normalizeString in Node's lib/path.js, step for step: '.' and '..' resolved, runs of slashes collapsed."""
    res = ""
    last_segment_length = 0
    last_slash = -1
    dots = 0
    code = ""
    for i in range(len(path) + 1):
        if i < len(path):
            code = path[i]
        elif code == "/":
            break
        else:
            code = "/"
        if code == "/":
            if last_slash == i - 1 or dots == 1:
                pass
            elif dots == 2:
                if len(res) < 2 or last_segment_length != 2 or not res.endswith(".."):
                    if len(res) > 2:
                        last_slash_index = len(res) - last_segment_length - 1
                        if last_slash_index == -1:
                            res = ""
                            last_segment_length = 0
                        else:
                            res = res[:last_slash_index]
                            last_segment_length = len(res) - 1 - res.rfind("/")
                        last_slash = i
                        dots = 0
                        continue
                    if res:
                        res = ""
                        last_segment_length = 0
                        last_slash = i
                        dots = 0
                        continue
                if allow_above_root:
                    res += "/.." if res else ".."
                    last_segment_length = 2
            else:
                res = f"{res}/{path[last_slash + 1:i]}" if res else path[last_slash + 1:i]
                last_segment_length = i - last_slash - 1
            last_slash = i
            dots = 0
        elif code == "." and dots != -1:
            dots += 1
        else:
            dots = -1
    return res


def normalize(path: str) -> str:
    """path.posix.normalize: a trailing slash stays, as in Node."""
    if not path:
        return "."
    absolute = path.startswith("/")
    trailing = path.endswith("/")
    path = _normalize_string(path, not absolute)
    if not path:
        if absolute:
            return "/"
        return "./" if trailing else "."
    if trailing:
        path += "/"
    return f"/{path}" if absolute else path


def resolve(*paths: str) -> str:
    """path.posix.resolve: from right to left until a path is absolute, else from the working folder."""
    if not paths or (len(paths) == 1 and paths[0] in ("", ".")):
        cwd = os.getcwd()
        if cwd.startswith("/"):
            return cwd
    resolved = ""
    absolute = False
    for path in reversed(paths):
        if not path:
            continue
        resolved = f"{path}/{resolved}"
        absolute = path.startswith("/")
        if absolute:
            break
    if not absolute:
        cwd = os.getcwd()
        resolved = f"{cwd}/{resolved}"
        absolute = cwd.startswith("/")
    resolved = _normalize_string(resolved, not absolute)
    if absolute:
        return f"/{resolved}"
    return resolved or "."


def join(*paths: str) -> str:
    """path.posix.join: the nonempty paths joined with '/', then normalized (a trailing slash stays)."""
    joined = "/".join(path for path in paths if path)
    return normalize(joined) if joined else "."


def relative(start: str, target: str) -> str:
    """path.posix.relative: '' for the same path."""
    if start == target:
        return ""
    start = resolve(start)
    target = resolve(target)
    if start == target:
        return ""
    start_length = len(start) - 1
    target_length = len(target) - 1
    length = min(start_length, target_length)
    last_common = -1
    i = 0
    while i < length:
        code = start[1 + i]
        if code != target[1 + i]:
            break
        if code == "/":
            last_common = i
        i += 1
    if i == length:
        if target_length > length:
            if target[1 + i] == "/":
                return target[1 + i + 1:]
            if i == 0:
                return target[1 + i:]
        elif start_length > length:
            if start[1 + i] == "/":
                last_common = i
            elif i == 0:
                last_common = 0
    out = ""
    for j in range(1 + last_common + 1, len(start) + 1):
        if j == len(start) or start[j] == "/":
            out += "/.." if out else ".."
    return out + target[1 + last_common:]


def dirname(path: str) -> str:
    """path.posix.dirname, step for step: dirname('a//b') is 'a/', dirname('//a') is '//'."""
    if not path:
        return "."
    has_root = path.startswith("/")
    end = -1
    matched_slash = True
    for i in range(len(path) - 1, 0, -1):
        if path[i] == "/":
            if not matched_slash:
                end = i
                break
        else:
            matched_slash = False
    if end == -1:
        return "/" if has_root else "."
    if has_root and end == 1:
        return "//"
    return path[:end]


def is_absolute(path: str) -> bool:
    return path.startswith("/")


def truthy(value: object) -> bool:
    """JavaScript truthiness: undefined, null, false, 0, -0, NaN and '' are false; [] and {} are true."""
    if value is UNDEFINED or value is None or value is False:
        return False
    if is_number(value):
        number = float(value)  # type: ignore[arg-type]
        return number != 0 and not math.isnan(number)
    if isinstance(value, str):
        return value != ""
    return True
