"""Bounded complete-line reads and streaming metadata for oversized Exchange events."""

from __future__ import annotations

import asyncio
import codecs
import json
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from .bridge import MAX_LINE, Params, decode
from .model import Refused

CHUNK = 65536
TOKEN = 8192
EVENTS = {"started", "text_delta", "text", "thinking_delta", "thinking", "tool_started", "tool_output_delta",
          "tool_finished", "ask_opened", "ask_closed", "usage", "notice", "control_refused", "finished"}
BODIES = {"event", "answer", "smallRun", "end"}
INTEREST = {("n",), *((body, name) for body in BODIES for name in
                       ("type", "runId", "parentCallId", "callId", "askId", "state"))}
SPECIAL = re.compile(r'["\\\x00-\x1f]')
NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')


@dataclass
class Node:
    kind: str
    path: tuple[str, ...] | None
    state: str
    key: str | None = None
    seen: set[str] = field(default_factory=set)


class Envelope:
    """A SAX-like JSON recognizer retaining only a few bounded envelope scalars."""
    def __init__(self) -> None:
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.stack: list[Node] = []
        self.values: dict[tuple[str, ...], Any] = {}
        self.bodies: set[str] = set()
        self.started = self.done = False
        self.mode = ""
        self.raw = ""
        self.large = False
        self.escaped = False
        self.unicode = 0
        self.number_state = ""

    def append(self, value: str) -> None:
        if not self.large:
            if len(self.raw) + len(value) <= TOKEN:
                self.raw += value
            else:
                self.large = True
                self.raw = ""

    def place(self) -> tuple[str, ...] | None:
        if not self.stack:
            if self.started:
                raise ValueError("Several roots.")
            self.started = True
            return ()
        node = self.stack[-1]
        if node.kind == "object":
            if node.state != "value":
                raise ValueError("Unexpected value.")
            node.state = "comma"
            return (*node.path, node.key) if node.path is not None and node.key is not None else None
        if node.state not in ("first", "value"):
            raise ValueError("Unexpected array value.")
        node.state = "comma"
        return None

    def token(self, kind: str, value: Any = None) -> None:
        if self.done:
            raise ValueError("Trailing data.")
        if kind in ("{", "["):
            path = self.place()
            if path == () and kind != "{":
                raise ValueError("Root must be an object.")
            if len(self.stack) >= 256:
                raise ValueError("Deep JSON.")
            if path and len(path) == 1 and path[0] in BODIES and kind == "{":
                self.bodies.add(path[0])
            keep = path if path == () or path and len(path) == 1 and path[0] in BODIES else None
            self.stack.append(Node("object" if kind == "{" else "array", keep,
                                   "first" if kind == "[" else "first-key"))
            return
        if kind in ("}", "]"):
            if not self.stack:
                raise ValueError("Unexpected close.")
            node = self.stack.pop()
            if ((kind == "}") != (node.kind == "object") or node.state not in ("first", "first-key", "comma")):
                raise ValueError("Incomplete container.")
            if not self.stack:
                self.done = True
            return
        if kind == ":":
            if not self.stack or self.stack[-1].kind != "object" or self.stack[-1].state != "colon":
                raise ValueError("Unexpected colon.")
            self.stack[-1].state = "value"
            return
        if kind == ",":
            if not self.stack or self.stack[-1].state != "comma":
                raise ValueError("Unexpected comma.")
            node = self.stack[-1]
            node.state = "key" if node.kind == "object" else "value"
            return
        if kind == "string" and self.stack and self.stack[-1].kind == "object" and self.stack[-1].state in ("first-key", "key"):
            node = self.stack[-1]
            node.key = value
            if value is not None and node.path is not None and ((*node.path, value) in INTEREST or node.path == () and value in BODIES):
                if value in node.seen:
                    raise ValueError("Duplicate envelope key.")
                node.seen.add(value)
            node.state = "colon"
            return
        path = self.place()
        if path == ():
            raise ValueError("Root must be an object.")
        if path in INTEREST:
            self.values[path] = value

    def number(self, char: str) -> bool:
        state = self.number_state
        if state == "minus" and char.isascii() and char.isdigit():
            self.number_state = "zero" if char == "0" else "int"
        elif state == "zero" and char == "." or state == "int" and char == ".":
            self.number_state = "point"
        elif state in ("zero", "int", "frac") and char in "eE":
            self.number_state = "exp"
        elif state in ("int", "point", "frac", "exp", "esign", "edig") and char.isascii() and char.isdigit():
            self.number_state = "int" if state == "int" else "frac" if state in ("point", "frac") else "edig"
        elif state == "exp" and char in "+-":
            self.number_state = "esign"
        else:
            return False
        self.append(char)
        return True

    def finish_number(self) -> None:
        if self.number_state not in ("zero", "int", "frac", "edig"):
            raise ValueError("Incomplete number.")
        value = None
        if not self.large:
            if not NUMBER.fullmatch(self.raw):
                raise ValueError("Invalid number.")
            # Metadata counters are small integers; never allocate an enormous Python integer.
            if len(self.raw) < 64:
                value = json.loads(self.raw)
        self.token("number", value)
        self.mode, self.raw, self.large = "", "", False

    def feed(self, data: bytes, *, final: bool = False) -> None:
        value = self.decoder.decode(data, final=final)
        at = 0
        while at < len(value):
            char = value[at]
            if self.mode == "string":
                if self.unicode:
                    if char not in "0123456789abcdefABCDEF":
                        raise ValueError("Invalid Unicode escape.")
                    self.append(char)
                    self.unicode -= 1
                    at += 1
                    continue
                if self.escaped:
                    if char not in '"\\/bfnrtu':
                        raise ValueError("Invalid escape.")
                    self.append(char)
                    self.escaped = False
                    self.unicode = 4 if char == "u" else 0
                    at += 1
                    continue
                match = SPECIAL.search(value, at)
                stop = match.start() if match else len(value)
                self.append(value[at:stop])
                at = stop
                if match is None:
                    break
                char = value[at]
                self.append(char)
                at += 1
                if char == '"':
                    parsed = None if self.large else json.loads(self.raw)
                    self.mode, self.raw, self.large = "", "", False
                    self.token("string", parsed)
                elif char == "\\":
                    self.escaped = True
                else:
                    raise ValueError("Raw control in string.")
                continue
            if self.mode == "number":
                if self.number(char):
                    at += 1
                    continue
                self.finish_number()
                continue
            if self.mode == "literal":
                if char.isascii() and char.isalpha():
                    self.append(char)
                    if self.large or len(self.raw) > 5:
                        raise ValueError("Invalid literal.")
                    at += 1
                    continue
                if self.raw not in ("true", "false", "null"):
                    raise ValueError("Invalid literal.")
                self.token("literal", json.loads(self.raw))
                self.mode, self.raw = "", ""
                continue
            if char in " \t\r\n":
                at += 1
            elif char in "{}[]:,":
                self.token(char)
                at += 1
            elif char == '"':
                self.mode, self.raw, self.large = "string", '"', False
                at += 1
            elif char == "-" or char.isascii() and char.isdigit():
                self.mode, self.raw, self.large = "number", char, False
                self.number_state = "minus" if char == "-" else "zero" if char == "0" else "int"
                at += 1
            elif char in "tfn":
                self.mode, self.raw = "literal", char
                at += 1
            else:
                raise ValueError("Unexpected JSON byte.")
        if final:
            if self.mode == "number":
                self.finish_number()
            elif self.mode == "literal":
                if self.raw not in ("true", "false", "null"):
                    raise ValueError("Invalid literal.")
                self.token("literal", json.loads(self.raw))
                self.mode = ""
            if self.mode or self.stack or not self.done:
                raise ValueError("Unfinished JSON.")


@dataclass(frozen=True)
class Meta:
    n: int
    kind: str
    run: str = ""
    parent: str = ""
    call: str = ""
    ask: str = ""

    def block(self) -> tuple[str, str, str, str] | None:
        if not self.run:
            return None
        kind = {"text": "text", "text_delta": "text", "thinking": "thinking", "thinking_delta": "thinking"}.get(self.kind)
        if kind:
            return self.run, self.parent, kind, ""
        if self.kind in ("tool_finished", "tool_output_delta") and self.call:
            return self.run, self.parent, "tool", self.call
        return None


def metadata(values: dict[tuple[str, ...], Any], bodies: set[str]) -> Meta | None:
    n = values.get(("n",))
    if type(n) is not int or not 1 <= n <= 9223372036854775807 or len(bodies) != 1:
        return None
    body = next(iter(bodies))
    kind = values.get((body, "type")) if body != "end" else "end"
    if ((body == "event" and kind not in EVENTS) or (body == "smallRun" and kind != "finished")
            or (body == "answer" and kind != "answer")):
        return None
    def name(key: str) -> str:
        value = values.get((body, key))
        return value if isinstance(value, str) else ""
    return Meta(n, str(kind), name("runId"), name("parentCallId"), name("callId"), name("askId"))


def meta(value: Params) -> Meta | None:
    bodies = {key for key in BODIES if isinstance(value.get(key), dict)}
    values: dict[tuple[str, ...], Any] = {("n",): value.get("n")}
    for body in bodies:
        values.update({(body, key): item for key, item in value[body].items() if (body, key) in INTEREST})
    return metadata(values, bodies)


@dataclass(frozen=True)
class Line:
    meta: Meta
    value: Params | None
    start: int
    end: int
    size: int

    def wire(self) -> Params:
        return self.value if self.value is not None else {"n": self.meta.n, "tooLarge": True, "bytes": self.size}


class Scanner:
    def __init__(self, descriptor: int, *, offset: int = 0) -> None:
        self.descriptor = descriptor
        self.offset = self.complete = self.start = offset
        self.size = 0
        self.buffer = bytearray()
        self.envelope: Envelope | None = None
        self.invalid = False
        self.last_n = 0

    async def part(self, data: bytes) -> None:
        self.size += len(data)
        try:
            if self.envelope is None and not self.invalid:
                if len(self.buffer) + len(data) <= MAX_LINE:
                    self.buffer.extend(data)
                    return
                self.envelope = Envelope()
                for at in range(0, len(self.buffer), CHUNK):
                    self.envelope.feed(bytes(self.buffer[at:at+CHUNK]))
                    await asyncio.sleep(0)
                self.buffer.clear()
            if self.envelope is not None and not self.invalid:
                self.envelope.feed(data)
        except (ValueError, UnicodeError, RecursionError):
            self.invalid = True
            self.buffer.clear()
            self.envelope = None

    def finished(self) -> Line | None:
        result = None
        try:
            value: Params | None = None
            info = None
            if not self.invalid:
                if self.envelope is not None:
                    self.envelope.feed(b"", final=True)
                    info = metadata(self.envelope.values, self.envelope.bodies)
                    observed = self.envelope.values.get(("n",))
                else:
                    value = decode(bytes(self.buffer))
                    info = meta(value)
                    observed = value.get("n")
                if type(observed) is int and 1 <= observed <= 9223372036854775807 and observed > self.last_n:
                    self.last_n = observed
                    if info is not None:
                        result = Line(info, value, self.start, self.offset, self.size)
        except (ValueError, UnicodeError, RecursionError, Refused):
            pass
        self.complete = self.start = self.offset
        self.size = 0
        self.buffer.clear()
        self.envelope = None
        self.invalid = False
        return result

    async def lines(self, *, limit: int | None = None) -> AsyncIterator[Line]:
        end = os.fstat(self.descriptor).st_size if limit is None else limit
        emitted = 0
        while self.offset < end:
            chunk = os.pread(self.descriptor, min(CHUNK, end-self.offset), self.offset)
            if not chunk:
                return
            at = 0
            while at < len(chunk):
                newline = chunk.find(b"\n", at)
                stop = len(chunk) if newline < 0 else newline+1
                part = chunk[at:stop]
                self.offset += len(part)
                await self.part(part)
                at = stop
                if newline >= 0:
                    line = self.finished()
                    if line is not None:
                        yield line
                        emitted += 1
                        if emitted % 64 == 0:
                            await asyncio.sleep(0)
            await asyncio.sleep(0)


async def completed(descriptor: int, limit: int) -> tuple[int, dict[tuple[str, str, str, str], int]]:
    reader = Scanner(descriptor)
    blocks: dict[tuple[str, str, str, str], int] = {}
    async for line in reader.lines(limit=limit):
        if line.meta.kind in ("text", "thinking", "tool_finished") and (key := line.meta.block()) is not None:
            blocks[key] = line.meta.n
    return reader.complete, blocks


def superseded(line: Line, blocks: dict[tuple[str, str, str, str], int]) -> bool:
    return (line.meta.kind in ("text_delta", "thinking_delta", "tool_output_delta")
            and (key := line.meta.block()) is not None and line.meta.n < blocks.get(key, 0))
