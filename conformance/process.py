"""Starting a Driver: one call that is waited for, or an interaction that is talked to (DRV-5, Interface).

Each Driver starts as Node started it: in a session and process group of its own, with every signal at
its default and none blocked, standard input from /dev/null (or a socket for an interaction), standard
output and error on Unix sockets with 64 KiB buffers, no other descriptor, and exactly the environment
given. When the Driver's main process ends, its whole group gets SIGKILL, so that descendants holding its
output end as well.
"""

from __future__ import annotations

import asyncio
import codecs
import errno
import os
import signal
import socket
import threading
from collections.abc import Callable
from typing import Any

from .check import Mismatch, ScenarioError
from .inspect import inspect
from .js import JSArray, JSObject, len16, number_text, parse, stringify, text_of, utf8_length, well_formed

LIMIT = 4 * 1024 * 1024
READ = 65536
# libuv gives both ends of each socketpair 64 KiB send and receive buffers, where macOS's default is 8 KiB.
BUFFER = 65536
ASYNC_SPAWN_ERRORS = ("ENOENT", "EACCES", "EAGAIN", "EMFILE", "ENFILE")
DEFAULT_SIGNALS = [number for number in signal.valid_signals() if number not in (signal.SIGKILL, signal.SIGSTOP)]
# The signal names Node knows (os.constants.signals); it has no name for SIGEMT.
SIGNALS = {name: int(number) for name, number in signal.Signals.__members__.items() if name != "SIGEMT"}
SIGNAL_NAMES = {int(number): number.name for number in signal.Signals if number.name != "SIGEMT"}


class Abort:
    """An AbortSignal: listeners run at once, in order, when the run is stopped."""

    def __init__(self) -> None:
        self.aborted = False
        self._listeners: list[Callable[[], None]] = []

    def add(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def remove(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def abort(self) -> None:
        if self.aborted:
            return
        self.aborted = True
        for listener in list(self._listeners):
            self._listeners.remove(listener)
            listener()

    def throw_if_aborted(self) -> None:
        if self.aborted:
            raise ScenarioError("This operation was aborted")


class SpawnFailed(Exception):
    """A start that Node reported later, as an 'error' event: `spawn <program> <CODE>`."""


def _code(error: OSError) -> str:
    return errno.errorcode.get(error.errno or 0, "UNKNOWN")


def _signal(name: str) -> int:
    """The number of a signal name, or Node's ERR_UNKNOWN_SIGNAL text."""
    if name not in SIGNALS:
        raise ScenarioError(f"Unknown signal: {name}")
    return SIGNALS[name]


def _without_nul(value: str, name: str, reason: str = "must be a string without null bytes") -> None:
    """Node's ERR_INVALID_ARG_VALUE for a NUL in a spawn argument, thrown before anything starts."""
    if "\0" in value:
        shown = inspect(value)
        if len16(shown) > 128:
            shown = shown.encode("utf-16-le", "surrogatepass")[:256].decode("utf-16-le", "surrogatepass") + "..."
        kind = "property" if "." in name else "argument"
        raise ScenarioError(f"The {kind} '{name}' {reason}. Received {shown}")


def _inherited() -> list[int]:
    """Descriptors above 2 that the runner would pass on; libuv starts a child with none of them."""
    try:
        names = os.listdir("/dev/fd")
    except OSError:
        return []
    found: list[int] = []
    for name in names:
        try:
            if int(name) > 2 and os.get_inheritable(int(name)):
                found.append(int(name))
        except (OSError, ValueError):
            pass
    return found


class _Spawned:
    def __init__(self, pid: int, sockets: dict[str, socket.socket]) -> None:
        self.pid = pid
        self.sockets = sockets


def _spawn(command: list[str], args: list[str], cwd: str, env: dict[str, str], interactive: bool) -> _Spawned:
    """posix_spawn in a new session, every signal at its default and none blocked; raises SpawnFailed or
    a ScenarioError `spawn <CODE>` as Node did."""
    program = command[0]
    _without_nul(program, "file")
    for index, word in enumerate([*command[1:], *args]):
        _without_nul(word, f"args[{index}]")
    _without_nul(cwd, "options.cwd", "must be a string, Uint8Array, or URL without null bytes")
    for key, value in env.items():
        _without_nul(key, f"options.env['{key}']")
        _without_nul(value, f"options.env['{key}']")
    pairs = {name: socket.socketpair() for name in (("stdin", "stdout", "stderr") if interactive else ("stdout", "stderr"))}
    for pair in pairs.values():
        for end in pair:
            for option in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                try:
                    end.setsockopt(socket.SOL_SOCKET, option, BUFFER)
                except OSError:
                    pass  # the system's own size then
    actions: list[tuple[Any, ...]] = []
    if interactive:
        actions.append((os.POSIX_SPAWN_DUP2, pairs["stdin"][1].fileno(), 0))
    else:
        actions.append((os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0))
    actions.append((os.POSIX_SPAWN_DUP2, pairs["stdout"][1].fileno(), 1))
    actions.append((os.POSIX_SPAWN_DUP2, pairs["stderr"][1].fileno(), 2))
    actions.extend((os.POSIX_SPAWN_CLOSE, fd) for fd in _inherited())
    try:
        here = os.open(".", os.O_RDONLY)
    except OSError:
        here = -1
    try:
        try:
            os.chdir(cwd)
            pid = os.posix_spawn(program, [program, *command[1:], *args], env, file_actions=actions, setsid=True,
                                 setsigdef=DEFAULT_SIGNALS, setsigmask=set())
        except OSError as error:
            code = _code(error)
            for parent, child in pairs.values():
                parent.close()
                child.close()
            if code in ASYNC_SPAWN_ERRORS:
                raise SpawnFailed(f"spawn {program} {code}") from None
            raise ScenarioError(f"spawn {code}") from None
        except ValueError as error:
            for parent, child in pairs.values():
                parent.close()
                child.close()
            raise ScenarioError(str(error)) from None
    finally:
        if here >= 0:
            os.fchdir(here)
            os.close(here)
    sockets: dict[str, socket.socket] = {}
    for name, (parent, child) in pairs.items():
        child.close()
        parent.setblocking(False)
        sockets[name] = parent
    return _Spawned(pid, sockets)


def _wait(pid: int, loop: asyncio.AbstractEventLoop, done: Callable[[int | None, str | None], None]) -> None:
    def waiter() -> None:
        while True:
            try:
                _, status = os.waitpid(pid, 0)
                break
            except ChildProcessError:
                status = 0
                break
            except InterruptedError:
                continue
        result: tuple[int | None, str | None] = (os.WEXITSTATUS(status), None)
        if os.WIFSIGNALED(status) and os.WTERMSIG(status) in SIGNAL_NAMES:
            result = (None, SIGNAL_NAMES[os.WTERMSIG(status)])
        elif os.WIFSIGNALED(status):
            result = (0, None)  # a signal Node cannot name (SIGEMT) reads as status 0
        try:
            loop.call_soon_threadsafe(done, *result)
        except RuntimeError:
            pass  # the loop has closed

    threading.Thread(target=waiter, daemon=True).start()


class _Reader:
    """One output stream read 64 KiB at a time and decoded as UTF-8 with U+FFFD, as Node's setEncoding did.

    While paused, Node goes on reading until 64 KiB of decoded text (UTF-16 units) waits, and the stream
    ends only after that text has been taken. A destroyed stream drops what waits and ends at once.
    """

    def __init__(self, sock: socket.socket, on_text: Callable[[str], None], on_end: Callable[[], None]) -> None:
        self.sock = sock
        self.on_text = on_text
        self.on_end = on_end
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.paused = False
        self.destroyed = False
        self.held: list[str] = []
        self.held_length = 0
        self.resumed = asyncio.Event()
        self.ended = False
        self.task = asyncio.get_running_loop().create_task(self._run())
        self.task.add_done_callback(lambda _: self._end())

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            if self.paused and self.held_length >= READ:
                await self._resumed()
                continue
            try:
                # Node's reads keep up with the Driver, so a paused stream stops at 64 KiB, not beyond it.
                data = await loop.sock_recv(self.sock, READ - self.held_length if self.paused else READ)
            except (OSError, ValueError):
                data = b""
            if not data:
                break
            self._push(self.decoder.decode(data))
        self._push(self.decoder.decode(b"", final=True))
        while self.held:
            await self._resumed()

    async def _resumed(self) -> None:
        self.resumed.clear()
        await self.resumed.wait()

    def _push(self, text: str) -> None:
        if not text:
            return
        if self.paused:
            self.held.append(text)
            self.held_length += len16(text)
        else:
            self.on_text(text)

    def _end(self) -> None:
        if not self.ended:
            self.ended = True
            try:
                self.sock.close()
            except OSError:
                pass
            self.on_end()

    def pause(self) -> None:
        if not self.destroyed:
            self.paused = True

    def resume(self) -> None:
        if self.paused and not self.destroyed:
            self.paused = False
            held, self.held, self.held_length = self.held, [], 0
            for text in held:
                self.on_text(text)
            self.resumed.set()

    def destroy(self) -> None:
        self.destroyed = True
        self.held, self.held_length = [], 0
        self.task.cancel()


def _kill_group(pid: int | None, number: int) -> None:
    if pid:
        os.killpg(pid, number)


async def invoke(command: list[str], args: list[str], *, cwd: str, env: dict[str, str], timeout_ms: float,
                 signal_: Abort | None = None) -> JSObject:
    """Run the Driver once and wait for it: its exit status or signal, standard output and error."""
    loop = asyncio.get_running_loop()
    result: asyncio.Future[JSObject] = loop.create_future()
    state: dict[str, Any] = {"stdout": "", "stderr": "", "bytes": 0, "failure": None, "status": None,
                             "signal": None, "exited": False, "ends": 0}
    arguments = JSArray(args)
    pid: int | None = None

    def kill_group() -> None:
        try:
            _kill_group(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as error:
            if state["failure"] is None:
                state["failure"] = ScenarioError(f"kill {_code(error)}")

    def stop(error: BaseException) -> None:
        if state["failure"] is None:
            state["failure"] = error
        kill_group()

    def abort() -> None:
        stop(Mismatch("Driver invocation was stopped", "a completed invocation",
                      JSObject(args=arguments, stdout=state["stdout"], stderr=state["stderr"])))

    def timed_out() -> None:
        stop(Mismatch("Driver invocation timed out", f"completion within {number_text(float(timeout_ms))} ms",
                      JSObject(args=arguments, stdout=state["stdout"], stderr=state["stderr"])))

    def close() -> None:
        timer.cancel()
        if signal_ is not None:
            signal_.remove(abort)
        if result.done():
            return
        if state["failure"] is not None:
            result.set_exception(state["failure"])
        else:
            result.set_result(JSObject(status=state["status"], signal=state["signal"], stdout=state["stdout"],
                                       stderr=state["stderr"]))

    def collect(text: str, stream: str) -> None:
        state["bytes"] += utf8_length(text)
        if state["bytes"] > LIMIT:
            stop(Mismatch("Driver output exceeded the runner limit", "at most 4 MiB per invocation",
                          JSObject(args=arguments, bytes=state["bytes"])))
            return
        state[stream] += text

    def ended() -> None:
        state["ends"] += 1
        if state["exited"] and state["ends"] == 2:
            close()

    def exited(status: int | None, name: str | None) -> None:
        state["exited"], state["status"], state["signal"] = True, status, name
        kill_group()  # end descendants even when the Driver exits without closing their inherited output
        if state["ends"] == 2:
            close()

    def listen() -> None:
        if signal_ is not None:
            signal_.add(abort)
            if signal_.aborted:
                abort()

    try:
        spawned = _spawn(command, args, cwd, env, False)
    except SpawnFailed as error:
        timer = loop.call_later(timeout_ms / 1000, timed_out)
        listen()  # Node reported the error a tick later, after a run already stopped had been stopped
        if state["failure"] is None:
            state["failure"] = Mismatch("Driver could not start", "an executable Driver",
                                        JSObject(args=arguments, message=str(error)))
        loop.call_soon(close)
        return await result
    pid = spawned.pid
    timer = loop.call_later(timeout_ms / 1000, timed_out)
    _Reader(spawned.sockets["stdout"], lambda text: collect(text, "stdout"), ended)
    _Reader(spawned.sockets["stderr"], lambda text: collect(text, "stderr"), ended)
    _wait(pid, loop, exited)
    listen()
    return await result


class _Stdout:
    def __init__(self, reader: _Reader) -> None:
        self._reader = reader

    def pause(self) -> None:
        self._reader.pause()

    def resume(self) -> None:
        self._reader.resume()

    def destroy(self) -> None:
        self._reader.destroy()


class _Stdin:
    """Writes in order, never blocking the caller; errors such as a closed Driver are ignored."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._task = asyncio.get_running_loop().create_task(self._run())
        # The socket closes once writing has ended, after its pending operation has been withdrawn.
        self._task.add_done_callback(lambda _: self._sock.close())

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                data = await self._queue.get()
                if data is None:
                    self._sock.shutdown(socket.SHUT_WR)
                    return
                await loop.sock_sendall(self._sock, data)
        except (OSError, ValueError, asyncio.CancelledError):
            pass

    def write(self, text: str) -> None:
        self._queue.put_nowait(well_formed(text).encode("utf-8"))

    def end(self) -> None:
        self._queue.put_nowait(None)

    def close(self) -> None:
        """Node's destroy: what is still waiting to be written is dropped."""
        self._task.cancel()


class Child:
    """The parts of Node's ChildProcess the scenarios use."""

    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        self.exited = False
        self.stdout: _Stdout
        self.stdin: _Stdin

    def kill(self, name: str = "SIGTERM") -> None:
        """Signal the Driver's main process only, not its group; nothing once it has been reaped."""
        number = _signal(name)
        if self.pid and not self.exited:
            try:
                os.kill(self.pid, number)
            except OSError:
                pass


class Interaction:
    """A Driver that is talked to: lines it writes, as JSON, while it runs (sign-in steps, runs)."""

    def __init__(self, command: list[str], args: list[str], *, cwd: str, env: dict[str, str], timeout_ms: float) -> None:
        loop = asyncio.get_running_loop()
        self.args = JSArray(args)
        self.lines: JSArray = JSArray()
        self.stdout = ""
        self.stderr = ""
        self.closed = False
        self._rest = ""
        self._stdout_bytes = 0
        self._stderr_bytes = 0
        self._ends = 0
        self._status: int | None = None
        self._signal: str | None = None
        self.done: asyncio.Future[JSObject] = loop.create_future()
        self.done.add_done_callback(lambda future: future.exception() if not future.cancelled() else None)
        try:
            spawned = _spawn(command, args, cwd, env, True)
        except SpawnFailed as error:
            self.child = Child(None)
            self._timer = loop.call_later(timeout_ms / 1000, lambda: None)
            failure = ScenarioError(str(error))

            def failed() -> None:
                self.done.set_exception(failure)
                self.closed = True
                self._timer.cancel()

            loop.call_soon(failed)
            self.child.stdin = _NullStdin()  # type: ignore[assignment]
            self.child.stdout = _NullStdout()  # type: ignore[assignment]
            return
        self.child = Child(spawned.pid)
        self._timer = loop.call_later(timeout_ms / 1000, lambda: self._kill(signal.SIGKILL))
        self.child.stdout = _Stdout(_Reader(spawned.sockets["stdout"], self._out, self._ended))
        _Reader(spawned.sockets["stderr"], self._err, self._ended)
        self.child.stdin = _Stdin(spawned.sockets["stdin"])
        _wait(spawned.pid, loop, self._exited)

    def _kill(self, number: int) -> None:
        try:
            _kill_group(self.child.pid, number)
        except OSError:
            pass  # gone

    def _out(self, text: str) -> None:
        self.stdout += text
        self._stdout_bytes += utf8_length(text)  # decoded text has whole characters: the sum is the whole length
        *complete, self._rest = (self._rest + text).split("\n")
        for line in complete:
            try:
                self.lines.append(parse(line))
            except Exception:  # catch {} took any error
                self.lines.append(JSObject(invalidLine=line))
        if self._stdout_bytes > LIMIT:
            self._kill(signal.SIGKILL)

    def _err(self, text: str) -> None:
        self.stderr += text
        self._stderr_bytes += utf8_length(text)
        if self._stderr_bytes > LIMIT:
            self._kill(signal.SIGKILL)

    def _exited(self, status: int | None, name: str | None) -> None:
        self.child.exited = True
        self.child.stdin.close()  # Node destroys standard input when the main process has exited
        self._status, self._signal = status, name
        self._kill(signal.SIGKILL)
        self.child.stdout.resume()  # and resumes a paused standard output, so that it can end (flushStdio)
        self._close()

    def _ended(self) -> None:
        self._ends += 1
        self._close()

    def _close(self) -> None:
        if self.child.exited and self._ends == 2 and not self.done.done():
            self.closed = True
            self._timer.cancel()
            self.child.stdin.close()
            self.done.set_result(JSObject(status=self._status, signal=self._signal, stdout=self.stdout,
                                          stderr=self.stderr))

    def send(self, value: Any) -> None:
        self.child.stdin.write(text_of(stringify(value)) + "\n")

    def stop(self, name: str = "SIGTERM") -> None:
        if name in SIGNALS:  # an unknown name was thrown and ignored
            self._kill(SIGNALS[name])

    async def step(self, name: str, timeout: float = 5000) -> JSObject:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout / 1000
        while True:
            for value in self.lines:
                if isinstance(value, dict) and "step" in value and value["step"] == name and isinstance(value["step"], str):
                    return value if isinstance(value, JSObject) else JSObject(value)
            if self.closed or loop.time() >= deadline:
                raise Mismatch(f"Sign-in did not return {name}", name,
                               JSObject(args=self.args, lines=self.lines, stdout=self.stdout, stderr=self.stderr))
            await asyncio.sleep(0.01)

    async def dispose(self) -> None:
        self._kill(signal.SIGKILL)
        try:
            await self.done
        except Exception:
            pass


class _NullStdin:
    def write(self, text: str) -> None:
        pass

    def end(self) -> None:
        pass

    def close(self) -> None:
        pass


class _NullStdout:
    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    def destroy(self) -> None:
        pass
