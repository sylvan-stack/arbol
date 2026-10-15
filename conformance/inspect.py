"""Node's util.inspect for JSON values, as the report prints Expected and Received (DRV-5, Interface).

The subset of Node 24.21's lib/internal/util/inspect.js that JSON values reach, with the options the runner
used: depth 6, at most 20 array items, compact 3, a line of 80 columns, and 10000 characters of a string
(2048 for Received).
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from typing import Any

from .js import UNDEFINED, is_number, keys, len16, number_text
from .widths import WIDTH_STARTS, WIDTHS

DEPTH = 6
MAX_ARRAY = 20
BREAK = 80
COMPACT = 3
MIN_LINE = 16
IDENTIFIER = re.compile(r"[a-zA-Z_][a-zA-Z_0-9]*")


class _Context:
    def __init__(self, max_string: int) -> None:
        self.indentation = 0
        self.current_depth = 0
        self.max_string = max_string


def inspect(value: Any, max_string: int = 10000) -> str:
    return _value(_Context(max_string), value, 0)


def _value(ctx: _Context, value: Any, depth: int) -> str:
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if is_number(value):
        number = float(value)
        return "-0" if number == 0 and math.copysign(1.0, number) < 0 else number_text(number)
    if isinstance(value, str):
        return _string(ctx, value)
    if isinstance(value, list | tuple):
        return _raw(ctx, list(value), depth)
    if isinstance(value, dict):
        return _raw(ctx, value, depth)
    return _string(ctx, str(value))


def _raw(ctx: _Context, value: list[Any] | dict[str, Any], depth: int) -> str:
    if isinstance(value, list):
        if not value:
            return "[]"
        braces = ("[", "]")
    else:
        if not value:
            return "{}"
        braces = ("{", "}")
    if depth > DEPTH:
        return "[Array]" if isinstance(value, list) else "[Object]"
    depth += 1
    ctx.current_depth = depth
    output: list[str] = []
    if isinstance(value, list):
        for item in value[:MAX_ARRAY]:
            output.append(_child(ctx, item, depth))
        if len(value) > MAX_ARRAY:
            more = len(value) - MAX_ARRAY
            output.append(f"... {more} more item{'s' if more > 1 else ''}")
    else:
        for key in keys(value):
            output.append(f"{_key(key)}: {_child(ctx, value[key], depth)}")
    return _reduce(ctx, output, braces, isinstance(value, list), depth, value)


def _child(ctx: _Context, value: Any, depth: int) -> str:
    ctx.indentation += 2
    try:
        return _value(ctx, value, depth)
    finally:
        ctx.indentation -= 2


def _key(key: str) -> str:
    if IDENTIFIER.fullmatch(key):
        return "['__proto__']" if key == "__proto__" else key
    return _escape(key)


def _reduce(ctx: _Context, output: list[str], braces: tuple[str, str], array: bool, depth: int,
            value: list[Any] | dict[str, Any]) -> str:
    entries = len(output)
    if array and entries > 6:
        output = _group(ctx, output, value)  # type: ignore[arg-type]
    if ctx.current_depth - depth < COMPACT and entries == len(output):
        start = len(output) + ctx.indentation + len16(braces[0]) + 10
        if _below_break(output, start):
            joined = ", ".join(output)
            if "\n" not in joined:
                return f"{braces[0]} {joined} {braces[1]}"
    indentation = "\n" + " " * ctx.indentation
    return f"{braces[0]}{indentation}  " + f",{indentation}  ".join(output) + f"{indentation}{braces[1]}"


def _below_break(output: list[str], start: int) -> bool:
    total = len(output) + start
    if total + len(output) > BREAK:
        return False
    for entry in output:
        total += len16(entry)
        if total > BREAK:
            return False
    return True


def _group(ctx: _Context, output: list[str], value: list[Any]) -> list[str]:
    total = 0
    longest = 0
    count = len(output) - 1 if MAX_ARRAY < len(output) else len(output)
    widths = [width(output[i]) for i in range(count)]
    for size in widths:
        total += size + 2
        longest = max(longest, size)
    actual = longest + 2
    if actual * 3 + ctx.indentation < BREAK and (total / actual > 5 or longest <= 6):
        bias = math.sqrt(actual - total / len(output))
        biased = max(actual - 3 - bias, 1)
        columns = min(math.floor(math.sqrt(2.5 * biased * count) / biased + 0.5),
                      math.floor((BREAK - ctx.indentation) / actual), COMPACT * 4, 15)
        if columns <= 1:
            return output
        line_lengths = []
        for i in range(columns):
            line = 0
            for j in range(i, len(output), columns):
                if j < count and widths[j] > line:
                    line = widths[j]
            line_lengths.append(line + 2)
        numbers = all(is_number(value[i]) for i in range(len(output)))
        grouped: list[str] = []
        for i in range(0, count, columns):
            last = min(i + columns, count)
            row = ""
            j = i
            while j < last - 1:
                padding = line_lengths[j - i] + len16(output[j]) - widths[j]
                row += _pad(f"{output[j]}, ", padding, numbers)
                j += 1
            if numbers:
                padding = line_lengths[j - i] + len16(output[j]) - widths[j] - 2
                row += _pad(output[j], padding, True)
            else:
                row += output[j]
            grouped.append(row)
        if MAX_ARRAY < len(output):
            grouped.append(output[count])
        return grouped
    return output


def _pad(text: str, length: int, start: bool) -> str:
    fill = " " * max(0, length - len16(text))
    return fill + text if start else text + fill


def width(text: str) -> int:
    """Node's getStringWidth(text, false): columns on a terminal."""
    total = 0
    for index, character in enumerate(text):
        code = ord(character)
        if code >= 127:
            for point in unicodedata.normalize("NFC", text[index:]):
                total += _point_width(ord(point))
            return total
        total += 1 if code >= 32 else 0
    return total


def _point_width(code: int) -> int:
    if code < 127:
        return 1 if code >= 32 else 0
    return WIDTHS[bisect.bisect_right(WIDTH_STARTS, code) - 1]


# --- Strings ---------------------------------------------------------------------------------------------


def _utf16_cut(text: str, length: int) -> str:
    """The first `length` UTF-16 units of text; a pair it cuts leaves its high surrogate alone."""
    data = text.encode("utf-16-le", "surrogatepass")[: 2 * length]
    return data.decode("utf-16-le", "surrogatepass")


def _string(ctx: _Context, text: str) -> str:
    trailer = ""
    size = len16(text)
    if size > ctx.max_string:
        remaining = size - ctx.max_string
        text = _utf16_cut(text, ctx.max_string)
        size = ctx.max_string
        trailer = f"... {remaining} more character{'s' if remaining > 1 else ''}"
    if size > MIN_LINE and size > BREAK - ctx.indentation - 4:
        pieces = re.split(r"(?<=\n)", text)
        if pieces and pieces[-1] == "":
            pieces.pop()
        return f" +\n{' ' * (ctx.indentation + 2)}".join(_escape(piece) for piece in pieces) + trailer
    return _escape(text) + trailer


_META = {**{code: f"\\x{code:02X}" for code in range(0x20)}, 8: "\\b", 9: "\\t", 10: "\\n", 12: "\\f", 13: "\\r",
         **{code: f"\\x{code:02X}" for code in range(0x7F, 0xA0)}, 92: "\\\\"}


def _escape(text: str) -> str:
    """strEscape: the quote that needs no escaping, and \\x and \\u escapes for control and lone surrogates."""
    quote = "'"
    if "'" in text:
        if '"' not in text:
            quote = '"'
        elif "`" not in text and "${" not in text:
            quote = "`"
    out = []
    units = list(text)
    index = 0
    while index < len(units):
        character = units[index]
        code = ord(character)
        if quote == "'" and code == 39:
            out.append("\\'")
        elif code in _META:
            out.append(_META[code])
        elif 0xD800 <= code <= 0xDBFF:
            if index + 1 < len(units) and 0xDC00 <= ord(units[index + 1]) <= 0xDFFF:
                out.append(character + units[index + 1])
                index += 1
            else:
                out.append(f"\\u{code:x}")
        elif 0xDC00 <= code <= 0xDFFF:
            out.append(f"\\u{code:x}")
        else:
            out.append(character)
        index += 1
    return quote + "".join(out) + quote
