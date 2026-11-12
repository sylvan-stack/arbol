"""Verify a continuous private group identity through TERM/KILL, including orphaned children."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .exchange_context import Refusal
from .exchange_process import parse_start, process_alive, timestamp


def members(group: int) -> dict[int, datetime]:
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,pgid=,stat=,lstart='],
                            env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','TZ':'UTC'},
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=5)
    if result.returncode:
        raise ValueError('The recorded process group could not be checked.')
    found: dict[int, datetime] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        pid_text, group_text, state, began = line.split(maxsplit=3)
        pid, pgid = int(pid_text), int(group_text)
        if pgid == group and not state.startswith(('Z', 'X')):
            if pid < 1:
                raise ValueError('ps returned a nonpositive group member.')
            found[pid] = parse_start(began)
    return found


def continuing(group: int, known: dict[int, datetime]) -> dict[int, datetime]:
    current = members(group)
    if current and not any(current.get(pid) == began for pid, began in known.items()):
        raise ValueError('The nonempty group has no surviving verified member identity.')
    return current


def force_group(process: dict[str, Any], clock: Callable[[], float], pause: Callable[[float], None]) -> bool:
    forced = False
    try:
        if not process_alive(process):
            return False
        group = process['pid']
        if os.getpgid(group) != group or group == os.getpgrp():
            raise ValueError('The recorded process does not lead a separate group.')
        known = members(group)
        began = known.get(group)
        if began is None or abs((began-timestamp(process['startedAt'])).total_seconds()) > 2:
            raise ValueError('Cannot anchor the recorded group leader.')
        if not process_alive(process):
            return False
        if os.getpgid(group) != group:
            raise ValueError('The recorded leader changed its process group.')
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            return False
        forced = True
        for following in [signal.SIGKILL, None]:
            deadline = clock()+5
            while True:
                known = continuing(group, known)
                if not known:
                    return True
                if clock() >= deadline:
                    break
                pause(min(0.1, max(0, deadline-clock())))
            if following is None:
                raise Refusal('not_ended', 'Verified group members still live five awake seconds after SIGKILL.')
            try:
                os.killpg(group, following)
            except ProcessLookupError:
                return True
        raise AssertionError('The final deadline must return or refuse.')
    except Refusal:
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        code = 'not_ended' if forced else 'runtime_unavailable'
        raise Refusal(code, f'Cannot safely end the recorded process group: {error}') from error
