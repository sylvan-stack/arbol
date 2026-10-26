"""Opt-in unused-Build pruning (BLD-0.26, BLD-D23/D24)."""

import json
import math
import os
import stat
from pathlib import Path
from typing import Any

from .config import Locations
from .launcher import js_integer, refuse_constant
from .service import components_in


def read_days(home: Path | None = None) -> float | None:
    path = (home or Path.home()) / '.arbol/arbol-builds.json'
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError(f'Cannot read unused-Build settings at {path}.') from error
    try:
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('The unused-Build settings must be a regular JSON file.')
            value = json.load(stream, parse_constant=refuse_constant, parse_int=js_integer)
        if not isinstance(value, dict):
            raise ValueError('The unused-Build settings must hold an object.')
        if 'removeUnusedAfterDays' not in value:
            return None
        days = value['removeUnusedAfterDays']
        if isinstance(days, bool) or not isinstance(days, (int,float)) or not math.isfinite(days) or days <= 0:
            raise ValueError('removeUnusedAfterDays must be a positive finite number.')
        return float(days)
    except (OSError, ValueError, OverflowError) as error:
        raise ValueError(f'Invalid unused-Build settings at {path}: {error}') from error


def prune_unused(paths: Locations) -> list[dict[str, Any]]:
    days = read_days()
    if days is not None:
        raise ValueError('Configured unused removal is not implemented yet.')
    return [{'component':component, 'pruned':[]} for component in components_in(paths.registry)]
