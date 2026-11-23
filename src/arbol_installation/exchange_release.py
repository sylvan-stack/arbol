"""Resolve Exchange writer capabilities from the locally retained release receipt."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from .admission import AdmissionRefusal, Lease, directory, private_file

RECEIPT = "exchange-authorization.json"
MAX_RECEIPT = 16384
MUTABLE = {"build.log", "last-start", ".use.lock"}
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate release field.")
        result[key] = value
    return result


def payload_digest(folder: Path) -> str:
    """Match the release recorder's installed payload tree digest."""
    folder = folder.resolve(strict=True)
    result: dict[str, object] = {}
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if name in MUTABLE:
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            link = os.readlink(path)
            if Path(link).is_absolute() or not path.resolve(strict=True).is_relative_to(folder):
                raise ValueError("Payload symlink leaves its Build.")
            result[name] = {"link": link}
        elif stat.S_ISREG(info.st_mode):
            with path.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            result[name] = {"sha256": checksum, "executable": info.st_mode & 0o111}
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("Payload contains a special file.")
    raw = (json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def checked(value: object, release: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != {"format", "release", "readExchange", "trunks", "backend"}
            or type(value["format"]) is not int or value["format"] != 1 or value["release"] != release
            or not isinstance(release, str) or DIGEST.fullmatch(release) is None
            or value["readExchange"] != [1, 2] or any(type(v) is not int for v in value["readExchange"])
            or not isinstance(value["trunks"], dict) or set(value["trunks"]) != {"steady", "trivial"}
            or not isinstance(value["backend"], dict)):
        raise ValueError("Invalid compact Exchange authorization.")
    backend = value["backend"]
    if (set(backend) != {"build", "payloadSha256", "readNotes", "writeNote"}
            or backend["readNotes"] != [1, 2] or any(type(v) is not int for v in backend["readNotes"])
            or type(backend["writeNote"]) is not int or backend["writeNote"] != 2):
        raise ValueError("Invalid note authorization.")
    for item in [backend, *value["trunks"].values()]:
        if (not isinstance(item, dict) or not isinstance(item.get("build"), str)
                or re.fullmatch(r"[1-9a-z][0-9a-z]*", item["build"]) is None
                or not isinstance(item.get("payloadSha256"), str)
                or DIGEST.fullmatch(item["payloadSha256"]) is None):
            raise ValueError("Invalid authorized payload.")
    for item in value["trunks"].values():
        if set(item) != {"build", "payloadSha256", "start"} or type(item["start"]) is not int or item["start"] != 2:
            raise ValueError("Invalid Trunk authorization.")
    return value


def authorization_from_release(release_record: dict[str, Any], release: str) -> bytes:
    """Derive canonical bytes only after the operator verifies the complete archived release."""
    if hashlib.sha256(canonical(release_record)).hexdigest() != release:
        raise ValueError("The verified release record does not match its digest.")
    policy = release_record["exchangeCapabilities"]
    builds = release_record["builds"]
    if (release_record.get("kind") != "current" or not isinstance(policy, dict)
            or set(policy) != {"readExchange", "trunks", "backend"} or not isinstance(builds, list)):
        raise ValueError("The verified release lacks Exchange capabilities.")
    def payload(component: str, build: object) -> str:
        matches = [item for item in builds if isinstance(item, dict) and item.get("component") == component
                   and item.get("build") == build]
        if len(matches) != 1 or not isinstance(matches[0].get("evidence"), dict):
            raise ValueError("The verified release does not identify one selected payload.")
        return matches[0]["evidence"]["installedFilesSha256"]
    backend = policy["backend"]
    trunks = policy["trunks"]
    value = {"format": 1, "release": release, "readExchange": policy["readExchange"],
             "trunks": {name: {**entry, "payloadSha256": payload(f"arbol-trunk/{name}", entry["build"])}
                        for name, entry in trunks.items()},
             "backend": {**backend, "payloadSha256": payload("arbol", backend["build"])}}
    return canonical(checked(value, release))


def verify_authorization(folder: int, commitment: str, release: str) -> dict[str, Any]:
    """Verify a compact authorization in the admission directory under the caller's locks."""
    if not isinstance(commitment, str) or DIGEST.fullmatch(commitment) is None:
        raise ValueError("Missing compact authorization commitment.")
    fd = os.open(RECEIPT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    try:
        before = os.fstat(fd)
        private_file(before)
        raw = bytearray()
        while len(raw) <= MAX_RECEIPT:
            chunk = os.read(fd, min(65536, MAX_RECEIPT + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        named = os.stat(RECEIPT, dir_fd=folder, follow_symlinks=False)
        if (len(raw) > MAX_RECEIPT or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                or hashlib.sha256(raw).hexdigest() != commitment):
            raise ValueError("Compact authorization changed or differs from admission.")
    finally:
        os.close(fd)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if canonical(value) != raw:
        raise ValueError("Compact authorization is not canonical.")
    return checked(value, release)


def writer_version(lease: Lease, component: str, build: str, payload: Path) -> int:
    """Check the exact successor Build and payload under its active admission lease."""
    try:
        lease.require()
        with directory(lease.runtime) as folder:
            value = verify_authorization(folder, lease.state.exchange_authorization, lease.state.release)
        if component == "arbol":
            role, version = value["backend"], value["backend"]["writeNote"]
        elif component in ("arbol-trunk/steady", "arbol-trunk/trivial"):
            role = value["trunks"][component.removeprefix("arbol-trunk/")]
            version = role["start"]
        else:
            raise ValueError("Unknown writer role.")
        if role["build"] != build or payload_digest(payload) != role["payloadSha256"]:
            raise ValueError("Writer Build or payload differs from authorization.")
        lease.require()
        return version
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise AdmissionRefusal("maintenance", "The Exchange authorization or selected payload could not be verified.") from None
