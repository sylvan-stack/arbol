"""The command line of the Driver conformance suite: `arbol-conformance --driver <command> [--only <ids>]`."""

from __future__ import annotations

import asyncio
import errno
import os
import select
import signal
import sys
from typing import Any, TextIO

from .check import message_of
from .command import resolve_command
from .harness import CALLS, INTERACTIONS
from .js import trim, well_formed
from .process import Abort, Interaction
from .runner import run_suite, scenarios, select_scenarios

USAGE = ("Usage: arbol-conformance --driver <command> [--only <scenario ids>]\n"
         "Available: {available}. Quote commands with fixed arguments and paths with spaces.\n"
         "Exit status: 0 passed; 1 scenario failed; 2 invalid input or stopped.")


def usage() -> str:
    return USAGE.format(available=", ".join(scenario.id for scenario in scenarios()))


def write(stream: TextIO | None, text: str) -> None:
    """Text as UTF-8, a lone surrogate as U+FFFD, whatever the locale: as Node wrote it.

    What a non-blocking pipe cannot take yet waits until it can, as in Node's write queue. A failed write (a
    reader that has gone: EPIPE) ends the runner with status 1, as the uncaught 'error' event of Node's stream
    did. A standard stream that was closed at start takes the text and drops it, as the /dev/null that Node
    opened in its place did.
    """
    if stream is None:
        return
    try:
        descriptor = stream.fileno()
    except (OSError, ValueError, AttributeError):  # not a file, such as a test's stream
        stream.write(well_formed(text))
        return
    data = memoryview(well_formed(text).encode("utf-8"))
    try:
        stream.flush()
        while data:
            try:
                data = data[os.write(descriptor, data):]
            except BlockingIOError:
                select.select([], [descriptor], [])
    except OSError as error:
        os.dup2(os.open(os.devnull, os.O_WRONLY), descriptor)  # nothing more for Python to flush at exit
        if descriptor != 2:
            write(sys.stderr, f"Error: write {errno.errorcode.get(error.errno or 0, 'UNKNOWN')}\n")
        raise SystemExit(1) from None


async def main(args: list[str]) -> int:
    cancellation = Abort()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(number, cancellation.abort)
    try:
        if len(args) == 1 and args[0] == "--help":
            write(sys.stdout, usage() + "\n")
            return 0
        values: dict[str, str] = {}
        index = 0
        while index < len(args):
            arg = args[index]
            name, equals, given = arg.partition("=")
            if name not in ("--driver", "--only"):
                raise ValueError(f"Unknown suite option: {arg}")
            if equals:
                value: str | None = given
            else:
                index += 1
                value = args[index] if index < len(args) else None
            if value is None or not trim(value) or value.startswith("--") or name in values:
                raise ValueError(f"Give {name} exactly one value.")
            values[name] = value
            index += 1
        if not values.get("--driver"):
            raise ValueError("Give --driver a command.")
        selected = select_scenarios(values.get("--only"))
        command = resolve_command(values["--driver"])
        return await run_suite(command, selected, signal_=cancellation)
    except Exception as error:
        write(sys.stderr, f"{message_of(error)}\n{usage()}\n")
        return 2
    finally:
        for number in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(number)
            signal.signal(number, signal.SIG_DFL)  # Node's default action again, not a KeyboardInterrupt


def _keeps_running(interaction: Interaction, loop: asyncio.AbstractEventLoop) -> bool:
    """Whether a handle of this interaction still kept Node's event loop alive: its time limit, its process, or
    its standard output while it was read (a paused one no longer counted)."""
    if interaction.done.done():
        return False
    timer: Any = getattr(interaction, "_timer", None)
    reader: Any = getattr(interaction.child.stdout, "_reader", None)
    timing = timer is not None and not timer.cancelled() and timer.when() > loop.time()
    return timing or not interaction.child.exited or not getattr(reader, "paused", False)


async def _running_work() -> None:
    """Node exited only when nothing kept its event loop alive. A scenario that failed may have left an
    interaction or a call running: Node waited for it to end, an interaction at the latest when its time limit
    killed its process group, so the runner does not exit before that either and leaves no Driver running."""
    loop = asyncio.get_running_loop()
    while True:
        running: list[asyncio.Future[Any]] = [*CALLS]
        running += [interaction.done for interaction in INTERACTIONS if _keeps_running(interaction, loop)]
        if not running:
            return
        await asyncio.wait(running, timeout=0.01, return_when=asyncio.FIRST_COMPLETED)


async def _run(args: list[str]) -> int:
    status = await main(args)
    await _running_work()
    return status


def _signals_as_node() -> None:
    """The signal state Node gave itself at start: a signal that the parent left ignored has its default action
    again (SIGPIPE and SIGXFSZ stay ignored), and none is blocked. So `nohup`, an ignored SIGCHLD or a blocked
    SIGINT change the runner no more than they changed Node."""
    for number in signal.valid_signals():
        if number in (signal.SIGKILL, signal.SIGSTOP, signal.SIGPIPE, signal.SIGXFSZ):
            continue
        try:
            if signal.getsignal(number) == signal.SIG_IGN:
                signal.signal(number, signal.SIG_DFL)
        except (OSError, ValueError):
            pass
    signal.pthread_sigmask(signal.SIG_SETMASK, [])


def entry() -> None:
    _signals_as_node()
    # JavaScript reads numbers of any length; Python refuses integer text over 4300 digits unless told otherwise.
    sys.set_int_max_str_digits(0)
    # Arguments as Node read them: UTF-8, with bytes that are not UTF-8 as U+FFFD.
    args = [arg.encode("utf-8", "surrogateescape").decode("utf-8", "replace") for arg in sys.argv[1:]]
    sys.exit(asyncio.run(_run(args)))
