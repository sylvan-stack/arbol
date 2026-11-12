"""List the installation Exchange directory from verified records only."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
from typing import Any, NoReturn

from .exchange_admission import lock, private_dir
from .exchange_command import UUID
from .exchange_context import Context, Refusal
from .exchange_process import process_alive, timestamp
from .model import BUILD_ID

CODE = re.compile(r'[a-z][a-z0-9]{0,31}\Z', re.ASCII)


def not_json(value: str) -> NoReturn:
    raise ValueError(f'{value} is not a JSON number.')


def read_record(catalogue: int, name: str) -> dict[str, Any]:
    directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=catalogue)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('The Exchange folder is not private.')
        descriptor = os.open('record.json', os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(descriptor, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise ValueError('record.json is not a private regular file.')
            value = json.load(stream, parse_constant=not_json)
        if not isinstance(value, dict):
            raise ValueError('record.json does not hold an object.')
        return value
    finally:
        os.close(directory)


def project(record: dict[str, Any], name: str) -> dict[str, Any]:
    if (record.get('exchange') != name or not UUID.fullmatch(name)
            or type(record.get('exchangeFormat')) is not int or record['exchangeFormat'] != 1
            or not isinstance(record.get('chat'), str) or not UUID.fullmatch(record['chat'])
            or not isinstance(record.get('trunk'), str) or not CODE.fullmatch(record['trunk'])
            or not isinstance(record.get('build'), str)
            or not (record['build'] == '0' or BUILD_ID.fullmatch(record['build']))
            or not isinstance(record.get('process'), dict) or not isinstance(record.get('signsOfLife'), dict)):
        raise ValueError('The record does not supply this Exchange’s listing fields.')
    life = record['signsOfLife']
    if (type(life.get('heartbeat')) is not int or life['heartbeat'] < 0
            or not isinstance(life.get('waitingFor'), str) or not life['waitingFor']):
        raise ValueError('The record has unreadable signs of life.')
    timestamp(life.get('since'))
    if 'acceptedAt' in record:
        timestamp(record['acceptedAt'])
    end = record.get('end')
    if 'end' in record:
        if not isinstance(end, dict) or end.get('state') not in ('completed', 'failed', 'cancelled', 'interrupted'):
            raise ValueError('The record has an unreadable end.')
        timestamp(end.get('at'))
        if 'error' in end:
            error = end['error']
            if (not isinstance(error, dict) or not isinstance(error.get('code'), str)
                    or not isinstance(error.get('message'), str)):
                raise ValueError('The end has an unreadable error.')
    alive = process_alive(record['process'])
    if 'acceptedAt' not in record:
        state = 'accepting' if alive else 'interrupted'
    elif 'end' in record:
        state = 'ending' if alive else 'unsaved'
    else:
        state = 'running' if alive else 'interrupted'
    result = {key:record[key] for key in ['exchangeFormat', 'exchange', 'chat', 'trunk', 'build']}
    result['process'] = {key:record['process'][key] for key in ['pid','startedAt']}
    result['process']['alive'] = alive
    result['state'] = state
    result['signsOfLife'] = {key:life[key] for key in ['heartbeat','waitingFor','since']}
    if end is not None:
        result['end'] = {key:end[key] for key in ['state','at','error'] if key in end}
    return result


def open_catalogue(context: Context) -> int | None:
    try:
        descriptor = os.open(context.exchanges, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        raise Refusal('runtime_unavailable', 'Cannot open the installation Exchange directory.') from None
    info = os.fstat(descriptor)
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(descriptor)
        raise Refusal('runtime_unavailable', 'The installation Exchange directory is not private.')
    return descriptor


def lookup(context: Context, exchange: str) -> dict[str, Any] | None:
    catalogue = open_catalogue(context)
    if catalogue is None:
        return None
    try:
        try:
            record = read_record(catalogue, exchange)
            os.stat(exchange, dir_fd=catalogue, follow_symlinks=False)
            return project(record, exchange)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            try:
                os.stat(exchange, dir_fd=catalogue, follow_symlinks=False)
            except FileNotFoundError:
                return None
            except OSError:
                pass
            raise Refusal('runtime_unavailable', 'Cannot verify the Exchange record or process identity.') from None
    finally:
        os.close(catalogue)


def listing(context: Context, *, strict: bool = False) -> dict[str, Any]:
    readable: list[dict[str, Any]] = []
    unreadable: set[str] = set()
    catalogue = open_catalogue(context)
    if catalogue is None:
        return {'exchanges': [], 'unreadable': []}
    try:
        try:
            with os.scandir(catalogue) as entries:
                names = sorted((entry.name, entry.is_symlink(), entry.is_dir(follow_symlinks=False))
                               for entry in entries)
        except OSError:
            raise Refusal('runtime_unavailable', 'Cannot enumerate the installation Exchange directory.') from None
        for name, symlink, directory in names:
            if name.startswith('.'):
                if name.endswith(('.new', '.old')):
                    if not UUID.fullmatch(name[1:-4]):
                        raise Refusal('runtime_unavailable', 'The Exchange directory has an invalid staging name.')
                    try:
                        os.stat(name, dir_fd=catalogue, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    unreadable.add(name[1:-4])
                elif strict:
                    raise Refusal("runtime_unavailable", "The Exchange directory contains an unrecognized hidden entry.")
                continue
            if not UUID.fullmatch(name):
                raise Refusal('runtime_unavailable', 'The Exchange directory contains a name without an Exchange UUID.')
            if symlink or not directory:
                unreadable.add(name)
                continue
            try:
                record = read_record(catalogue, name)
                os.stat(name, dir_fd=catalogue, follow_symlinks=False)
                readable.append(project(record, name))
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                try:
                    os.stat(name, dir_fd=catalogue, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError:
                    pass
                unreadable.add(name)
    finally:
        os.close(catalogue)
    return {'exchanges': [row for row in readable if row['exchange'] not in unreadable],
            'unreadable': sorted(unreadable)}



def drained_inventory(context: Context) -> None:
    """Require the complete runtime catalogue to be empty with admission closed."""
    pending = listing(context, strict=True)
    if pending["exchanges"] or pending["unreadable"]:
        raise Refusal("maintenance_busy", "The runtime still has live, staged, unreadable or unsettled Exchanges.")
    starts = context.identity.folder / "exchange-starts"
    try:
        folder = os.open(starts, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return
    except OSError:
        raise Refusal("runtime_unavailable", "Cannot inspect unresolved Exchange starts.") from None
    try:
        private_dir(folder)
        for name in os.listdir(folder):
            if not UUID.fullmatch(name):
                raise ValueError("Unrecognized start lock name.")
            # A detached launcher inherits its UUID lock even before Trivial
            # has acquired its own admission permit. An unlocked marker is
            # harmless after the independent catalogue and SQL proofs pass.
            with lock(folder, name, fcntl.LOCK_EX):
                pass
    except BlockingIOError:
        raise Refusal("maintenance_busy", "An Exchange launch has not resolved.") from None
    except (OSError, ValueError):
        raise Refusal("runtime_unavailable", "Cannot verify the Exchange start inventory.") from None
    finally:
        os.close(folder)
