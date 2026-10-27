"""BKD-1 framed connections and versioned topic subscriptions; no raw wire logging."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .model import Refused

MAX_LINE = 16 * 1024 * 1024
MAX_WAITING = 64 * 1024 * 1024
MAX_IDS = 65536
MESSAGES = {
    "draft_conflict": "The Draft changed in another window; use its current text and revision.",
    "invalid_input": "The Bridge request is invalid.",
    "unknown_method": "This Build does not provide that method or topic.",
    "not_found": "The requested item was not found.",
    "database_unavailable": "The Root database is unavailable.",
    "timeout": "The operation exceeded its time limit.",
    "layout_incomplete": "The Root lacks the backend database layout.",
    "ended": "The subscription has ended.",
    "no_answer": "The requested program did not provide a valid answer.",
    "slow_reader": "This window has more than 64 MiB waiting to be sent.",
}
SOURCES = {"trunk", "root-manager", "roots", "driver"}
Params = dict[str, Any]
Validator = Callable[[Params], Awaitable[Params]]
Handler = Callable[[Params], Awaitable[Any]]


class Error(Refused):
    def __init__(self, code: str, *, source: str | None = None) -> None:
        super().__init__(code, MESSAGES.get(code, "The requested program refused the operation."))
        if source is not None and source not in SOURCES:
            raise ValueError("Invalid Bridge error source.")
        self.source = source

    def wire(self) -> Params:
        value = {"code": self.code, "message": str(self)}
        if self.source:
            value["source"] = self.source
        return value


def safe_error(error: Refused) -> Params:
    return error.wire() if isinstance(error, Error) else Error(
        error.code if error.code in MESSAGES else "no_answer"
    ).wire()


def encode(value: Params) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Error("invalid_input") from error
    if len(data) > MAX_LINE:
        raise Error("invalid_input")
    return data


def pairs(items: list[tuple[str, Any]]) -> Params:
    result: Params = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def constant(value: str) -> Any:
    raise ValueError("Non-finite JSON number.")


def finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number.")
    return number


def decode(data: bytes) -> Params:
    if len(data) > MAX_LINE or not data.endswith(b"\n"):
        raise ValueError("Invalid frame.")
    value: object = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
    if not isinstance(value, dict):
        raise ValueError("Expected object.")
    return value


def request_id(value: object) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Invalid correlation id.")
    if len(value.encode("utf-8")) > 128:
        raise ValueError("Long correlation id.")
    return value


def uuid_id(value: object) -> str:
    if not isinstance(value, str):
        raise Error("invalid_input")
    try:
        if str(UUID(value)) != value:
            raise ValueError("Noncanonical UUID.")
    except ValueError as error:
        raise Error("invalid_input") from error
    return value


def driver_id(value: object, launchers: set[str]) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", value) or value not in launchers:
        raise Error("invalid_input")
    return value


def subscription_id(value: object, subscriptions: set[str]) -> str:
    if not isinstance(value, str) or value not in subscriptions:
        raise Error("invalid_input")
    return value


async def no_params(params: Params) -> Params:
    return {}


@dataclass(frozen=True)
class Snapshot:
    version: int
    event: Params


@dataclass
class Topic:
    snapshot: Callable[[Params], Awaitable[Snapshot]]
    validate: Validator = no_params
    version: int = 0
    listeners: set[Subscription] = field(default_factory=set)

    def publish(self, event: Params, *, params: Params | None = None) -> None:
        self.version += 1
        for subscription in list(self.listeners):
            if params is None or subscription.params == params:
                subscription.publish(self.version, event)

    def fail(self, error: Refused, *, params: Params | None = None) -> None:
        for subscription in list(self.listeners):
            if params is None or subscription.params == params:
                subscription.connection.end(subscription, error)


class Registry:
    def __init__(self) -> None:
        self.methods: dict[str, tuple[Validator, Handler]] = {}
        self.topics: dict[str, Topic] = {}

    def method(self, name: str, handler: Handler, validate: Validator = no_params) -> None:
        self.methods[name] = (validate, handler)


@dataclass
class Frame:
    data: bytes
    subscription: Subscription | None = None
    seq: int = 0


@dataclass(eq=False)
class Subscription:
    connection: Connection
    id: str
    topic: Topic
    params: Params
    key: bytes
    seq: int = 0
    sent: int = 0
    ready: bool = False
    active: bool = True
    pending: list[tuple[int, bytes]] = field(default_factory=list)
    task: asyncio.Task[None] | None = None

    def publish(self, version: int, event: Params) -> None:
        if not self.active:
            return
        try:
            if self.ready:
                self.send(event)
            else:
                data = encode(event)
                self.pending.append((version, data))
                self.connection.buffered += len(data)
                self.connection.check_waiting()
        except Refused as error:
            self.connection.end(self, error)

    def send(self, event: Params) -> None:
        data = encode({"type": "event", "id": self.id, "seq": self.seq + 1, "event": event})
        self.seq += 1
        self.connection.enqueue(Frame(data, self, self.seq))

    async def begin(self) -> None:
        try:
            snapshot = await self.topic.snapshot(self.params)
            if not self.active:
                return
            self.send(snapshot.event)
            pending, self.pending = self.pending, []
            self.connection.buffered -= sum(len(data) for _, data in pending)
            self.ready = True
            for version, data in pending:
                if self.active and version > snapshot.version:
                    self.send(decode(data))
        except Refused as error:
            self.connection.end(self, error)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.connection.end(self, Error("no_answer"))


class Connection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, registry: Registry) -> None:
        self.reader, self.writer, self.registry = reader, writer, registry
        self.ids: set[str] = set()
        self.subscriptions: dict[str, Subscription] = {}
        self.keys: dict[bytes, Subscription] = {}
        self.queue: deque[Frame] = deque()
        self.queued = 0
        self.buffered = 0
        self.wake = asyncio.Event()
        self.tasks: set[asyncio.Task[None]] = set()
        self.sender: asyncio.Task[None] | None = None
        self.slow_task: asyncio.Task[None] | None = None
        self.closed = False
        self.slow = False

    def task(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def enqueue(self, frame: Frame) -> None:
        if self.closed or self.slow:
            return
        self.queue.append(frame)
        self.queued += len(frame.data)
        self.wake.set()
        self.check_waiting()

    def waiting(self) -> int:
        return self.queued + self.buffered + self.writer.transport.get_write_buffer_size()

    def check_waiting(self) -> None:
        if not self.slow and not self.closed and self.waiting() > MAX_WAITING:
            self.slow = True
            notices = [encode({"type": "ended", "id": sub.id, "error": Error("slow_reader").wire()})
                       for sub in self.subscriptions.values()]
            for sub in list(self.subscriptions.values()):
                self.detach(sub)
            self.queue.clear()
            self.queued = 0
            if self.sender:
                self.sender.cancel()
            self.slow_task = self.task(self.finish_slow(notices))

    async def finish_slow(self, notices: list[bytes]) -> None:
        try:
            async with asyncio.timeout(1):
                for notice in notices:
                    self.writer.write(notice)
                await self.writer.drain()
        except (TimeoutError, OSError, ConnectionError):
            pass
        finally:
            self.writer.transport.abort()

    async def send(self) -> None:
        try:
            while True:
                await self.wake.wait()
                while self.queue:
                    frame = self.queue.popleft()
                    self.queued -= len(frame.data)
                    self.writer.write(frame.data)
                    if frame.subscription:
                        frame.subscription.sent = frame.seq
                    self.check_waiting()
                    await self.writer.drain()
                self.wake.clear()
        except (ConnectionError, OSError):
            self.writer.transport.abort()

    def detach(self, sub: Subscription) -> None:
        sub.active = False
        sub.topic.listeners.discard(sub)
        self.subscriptions.pop(sub.id, None)
        if self.keys.get(sub.key) is sub:
            self.keys.pop(sub.key)
        self.buffered -= sum(len(data) for _, data in sub.pending)
        sub.pending.clear()
        if sub.task and sub.task is not asyncio.current_task():
            sub.task.cancel()

    def end(self, sub: Subscription, error: Refused | None = None) -> None:
        if not sub.active:
            return
        self.detach(sub)
        message: Params = {"type": "ended", "id": sub.id}
        if error:
            message["error"] = safe_error(error)
        self.enqueue(Frame(encode(message)))

    async def call(self, id: str, method: object, params: object) -> None:
        try:
            if not isinstance(method, str) or not isinstance(params, dict):
                raise Error("invalid_input")
            if method == "subscriptions.check":
                result: Any = {"subscriptions": [{"id": sub.id, "seq": sub.sent}
                                                 for sub in self.subscriptions.values()]}
            else:
                entry = self.registry.methods.get(method)
                if entry is None:
                    raise Error("unknown_method")
                validate, handler = entry
                result = await handler(await validate(params))
            frame = encode({"type": "reply", "id": id, "result": result})
        except Refused as error:
            frame = encode({"type": "reply", "id": id, "error": safe_error(error)})
        except asyncio.CancelledError:
            raise
        except Exception:
            frame = encode({"type": "reply", "id": id, "error": Error("no_answer").wire()})
        self.enqueue(Frame(frame))

    async def subscribe(self, id: str, name: object, params: object) -> None:
        try:
            if not isinstance(name, str) or not isinstance(params, dict):
                raise Error("invalid_input")
            topic = self.registry.topics.get(name)
            if topic is None:
                raise Error("unknown_method")
            normalized = await topic.validate(params)
            key = json.dumps({"topic": name, "params": normalized}, sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if self.closed or self.slow:
                return
            if old := self.keys.get(key):
                self.end(old)
            sub = Subscription(self, id, topic, normalized, key)
            self.subscriptions[id] = sub
            self.keys[key] = sub
            topic.listeners.add(sub)
            sub.task = self.task(sub.begin())
        except Refused as error:
            self.enqueue(Frame(encode({"type": "ended", "id": id, "error": safe_error(error)})))
        except asyncio.CancelledError:
            raise
        except Exception:
            self.enqueue(Frame(encode({"type": "ended", "id": id, "error": Error("no_answer").wire()})))

    async def run(self, hello: Callable[[], Awaitable[Params]]) -> None:
        try:
            self.enqueue(Frame(encode(await hello())))
            self.sender = self.task(self.send())
            while not self.slow:
                data = await self.reader.readuntil(b"\n")
                message = decode(data)
                kind = message.get("type")
                if kind not in ("call", "subscribe", "unsubscribe"):
                    continue
                id = request_id(message.get("id"))
                if kind == "unsubscribe":
                    if sub := self.subscriptions.get(id):
                        self.end(sub)
                    continue
                if id in self.ids or len(self.ids) >= MAX_IDS:
                    break
                self.ids.add(id)
                if kind == "call":
                    self.task(self.call(id, message.get("method"), message.get("params", {})))
                else:
                    # Serial registration preserves wire order of replacement/unsubscribe.
                    await self.subscribe(id, message.get("topic"), message.get("params", {}))
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, UnicodeError,
                RecursionError, Refused, OSError, ConnectionError):
            pass
        except Exception:
            pass
        finally:
            if self.slow_task:
                await self.slow_task
            self.closed = True
            for sub in list(self.subscriptions.values()):
                self.detach(sub)
            for task in list(self.tasks):
                task.cancel()
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            self.writer.close()
            with contextlib.suppress(OSError, ConnectionError):
                await self.writer.wait_closed()
