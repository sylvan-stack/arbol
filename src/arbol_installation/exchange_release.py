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

RECEIPT = "exchange-release.json"
MAX_RECEIPT = 32 * 1024 * 1024
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


def writer_version(lease: Lease, component: str, build: str, payload: Path) -> int:
    """Return the selected version only for the exact receipt, Build and payload under this lease."""
    try:
        lease.require()
        if lease.state.release is None:
            raise ValueError("The admission has no release.")
        with directory(lease.runtime) as folder:
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
                        or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)):
                    raise ValueError("Release receipt changed while reading.")
            finally:
                os.close(fd)
        if hashlib.sha256(raw).hexdigest() != lease.state.release:
            raise ValueError("Release receipt does not match admission.")
        receipt = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (not isinstance(receipt, dict) or type(receipt.get("format")) is not int or receipt["format"] != 1
                or receipt.get("kind") != "current" or not isinstance(receipt.get("builds"), list)):
            raise ValueError("Invalid release receipt.")
        matches = [item for item in receipt["builds"] if isinstance(item, dict)
                   and item.get("component") == component and item.get("build") == build]
        if len(matches) != 1 or not isinstance(matches[0].get("evidence"), dict):
            raise ValueError("Build is not uniquely selected.")
        expected = matches[0]["evidence"].get("installedFilesSha256")
        if not isinstance(expected, str) or DIGEST.fullmatch(expected) is None or payload_digest(payload) != expected:
            raise ValueError("Build payload differs from the release.")
        policy = receipt.get("exchangeCapabilities")
        if policy is None and "exchangeCapabilities" not in receipt:
            return 1  # A digest-matched historical receipt is explicit prior-release evidence.
        if (not isinstance(policy, dict) or set(policy) != {"readExchange", "trunks", "backend"}
                or policy["readExchange"] != [1, 2] or any(type(v) is not int for v in policy["readExchange"])
                or not isinstance(policy["trunks"], dict) or set(policy["trunks"]) != {"steady", "trivial"}
                or not isinstance(policy["backend"], dict)):
            raise ValueError("Invalid Exchange capabilities.")
        backend = policy["backend"]
        if (set(backend) != {"build", "readNotes", "writeNote"} or backend["readNotes"] != [1, 2]
                or any(type(v) is not int for v in backend["readNotes"])
                or type(backend["writeNote"]) is not int or backend["writeNote"] != 2):
            raise ValueError("Invalid note capabilities.")
        declarations = {"arbol": (backend.get("build"), backend["writeNote"])}
        for code, item in policy["trunks"].items():
            if (not isinstance(item, dict) or set(item) != {"build", "start"}
                    or type(item["start"]) is not int or item["start"] != 2):
                raise ValueError("Invalid Trunk capabilities.")
            declarations[f"arbol-trunk/{code}"] = (item.get("build"), item["start"])
        for name, (number, _) in declarations.items():
            found = [item for item in receipt["builds"] if isinstance(item, dict)
                     and item.get("component") == name and item.get("build") == number]
            if (not isinstance(number, str) or re.fullmatch(r"[1-9a-z][0-9a-z]*", number) is None
                    or len(found) != 1 or not isinstance(found[0].get("evidence"), dict)
                    or not isinstance(found[0]["evidence"].get("installedFilesSha256"), str)
                    or DIGEST.fullmatch(found[0]["evidence"]["installedFilesSha256"]) is None):
                raise ValueError("Capability does not identify one evidenced Build.")
        if component not in declarations or declarations[component][0] != build:
            raise ValueError("Build is not authorized to write.")
        lease.require()
        return declarations[component][1]
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise AdmissionRefusal("maintenance", "The Exchange release or selected payload could not be verified.") from None
