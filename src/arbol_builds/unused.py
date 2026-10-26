"""Opt-in unused-Build pruning (BLD-0.26, BLD-D23/D24)."""

import json
import math
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Locations
from .launcher import BUILD_PATTERN, Record, code_name, js_integer, milliseconds, read_records, refuse_constant
from .mutation import with_mutation_lock
from .pruning import retained_roots
from .root_launcher import root_default_record
from .roots import roots_folder
from .service import build_details, components_in, prune_protections, remove_build_payload


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


def old_enough(registry: str, record: Record, clock: float, days: float) -> bool:
    if record["status"] == "building" or record.get("prunedAt") or record.get("lockedAt"):
        return False
    value = build_details(registry,record)["unusedSince"]
    stamp = milliseconds(value) if isinstance(value,str) else None
    return stamp is not None and clock-stamp > days*86_400_000


def prune_unused(paths: Locations, *, now_ms: float | None = None) -> list[dict[str, Any]]:
    days = read_days()
    names = components_in(paths.registry)
    if days is None:
        return [{"component":component,"pruned":[]} for component in names]
    usage = usage_snapshot(paths)
    clock = time.time()*1000 if now_ms is None else now_ms
    if usage.unavailable:
        print("Cannot obtain complete manager listings for Roots: "+", ".join(usage.unavailable)+
              "; retained every Trunk, Driver and classifier Build.",file=sys.stderr)
    results: list[dict[str, Any]] = []
    for component in names:
        row: dict[str, Any] = {"component":component,"pruned":[]}
        dynamic = component.startswith("arbol-trunk/") or shared_runtime(component)
        if dynamic and usage.unavailable:
            row["unavailableRoots"] = list(usage.unavailable)
        if shared_runtime(component) and usage.roots_with_exchanges:
            row["rootsWithExchanges"] = list(usage.roots_with_exchanges)
        if (dynamic and usage.unavailable) or (shared_runtime(component) and usage.roots_with_exchanges):
            results.append(row)
            continue

        def change(component: str = component, row: dict[str, Any] = row) -> None:
            records = read_records(paths.registry,component)
            working = [record for record in records if record["status"] == "working" and not record.get("prunedAt")]
            protected = prune_protections(paths.registry,component,working,usage.roots)
            protected.update(usage.trunks.get(component,set()))
            for record in records:
                if record["build"] in protected or not old_enough(paths.registry,record,clock,days):
                    continue
                def still_old(record: Record = record) -> bool:
                    return old_enough(paths.registry,record,clock,days)
                outcome = remove_build_payload(paths.registry,record,still_old)
                if outcome == "pruned":
                    row["pruned"].append(record["build"])
                elif outcome in ("inUse","unverifiable"):
                    row.setdefault(outcome,[]).append(record["build"])
        with_mutation_lock(os.path.join(paths.registry,component),change)
        results.append(row)
    return results


UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z", re.ASCII)
MANAGER_SECONDS = 30


@dataclass(frozen=True)
class Usage:
    roots: dict[str, Record | None]
    trunks: dict[str, set[str]]
    unavailable: list[str]
    roots_with_exchanges: list[str]


def absolute_time(value: object) -> bool:
    return isinstance(value, str) and milliseconds(value) is not None


def listed_exchanges(value: object, root: str, manager: Record) -> list[Record]:
    if (not isinstance(value, dict) or value.get("root") != root or value.get("rootBuild") != manager["build"]
            or value.get("rootPackageVersion") != manager["packageVersion"]
            or not isinstance(value.get("exchanges"), list) or value.get("unreadable") != []):
        raise ValueError("The Root did not return a complete matching manager listing.")
    result: list[Record] = []
    for item in value["exchanges"]:
        if (not isinstance(item, dict) or item.get("root") != root
                or not isinstance(item.get("exchange"), str) or not UUID.fullmatch(item["exchange"])
                or not isinstance(item.get("chat"), str) or not UUID.fullmatch(item["chat"])
                or not isinstance(item.get("trunk"), str) or not code_name(item["trunk"])
                or not isinstance(item.get("build"), str)
                or not (item["build"] == "0" or BUILD_PATTERN.fullmatch(item["build"]))
                or not isinstance(item.get("process"), dict) or not isinstance(item.get("signsOfLife"), dict)
                or not isinstance(item.get("state"), str) or not item["state"]):
            raise ValueError("An Exchange has unreadable protection fields.")
        process, life = item["process"], item["signsOfLife"]
        if (type(process.get("pid")) is not int or process["pid"] < 1
                or not absolute_time(process.get("startedAt")) or type(process.get("alive")) is not bool
                or type(life.get("heartbeat")) is not int or life["heartbeat"] < 0
                or not isinstance(life.get("waitingFor"), str) or not life["waitingFor"]
                or not absolute_time(life.get("since"))):
            raise ValueError("An Exchange has unreadable process/signs-of-life fields.")
        if "end" in item:
            end = item["end"]
            if (not isinstance(end, dict) or not isinstance(end.get("state"), str) or not end["state"]
                    or not absolute_time(end.get("at"))):
                raise ValueError("An Exchange has an unreadable end.")
            if "error" in end and (not isinstance(end["error"], dict)
                                  or not isinstance(end["error"].get("code"), str)
                                  or not isinstance(end["error"].get("message"), str)):
                raise ValueError("An Exchange has an unreadable end error.")
        result.append(item)
    return result


def usage_snapshot(paths: Locations) -> Usage:
    roots = retained_roots(roots_folder())
    managers = read_records(paths.registry, "arbol-root") if roots else []
    protected: dict[str, set[str]] = {}
    unavailable: list[str] = []
    active: list[str] = []
    for name, record in roots.items():
        manager = root_default_record(paths.registry, managers, name)
        if record is None or manager is None:
            unavailable.append(name)
            continue
        try:
            answer = subprocess.run([os.path.join(paths.bin,"arbol-root"),"--root",name,"list"],
                                    env={**os.environ,"PATH":os.path.abspath(paths.bin)+os.pathsep+
                                         os.environ.get("PATH",os.defpath)},
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=MANAGER_SECONDS, check=False)
            if answer.returncode:
                raise ValueError("The manager refused or failed.")
            value = json.loads(answer.stdout.decode("utf-8"), parse_constant=refuse_constant, parse_int=js_integer)
            entries = listed_exchanges(value,name,manager)
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
            unavailable.append(name)
            continue
        if entries:
            active.append(name)
        for entry in entries:
            protected.setdefault("arbol-trunk/"+entry["trunk"],set()).add(entry["build"])
    return Usage(roots,protected,unavailable,active)


def shared_runtime(component: str) -> bool:
    return component.endswith("-driver") or component == "arbol-classifier"
