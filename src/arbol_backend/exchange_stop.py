"""One verified append-only stop request, then record observation and bounded escalation."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .exchange_admission import GENERATION_ENV, Admission, Lease
from .exchange_clock import awake
from .exchange_context import Context, Refusal
from .exchange_groups import force_group
from .exchange_launcher import Reply
from .exchange_listing import lookup, open_catalogue, project, read_record
from .exchange_settle import settle_after_stop

ENDS = {'completed', 'failed', 'cancelled', 'interrupted'}


@dataclass(frozen=True)
class Observed:
    process: dict[str, Any]
    alive: bool
    end: str | None


def read_exchange(context: Context, exchange: str) -> Observed | None:
    view = lookup(context, exchange)
    if view is None:
        return None
    return Observed(view['process'], view['process']['alive'], view.get('end', {}).get('state'))


def pending(context: Context, exchange: str) -> bool:
    place = context.exchanges / ('.'+exchange+'.new')
    try:
        metadata = place.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError('The publishing name is not a real directory.')
        return True
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as error:
        raise Refusal('runtime_unavailable', f'Cannot verify {place}: {error}') from error


def same_process(observed: Observed, expected: Observed) -> None:
    if any(observed.process[key] != expected.process[key] for key in ['pid', 'startedAt']):
        raise Refusal('runtime_unavailable', 'The recorded process changed while stop was running.')


def append_stop(context: Context, exchange: str, expected: Observed) -> None:
    catalogue = directory = descriptor = None
    try:
        catalogue = open_catalogue(context)
        if catalogue is None:
            return
        directory = os.open(exchange, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=catalogue)
        record = read_record(directory, '.')
        view = project(record, exchange)
        same_process(Observed(record['process'], view['process']['alive'], record.get('end', {}).get('state')), expected)
        if not view['process']['alive'] or 'end' in record:
            return
        descriptor = os.open('control', os.O_RDWR | os.O_APPEND | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError('control is not a private regular file.')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with os.fdopen(os.dup(descriptor), 'rb') as control:
            for raw in control:
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(event, dict) and event.get('type') == 'stop' and raw.endswith(b'\n'):
                    return
        named = os.stat(exchange, dir_fd=catalogue, follow_symlinks=False)
        opened = os.fstat(directory)
        if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError('The Exchange folder changed before its control write.')
        line = b'{"type":"stop"}\n'
        if os.write(descriptor, line) != len(line):
            raise ValueError('The stop line could not be written completely; it was not retried.')
    except FileNotFoundError as error:
        if read_exchange(context, exchange) is not None:
            raise Refusal('runtime_unavailable', f'Cannot append to existing control: {error}') from error
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        raise Refusal('runtime_unavailable', f'Cannot append a stop line: {error}') from error
    finally:
        for fd in [descriptor, directory, catalogue]:
            if fd is not None:
                os.close(fd)


def force_end(context: Context, exchange: str, expected: Observed,
              clock: Callable[[], float], pause: Callable[[float], None]) -> bool:
    observed = read_exchange(context, exchange)
    if observed is None:
        return False
    same_process(observed, expected)
    if not observed.alive or observed.end is not None:
        return False
    return force_group(observed.process, clock, pause)


def result(exchange: str, ended: str, forced: bool,
           settling: dict[str, Any] | None = None) -> Reply:
    document: dict[str, Any] = {'exchange': exchange, 'ended': ended, 'forced': forced}
    if settling is not None:
        document['settling'] = settling
    return Reply(document)


def save_ended(context: Context, exchange: str, observed: Observed, forced: bool, lease: Lease) -> Reply:
    saved = settle_after_stop(context, exchange, lease)
    state = saved.get('settled')
    ended = 'saved' if state == 'none' else state if isinstance(state, str) and state in ENDS else observed.end or 'interrupted'
    return result(exchange, ended, forced, saved)


def stop(context: Context, exchange: str, force: bool = False, *,
         clock: Callable[[], float] = awake, pause: Callable[[float], None] = time.sleep) -> Reply:
    admission = Admission(context.identity.folder)
    with admission.lease("controlled", generation=os.environ.get(GENERATION_ENV)) as lease:
        return stop_admitted(context, exchange, force, lease, clock=clock, pause=pause)


def stop_admitted(context: Context, exchange: str, force: bool, lease: Lease, *,
                  clock: Callable[[], float], pause: Callable[[float], None]) -> Reply:
    observed = read_exchange(context, exchange)
    deadline = clock()+15
    while observed is None and pending(context, exchange) and clock() < deadline:
        pause(min(0.1, max(0, deadline-clock())))
        observed = read_exchange(context, exchange)
    if observed is None:
        return result(exchange, 'none', False)
    if not observed.alive:
        return save_ended(context, exchange, observed, False, lease)
    if observed.end is not None:
        return result(exchange, observed.end, False)
    expected = observed
    if not force:
        append_stop(context, exchange, expected)
        deadline = clock()+20
        while True:
            observed = read_exchange(context, exchange)
            if observed is None:
                return result(exchange, 'saved', False)
            same_process(observed, expected)
            if not observed.alive:
                return save_ended(context, exchange, observed, False, lease)
            if observed.end is not None:
                return result(exchange, observed.end, False)
            if clock() >= deadline:
                break
            pause(min(0.1, max(0, deadline-clock())))
    forced = force_end(context, exchange, expected, clock, pause)
    observed = read_exchange(context, exchange)
    if observed is None:
        return save_ended(context, exchange, expected, True, lease) if forced else result(exchange, 'saved', False)
    same_process(observed, expected)
    if not forced and observed.end is not None:
        return result(exchange, observed.end, False)
    if not forced and observed.alive and observed.end is None:
        raise Refusal('runtime_unavailable', 'The Exchange still lives but its group could not be ended.')
    return save_ended(context, exchange, observed, forced, lease)
