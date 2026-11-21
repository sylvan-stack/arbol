"""Opt-in unused-Build pruning (BLD-0.26, BLD-D23/D24)."""

import hashlib
import json
import math
import os
import plistlib
import re
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arbol_installation.admission import Admission, AdmissionRefusal, runtime_folder
from arbol_installation.paths import build_payload_directory, installation_root

from .config import Locations
from .driver_admission import sync_directory
from .driver_payload import retention_status
from .launcher import (
    BUILD_PATTERN,
    RESERVED_CODE_NAMES,
    Record,
    backend_fits,
    code_name,
    default_record,
    executable_entry,
    js_integer,
    milliseconds,
    read_records,
    refuse_constant,
    trunk,
)
from .mutation import with_mutation_lock
from .schema_state import SchemaState, read_schema
from .service import (
    browser_document,
    browser_file,
    browser_file_digest,
    browser_lock,
    browser_private_directory,
    browser_release_number,
    browser_release_receipt,
    browser_sha,
    browser_support,
    build_details,
    components_in,
    installed_browser_selection,
    prune_protections,
    remove_build_payload,
)


def read_days(home: Path | None = None) -> float | None:
    path = installation_root(home) / 'arbol-builds.json'
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
    try:
        with Admission(runtime_folder()).permit("normal"):
            return prune_admitted(paths, names, days, now_ms)
    except AdmissionRefusal:
        return [{"component": component, "pruned": [], "maintenance": True} for component in names]


def _browser_document(path: Path, maximum: int = 16384) -> Record | None:
    try:
        return browser_document(path, maximum)[0]
    except FileNotFoundError:
        return None


def _profile_claims(home: Path, profile: Path, instance: str) -> list[Record]:
    profile_hash = hashlib.sha256(os.fsencode(profile)).hexdigest()
    history = profile.parent.parent / "exit-evidence" / profile_hash
    runtime = Path(f"/private/tmp/ab-{os.getuid()}") / profile_hash[:32]
    claims: list[Record] = []
    for path in (runtime / "claim.json", history / "previous-claim.json", history / "current-attempt.json"):
        claim = _browser_document(path)
        if claim is None:
            continue
        claims.append(claim)
        terminal = claim.get("terminal")
        if terminal is not None:
            request = claim.get("request", "")
            if (not isinstance(request, str) or not re.fullmatch(r"req_[A-Za-z0-9_-]{22}", request)
                    or not isinstance(terminal, dict) or not browser_sha(terminal.get("digest"))
                    or not isinstance(terminal.get("path"), str)):
                raise ValueError("Browser Claim has uncertain terminal evidence.")
            evidence = Path(terminal["path"])
            if evidence.parent != history / request or evidence.name not in ("activation.json", "terminal.json", "unused.json"):
                raise ValueError("Browser Claim has an unexpected evidence location.")
            if evidence.name == "unused.json":
                witness, witness_digest = browser_document(evidence, 262144)
                prior = witness.get("priorDataClaim")
                if terminal["digest"] != witness_digest or "priorDataClaim" not in witness or (
                    prior is not None and (not isinstance(prior, dict) or prior.get("phase") != "closed")
                ):
                    raise ValueError("Browser Claim has uncertain previous data-writer evidence.")
                if prior is not None:
                    claims.append(prior)
    for claim in claims:
        if (claim.get("format") != 1 or claim.get("profile") != str(profile)
                or claim.get("profileInstance") != instance or claim.get("profilePathHash") != profile_hash
                or not browser_release_number(claim.get("build")) or not browser_sha(claim.get("productDigest"))):
            raise ValueError("Browser Claim differs from its profile.")
        build = claim["build"]
        root = home / "Applications/Arbol Browser/.mounted/arbol-browser" / build
        uses = browser_support(home) / "uses" / build
        # Existing preview evidence may use an isolated Build. Only the exact
        # installed path and corresponding original guard name an installed image.
        if (claim.get("buildRoot") == str(root)) != (claim.get("buildGuard") == str(uses)):
            raise ValueError("Browser Claim has an inconsistent installed Build path.")
    return claims


@contextmanager
def _browser_references(home: Path) -> Iterator[set[str]]:
    state = home / ".arbol/browser"
    if not os.path.lexists(state):
        yield set()
        return
    profiles = state / "profiles"
    browser_private_directory(profiles)
    with ExitStack() as locks:
        locks.enter_context(browser_lock(state / "registry.lock"))
        referenced: set[str] = set()
        for profile in sorted(profiles.iterdir()):
            if re.fullmatch(r"\.creating-[0-9a-f]{32}", profile.name):
                continue
            if re.fullmatch(r"\.deleting-[0-9a-f]{32}", profile.name):
                browser_private_directory(profile)
                if sorted(item.name for item in profile.iterdir()) != ["owner.lock"]:
                    raise ValueError("Browser profile deletion still has private data.")
                with browser_file(profile / "owner.lock"):
                    continue  # The original lock-only tombstone is not a live profile.
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", profile.name):
                raise ValueError("Browser profile registry has unfinished or unknown state.")
            metadata, _ = browser_document(profile / "profile.json")
            instance = metadata.get("instance")
            if metadata.get("id") != profile.name or not isinstance(instance, str) or not re.fullmatch(r"prf_[A-Za-z0-9_-]{22}", instance):
                raise ValueError("Invalid Browser profile identity.")
            locks.enter_context(browser_lock(profile / "owner.lock"))
            claims = _profile_claims(home, profile, instance)
            installed = [claim for claim in claims if claim.get("buildRoot") ==
                         str(home / "Applications/Arbol Browser/.mounted/arbol-browser" / claim["build"])]
            referenced.update(claim["build"] for claim in installed)
            marker = _browser_document(profile / "engine.json")
            if marker is not None:
                reader = marker.get("requiredReader")
                if marker.get("profileInstance") != instance or not isinstance(reader, str):
                    raise ValueError("Invalid Browser data-writer marker.")
                if reader.startswith("host-production:") and not any(
                    reader == f"host-production:1:{claim['productDigest']}" for claim in installed
                ):
                    raise ValueError("Browser data-writer Build cannot be verified.")
        yield referenced


def _image_command(program: str, *arguments: str) -> bytes:
    return subprocess.run([program, *arguments], env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                          stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=12).stdout


def _unmount_browser_image(image: Path, mount: Path) -> None:
    if not os.path.lexists(mount):
        return
    browser_private_directory(mount)
    info = plistlib.loads(_image_command("/usr/bin/hdiutil", "info", "-plist"))
    matches = [(row, entity) for row in info["images"] for entity in row.get("system-entities", [])
               if entity.get("mount-point") == str(mount)]
    if not matches and not any(mount.iterdir()):
        return
    if len(matches) != 1:
        raise ValueError("Historical Browser mount has an uncertain image mapping.")
    row, entity = matches[0]
    device = entity.get("dev-entry")
    if (row.get("image-path") != str(image) or row.get("owner-uid") != os.getuid()
            or row.get("image-type") != "UDIF read-only" or row.get("writeable") is not False
            or not isinstance(device, str) or not re.fullmatch(r"/dev/disk[0-9]+s[0-9]+", device)):
        raise ValueError("Historical Browser mount has the wrong backing image.")
    volume = plistlib.loads(_image_command("/usr/sbin/diskutil", "info", "-plist", device))
    node = Path(device).lstat()
    if (volume.get("MountPoint") != str(mount) or volume.get("FilesystemType") != "apfs"
            or volume.get("WritableVolume") is not False or not stat.S_ISBLK(node.st_mode)
            or node.st_rdev != mount.lstat().st_dev):
        raise ValueError("Historical Browser volume is not the guarded read-only mount.")
    _image_command("/usr/bin/hdiutil", "detach", device)
    if any(mount.iterdir()):
        raise ValueError("Historical Browser mount is still populated.")


def prune_browser_releases(home: Path, selected_build: str, selected_sha: str) -> dict[str, Any]:
    """Only retire exact inactive installed images after a fresh, guarded reference census."""
    support = browser_support(home)
    uses, releases = support / "uses", support / "releases"
    result: dict[str, Any] = {"pruned": [], "retained": [], "inUse": []}
    with browser_lock(support / "selection.lock"):
        selected = installed_browser_selection(home)
        if selected is None or (selected["build"], selected["imageSha256"]) != (selected_build, selected_sha):
            raise ValueError("Installed Browser selection changed before maintenance.")
        browser_private_directory(releases)
        for path in sorted(releases.glob("*.json")):
            build = path.stem
            if build == selected_build or not browser_release_number(build):
                continue
            guard = uses / build
            try:
                with browser_lock(guard, retiring=True), _browser_references(home) as references:
                    receipt = browser_release_receipt(home, build)
                    image = support / "images" / f"{build}.dmg"
                    mounted = home / "Applications/Arbol Browser/.mounted/arbol-browser" / build / "app"
                    original = os.path.lexists(image)
                    if original and browser_file_digest(image, 1073741824) != receipt["imageSha256"]:
                        raise ValueError("Historical Browser image differs from its verified receipt.")
                    if build in references and not original:
                        raise ValueError("A referenced historical Browser image is missing.")
                    _unmount_browser_image(image, mounted)
                    if build in references:
                        result["retained"].append(build)
                        continue
                    if os.path.lexists(mounted.parent):
                        browser_private_directory(mounted.parent)
                        if os.path.lexists(mounted):
                            mounted.rmdir()
                        mounted.parent.rmdir()
                        sync_directory(mounted.parent.parent)
                    if original:
                        image.unlink()
                        sync_directory(image.parent)
                    # Finish metadata only after all actual payloads are absent.
                    if os.path.lexists(image) or os.path.lexists(mounted.parent):
                        raise ValueError("Historical Browser payload retirement was incomplete.")
                    (uses / f"{build}.mount").unlink(missing_ok=True)
                    path.unlink()
                    guard.unlink()  # descriptor remains held until finally
                    sync_directory(releases)
                    sync_directory(uses)
                    result["pruned"].append(build)
            except BlockingIOError:
                result["inUse"].append(build)
    return result


def prune_admitted(paths: Locations, names: list[str], days: float, now_ms: float | None) -> list[dict[str, Any]]:
    schema = read_schema()
    usage = usage_snapshot(paths, schema)
    clock = time.time()*1000 if now_ms is None else now_ms
    if usage.unavailable:
        print("The installed Exchange listing is unavailable or unreadable. Retained Trunks, Drivers and classifiers.",
              file=sys.stderr)
    results: list[dict[str, Any]] = []
    for component in names:
        row: dict[str, Any] = {"component":component,"pruned":[]}
        dynamic = trunk(component) or shared_runtime(component)
        if (component == "arbol" or trunk(component)) and schema.pair is None:
            row["schemaStatus"] = schema.status
            results.append(row)
            continue
        if dynamic and usage.unavailable:
            row["runtimeUnavailable"] = True
        if shared_runtime(component) and usage.active:
            row["activeExchanges"] = True
        if (dynamic and usage.unavailable) or (shared_runtime(component) and usage.active):
            results.append(row)
            continue

        def change(component: str = component, row: dict[str, Any] = row, dynamic: bool = dynamic) -> None:
            records = read_records(paths.registry,component)
            working = [record for record in records if record["status"] == "working" and not record.get("prunedAt")]
            protected = prune_protections(paths.registry, component, working, schema=schema)
            protected.update(usage.trunks.get(component,set()))
            for record in records:
                if record["build"] in protected or not old_enough(paths.registry,record,clock,days):
                    continue
                retained = retention_status(paths.registry, component, record["build"])
                if retained is not None:
                    row.setdefault(retained, []).append(record["build"])
                    continue
                def still_old(record: Record = record) -> bool:
                    if not old_enough(paths.registry, record, clock, days):
                        return False
                    return not dynamic or not usage_snapshot(paths, schema).retains(component, record["build"])
                outcome = remove_build_payload(paths.registry,record,still_old)
                if outcome == "pruned":
                    row["pruned"].append(record["build"])
                elif outcome in ("inUse","unverifiable"):
                    row.setdefault(outcome,[]).append(record["build"])
        with_mutation_lock(os.path.join(paths.registry,component),change)
        results.append(row)
    return results


UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z", re.ASCII)
LIST_SECONDS = 30


@dataclass(frozen=True)
class Usage:
    trunks: dict[str, set[str]]
    unavailable: bool = False
    active: bool = False

    def retains(self, component: str, build: str) -> bool:
        return (self.unavailable or (self.active and shared_runtime(component))
                or build in self.trunks.get(component, set()))


def absolute_time(value: object) -> bool:
    return isinstance(value, str) and milliseconds(value) is not None


def listed_trunk(item: Record) -> bool:
    """A Trunk code name, or a reserved one with Build 0: an imported Exchange, which no Trunk Build protects
    (IMP-0.18, IMP-D15)."""
    return code_name(item["trunk"]) or (item["trunk"] in RESERVED_CODE_NAMES and item.get("build") == "0")


def listed_exchanges(value: object) -> list[Record]:
    if (not isinstance(value, dict) or "error" in value
            or not isinstance(value.get("exchanges"), list) or value.get("unreadable") != []):
        raise ValueError("The installation did not return a complete Exchange listing.")
    result: list[Record] = []
    seen: set[str] = set()
    for item in value["exchanges"]:
        if (not isinstance(item, dict) or type(item.get("exchangeFormat")) is not int or item["exchangeFormat"] != 1
                or not isinstance(item.get("exchange"), str) or not UUID.fullmatch(item["exchange"])
                or not isinstance(item.get("chat"), str) or not UUID.fullmatch(item["chat"])
                or not isinstance(item.get("trunk"), str) or not listed_trunk(item)
                or not isinstance(item.get("build"), str)
                or not (item["build"] == "0" or BUILD_PATTERN.fullmatch(item["build"]))
                or not isinstance(item.get("process"), dict) or not isinstance(item.get("signsOfLife"), dict)
                or item.get("state") not in ("accepting", "running", "ending", "unsaved", "interrupted")
                or item["exchange"] in seen):
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
        seen.add(item["exchange"])
        result.append(item)
    return result


def usage_snapshot(paths: Locations, schema: SchemaState) -> Usage:
    records = read_records(paths.registry, "arbol")
    backend = default_record(paths.registry, [record for record in records if backend_fits(record, schema.pair)])
    if backend is None:
        return Usage({}, unavailable=True)
    folder = build_payload_directory(paths.registry, "arbol", backend["build"])
    executable = executable_entry(str(folder), "bin/arbol-exchanges")
    if executable is None:
        return Usage({}, unavailable=True)
    try:
        command = [executable, "list"]
        if Path(paths.bin).resolve() != (Path.home() / ".local/bin").resolve():
            command += ["--bin-dir", os.path.abspath(paths.bin)]
        answer = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=LIST_SECONDS, check=False)
        if answer.returncode:
            raise ValueError("The installation refused to list Exchanges.")
        value = json.loads(answer.stdout, parse_constant=refuse_constant, parse_int=js_integer)
        entries = listed_exchanges(value)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return Usage({}, unavailable=True)
    protected: dict[str, set[str]] = {}
    for entry in entries:
        protected.setdefault("arbol-trunk/" + entry["trunk"], set()).add(entry["build"])
    return Usage(protected, active=bool(entries))


def shared_runtime(component: str) -> bool:
    return component.endswith("-driver") or component == "arbol-classifier"
