"""Read process identity from ps alone, independently of inherited shell settings."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import Any

MONTHS = {name:index for index,name in enumerate(
    ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], 1)}


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError('A timestamp must be an absolute ISO time.')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('A timestamp must include its timezone.')
    return parsed.astimezone(UTC)


def parse_start(value: str) -> datetime:
    try:
        _day, month, date, clock, year = value.split()
        hour, minute, second = map(int, clock.split(':'))
        return datetime(int(year),MONTHS[month],int(date),hour,minute,second,tzinfo=UTC)
    except (ValueError, KeyError):
        raise ValueError('ps returned an unreadable process start time.') from None


def started_at(pid: int) -> datetime | None:
    result = subprocess.run(['/bin/ps','-o','lstart=','-p',str(pid)], capture_output=True, text=True, check=False,
                            env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','TZ':'UTC'}, timeout=5)
    if result.returncode:
        if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
            return None
        raise ValueError('The recorded process could not be checked.')
    return parse_start(result.stdout)


def process_alive(process: dict[str, Any]) -> bool:
    pid = process.get('pid')
    if type(pid) is not int or pid < 1:
        raise ValueError('A process needs a positive integer PID.')
    recorded = timestamp(process.get('startedAt'))
    actual = started_at(pid)
    return actual is not None and abs((actual-recorded).total_seconds()) <= 2
