"""The home of one scenario: a private temporary folder with the vendor tool's stand-in (DRV-5, Interface).

Each scenario gets a fresh home with both settings files naming `<home>/tool/vendor-tool`, a shell launcher
that starts the Driver's own `dev stand-in` as the vendor tool, `<home>/tool/scenario` naming the part being
run, and a minimal environment. The stand-in writes what it received to `<home>/tool/received.jsonl`.
"""

from __future__ import annotations

import asyncio
import ctypes
import errno
import os
import secrets
import stat
import string
import sys
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .check import Mismatch, ScenarioError, check, object_
from .command import shell_quote
from .js import JSObject, JSONError, dirname, is_absolute, join, parse, relative, stringify, text_of, trim
from .process import Abort, Interaction, invoke

LETTERS = string.digits + string.ascii_uppercase + string.ascii_lowercase
# libuv's codes and descriptions, which Node's file-system errors carry: "CODE: description, syscall 'path'".
# An error number libuv does not know is "UNKNOWN: unknown error" in Node.
DESCRIPTIONS = {
    "EPERM": "operation not permitted", "ENOENT": "no such file or directory", "ESRCH": "no such process",
    "EINTR": "interrupted system call", "EIO": "i/o error", "ENXIO": "no such device or address",
    "E2BIG": "argument list too long", "ENOEXEC": "exec format error", "EBADF": "bad file descriptor",
    "ENOMEM": "not enough memory", "EACCES": "permission denied", "EFAULT": "bad address in system call argument",
    "EBUSY": "resource busy or locked", "EEXIST": "file already exists", "EXDEV": "cross-device link not permitted",
    "ENODEV": "no such device", "ENOTDIR": "not a directory", "EISDIR": "illegal operation on a directory",
    "EINVAL": "invalid argument", "ENFILE": "file table overflow", "EMFILE": "too many open files",
    "ENOTTY": "inappropriate ioctl for device", "ETXTBSY": "text file is busy", "EFBIG": "file too large",
    "ENOSPC": "no space left on device", "ESPIPE": "invalid seek", "EROFS": "read-only file system",
    "EMLINK": "too many links", "EPIPE": "broken pipe", "ERANGE": "result too large",
    "EAGAIN": "resource temporarily unavailable", "EALREADY": "connection already in progress",
    "ENOTSOCK": "socket operation on non-socket", "EDESTADDRREQ": "destination address required",
    "EMSGSIZE": "message too long", "EPROTOTYPE": "protocol wrong type for socket",
    "ENOPROTOOPT": "protocol not available", "EPROTONOSUPPORT": "protocol not supported",
    "ESOCKTNOSUPPORT": "socket type not supported", "ENOTSUP": "operation not supported on socket",
    "EAFNOSUPPORT": "address family not supported", "EADDRINUSE": "address already in use",
    "EADDRNOTAVAIL": "address not available", "ENETDOWN": "network is down", "ENETUNREACH": "network is unreachable",
    "ECONNABORTED": "software caused connection abort", "ECONNRESET": "connection reset by peer",
    "ENOBUFS": "no buffer space available", "EISCONN": "socket is already connected",
    "ENOTCONN": "socket is not connected", "ESHUTDOWN": "cannot send after transport endpoint shutdown",
    "ETIMEDOUT": "connection timed out", "ECONNREFUSED": "connection refused",
    "ELOOP": "too many symbolic links encountered", "ENAMETOOLONG": "name too long", "EHOSTDOWN": "host is down",
    "EHOSTUNREACH": "host is unreachable", "ENOTEMPTY": "directory not empty", "ENOSYS": "function not implemented",
    "EFTYPE": "inappropriate file type or format", "EOVERFLOW": "value too large for defined data type",
    "ECANCELED": "operation canceled", "EILSEQ": "illegal byte sequence", "ENODATA": "no data available",
    "EPROTO": "protocol error",
}


class FileError(ScenarioError):
    """A file-system error with Node's message; `code` is its error code, as Node's `error.code`."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def fs_error(error: OSError, syscall: str, path: str | None = None) -> FileError:
    """A file-system error with Node's text."""
    code = errno.errorcode.get(error.errno or 0, "UNKNOWN")
    if code not in DESCRIPTIONS:
        code = "UNKNOWN"
    description = DESCRIPTIONS.get(code, "unknown error")
    return FileError(f"{code}: {description}, {syscall}" + (f" '{path}'" if path is not None else ""), code)


def tmpdir() -> str:
    """os.tmpdir(): TMPDIR, TMP or TEMP, else /tmp, without one trailing slash."""
    path = os.environ.get("TMPDIR") or os.environ.get("TMP") or os.environ.get("TEMP") or "/tmp"
    return path[:-1] if len(path) > 1 and path.endswith("/") else path


def mkdtemp(prefix: str) -> str:
    """fs.mkdtemp: the prefix and six letters or digits, created with mode 0700."""
    while True:
        path = prefix + "".join(secrets.choice(LETTERS) for _ in range(6))
        try:
            os.mkdir(path, 0o700)
            return path
        except FileExistsError:
            continue
        except OSError as error:
            raise fs_error(error, "mkdtemp", path) from None


def realpath(path: str) -> str:
    """fs.promises.realpath: the C library's realpath(3), which libuv calls. On macOS it also gives each name the
    case it has on disk (`/PRIVATE/TMP` is `/private/tmp`), which os.path.realpath does not."""
    try:
        function = ctypes.CDLL(None, use_errno=True).realpath
    except (OSError, AttributeError):
        return os.path.realpath(path, strict=True)
    function.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    function.restype = ctypes.c_char_p
    found = function(os.fsencode(path), ctypes.create_string_buffer(4096))
    if found is None:
        number = ctypes.get_errno()
        raise fs_error(OSError(number, os.strerror(number)), "realpath", path)
    return os.fsdecode(found)


def write_file(path: str, text: str, mode: int) -> None:
    """fs.writeFile: the mode applies only when the file is created."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, mode)
    except OSError as error:
        raise fs_error(error, "open", path) from None
    try:
        data = memoryview(text.encode("utf-8", "surrogatepass"))
        while data:
            data = data[os.write(fd, data):]
    except OSError as error:
        raise fs_error(error, "write") from None
    finally:
        os.close(fd)


type _Done = Callable[[FileError | None], None]


def remove(path: str) -> None:
    """fs.rm(path, { recursive: true, force: true }) as Node 24 runs it: an lstat (a missing path is fine), then
    Node's rimraf. A folder is removed with rmdir first, so an empty one goes even when it cannot be read; only a
    folder that is not empty is listed (in byte order, as libuv lists it) and its entries removed before rmdir
    again. Links are not followed. Node removes the entries of a folder concurrently and reports the first
    failure; here the file operations run one at a time, in the order Node starts them."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise fs_error(error, "lstat", path) from None
    pending: deque[Callable[[], None]] = deque()

    def operation(syscall: str, target: str, function: Callable[[], Any],
                  then: Callable[[FileError | None, Any], None]) -> None:
        def run() -> None:
            try:
                result = function()
            except OSError as error:
                then(fs_error(error, syscall, target), None)
                return
            then(None, result)
        pending.append(run)

    def rimraf(target: str, done: _Done) -> None:
        entry(target, lambda failure: done(None if failure is not None and failure.code == "ENOENT" else failure))

    def entry(target: str, done: _Done) -> None:
        def unlinked(failure: FileError | None, _: Any) -> None:
            if failure is not None and failure.code == "ENOENT":
                done(None)
            elif failure is not None and failure.code in ("EISDIR", "EPERM"):
                folder(target, failure, done)
            else:
                done(failure)

        def found(failure: FileError | None, status: Any) -> None:
            if failure is not None and failure.code == "ENOENT":
                done(None)
            elif failure is None and stat.S_ISDIR(status.st_mode):
                folder(target, None, done)
            else:
                operation("unlink", target, lambda: os.unlink(target), unlinked)
        operation("lstat", target, lambda: os.lstat(target), found)

    def folder(target: str, original: FileError | None, done: _Done) -> None:
        def removed(failure: FileError | None, _: Any) -> None:
            if failure is not None and failure.code in ("ENOTEMPTY", "EEXIST", "EPERM"):
                children(target, done)
            elif failure is not None and failure.code == "ENOTDIR":
                done(original)
            else:
                done(failure)
        operation("rmdir", target, lambda: os.rmdir(target), removed)

    def children(target: str, done: _Done) -> None:
        def listed(failure: FileError | None, names: Any) -> None:
            if failure is not None:
                done(failure)
                return
            left, failed = [len(names)], [False]

            def removed(failure: FileError | None) -> None:
                if failed[0]:
                    return
                if failure is not None:
                    failed[0] = True
                    done(failure)
                    return
                left[0] -= 1
                if left[0] == 0:
                    operation("rmdir", target, lambda: os.rmdir(target), lambda failure, _: done(failure))
            if not names:
                operation("rmdir", target, lambda: os.rmdir(target), lambda failure, _: done(failure))
            for name in names:
                rimraf(target + "/" + os.fsdecode(name), removed)
        operation("scandir", target, lambda: sorted(os.listdir(os.fsencode(target))), listed)

    outcome: list[FileError | None] = []
    rimraf(path, outcome.append)
    while pending:
        pending.popleft()()
    if outcome and outcome[0] is not None:
        raise outcome[0]


# What scenarios started and is still running. Node's event loop kept the runner alive until each had ended (an
# interaction at the latest when its time limit killed it), also when a scenario that failed left one behind.
INTERACTIONS: list[Interaction] = []
CALLS: set[asyncio.Future[None]] = set()


@dataclass
class JsonResult:
    process: JSObject
    result: JSObject


class ScenarioHome:
    def __init__(self, home: str, scenario: str, command: list[str], timeout_ms: float, signal_: Abort | None) -> None:
        self.home = home
        self.id = scenario
        self.command = command
        self.timeout_ms = timeout_ms
        self.signal = signal_
        self.tool = join(home, "tool")
        self.tool_path = join(self.tool, "vendor-tool")
        # The interpreter's folder comes first, as Node's did; scenarios never judge PATH.
        self.env: dict[str, str] = {
            "HOME": home, "PATH": f"{dirname(os.path.realpath(sys.executable))}:{dirname(command[0])}:/usr/bin:/bin",
            "LANG": "C", "TMPDIR": home, "TMP": home, "TEMP": home, "ARBOL_TEST_TIME_SCALE": "100",
        }

    @classmethod
    async def create(cls, scenario: str, command: list[str], timeout_ms: float | None = None,
                     signal_: Abort | None = None) -> ScenarioHome:
        home = realpath(mkdtemp(join(tmpdir(), f"arbol-conformance-{scenario}-")))
        fixture = cls(home, scenario, command, 15000 if timeout_ms is None else timeout_ms, signal_)
        try:
            for folder in (fixture.tool, join(home, ".arbol")):
                try:
                    os.mkdir(folder, 0o700)
                except OSError as error:
                    raise fs_error(error, "mkdir", folder) from None
            words = " ".join(shell_quote(word) for word in [*command, "dev", "stand-in", fixture.tool, "--"])
            write_file(fixture.tool_path, f'#!/bin/sh\nexec {words} "$@"\n', 0o700)
            await fixture.part("supported")
            return fixture
        except BaseException:
            await fixture.dispose()
            raise

    async def part(self, part: str, missing: bool = False) -> None:
        write_file(join(self.tool, "scenario"), f"{self.id} {part}\n", 0o600)
        settings = text_of(stringify({"toolPath": join(self.tool, "nonexistent") if missing else self.tool_path}))
        # Both contract filenames are installed before discovering the Driver with info.
        for driver in ("claude", "codex"):
            write_file(join(self.home, ".arbol", f"arbol-{driver}-driver.json"), settings, 0o600)

    async def call(self, args: list[str]) -> JSObject:
        running = asyncio.get_running_loop().create_future()
        CALLS.add(running)
        try:
            return await invoke(self.command, args, cwd=self.home, env=self.env, timeout_ms=self.timeout_ms,
                                signal_=self.signal)
        finally:
            CALLS.discard(running)
            running.set_result(None)

    def start(self, args: list[str]) -> Interaction:
        interaction = Interaction(self.command, args, cwd=self.home, env=self.env, timeout_ms=self.timeout_ms)
        INTERACTIONS[:] = [*(started for started in INTERACTIONS if not started.done.done()), interaction]
        return interaction

    async def settings(self, value: dict[str, Any]) -> None:
        text = text_of(stringify({"toolPath": self.tool_path, **value}))
        for driver in ("claude", "codex"):
            write_file(join(self.home, ".arbol", f"arbol-{driver}-driver.json"), text, 0o600)

    async def json(self, args: list[str]) -> JsonResult:
        process = await self.call(args)
        try:
            parsed = parse(process["stdout"])
        except JSONError:
            raise Mismatch(f"Invalid JSON from {' '.join(args)}", "one JSON result", process) from None
        return JsonResult(process, object_(f"Result of {' '.join(args)}", parsed))

    async def received(self) -> list[JSObject]:
        path = join(self.tool, "received.jsonl")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        except FileNotFoundError:
            return []
        except OSError as error:
            raise fs_error(error, "open", path) from None
        chunks: list[bytes] = []
        try:
            while chunk := os.read(fd, 65536):
                chunks.append(chunk)
        except OSError as error:  # a folder is opened and refused on reading, as in Node
            raise fs_error(error, "read") from None
        finally:
            os.close(fd)
        content = b"".join(chunks).decode("utf-8", "replace")
        records: list[JSObject] = []
        for index, line in enumerate(trim(content).split("\n")):
            if not line:
                continue
            try:
                parsed = parse(line)
            except JSONError:
                raise Mismatch(f"received.jsonl line {index + 1}", "a JSON record", line) from None
            entry = object_("Stand-in record", parsed)
            for field in ("scenario", "part", "workingDirectory"):
                check(f"Stand-in {field}", isinstance(entry[field], str), "a string", entry[field])
            for field in ("arguments", "environment"):
                value = entry[field]
                check(f"Stand-in {field}", isinstance(value, list) and all(isinstance(item, str) for item in value),
                      "an array of strings", value)
            object_("Stand-in checks", entry["checks"])
            records.append(entry)
        return records

    def contains(self, path: str) -> bool:
        rel = relative(self.home, path)
        return is_absolute(path) and rel != ".." and not rel.startswith("../") and not is_absolute(rel)

    async def dispose(self) -> None:
        remove(self.home)


@dataclass
class Scenario:
    id: str
    title: str
    scope: str
    covers: list[str]
    run: Callable[[ScenarioHome], Awaitable[None]]
