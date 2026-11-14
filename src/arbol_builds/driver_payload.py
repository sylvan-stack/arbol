"""Complete immutable Driver/provider payload identity (DRV-6.21).

Build lifecycle files live above driver-payload, never in its hash exclusions.
These declarations are not qualification or authority to touch Driver state.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .driver_admission import (
    COMPONENTS,
    LIMIT,
    MANIFEST_LIMIT,
    Authority,
    Object,
    canonical,
    decode,
    fields,
    natural,
    physical,
    private_directory,
    publish,
    read_bytes,
    refuse,
    sha256,
    valid_hash,
)

MANIFEST = "driver-payload-manifest.json"
DESCRIPTOR = "driver-capability.json"
SUBTREE = "driver-payload"
MAX_ENTRIES = 100000
BUILD = re.compile(r"[1-9a-f][0-9a-f]*\Z", re.ASCII)
SOURCE = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)


def relative(value: object) -> str:
    if not isinstance(value, str):
        refuse()
    try:
        raw = value.encode("utf-8", "strict")
    except UnicodeError:
        refuse()
    if (not raw or len(raw) > LIMIT or "\0" in value or "\\" in value or value.startswith("/")
            or any(part in ("", ".", "..") for part in value.split("/"))):
        refuse()
    return value


def contained(root: Path, name: object, *, regular: bool = False) -> Path:
    value = relative(name)
    path = root.joinpath(*PurePosixPath(value).parts)
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or resolved == root:
            refuse()
        if regular and not stat.S_ISREG(path.lstat().st_mode):
            refuse()
    except (OSError, RuntimeError):
        refuse()
    return path


def _file_hash(path: Path) -> tuple[int, str]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
            refuse()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(descriptor)
        named = path.lstat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode)
                or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)):
            refuse()
        return before.st_size, digest
    finally:
        os.close(descriptor)


def _acyclic_links(root: Path, rows: list[Object]) -> None:
    """Reject directory-link traversal cycles as well as symlink-chain cycles."""
    nodes = {"", *(row["path"] for row in rows if row["type"] == "directory")}
    edges: dict[str, set[str]] = {name: set() for name in nodes}
    for row in rows:
        target: str | None = None
        if row["type"] == "directory":
            target = row["path"]
        elif row["type"] == "symlink":
            resolved = (root / row["path"]).resolve(strict=True)
            if resolved.is_dir():
                target = resolved.relative_to(root).as_posix()
                if target == ".":
                    target = ""
        if target is not None:
            parent = PurePosixPath(row["path"]).parent.as_posix()
            parent = "" if parent == "." else parent
            if parent not in edges or target not in edges:
                refuse()
            edges[parent].add(target)
    degree = {name: 0 for name in nodes}
    for targets in edges.values():
        for name in targets:
            degree[name] += 1
    ready = [name for name, count in degree.items() if not count]
    visited = 0
    while ready:
        name = ready.pop()
        visited += 1
        for target in edges[name]:
            degree[target] -= 1
            if not degree[target]:
                ready.append(target)
    if visited != len(nodes):
        refuse()


def inventory(root: Path) -> list[Object]:
    private_directory(root)
    found: list[Object] = []
    collisions: set[str] = set()

    def visit(folder: Path) -> None:
        with os.scandir(folder) as entries:
            names = sorted((entry.name for entry in entries), key=lambda value: value.encode("utf-8", "strict"))
        for name in names:
            path = folder / name
            spelling = relative(path.relative_to(root).as_posix())
            if folder == root and name in (MANIFEST, DESCRIPTOR):
                continue
            normalized = unicodedata.normalize("NFC", spelling)
            if normalized in collisions or len(found) >= MAX_ENTRIES:
                refuse()
            collisions.add(normalized)
            info = path.lstat()
            if info.st_uid != os.getuid():
                refuse()
            row: Object = {"path": spelling, "mode": stat.S_IMODE(info.st_mode), "size": 0,
                           "sha256": None, "target": None}
            if stat.S_ISREG(info.st_mode):
                row["type"] = "file"
                row["size"], row["sha256"] = _file_hash(path)
            elif stat.S_ISDIR(info.st_mode):
                row["type"] = "directory"
            elif stat.S_ISLNK(info.st_mode):
                row["type"] = "symlink"
                target = os.readlink(path)
                try:
                    raw = target.encode("utf-8", "strict")
                    resolved = path.resolve(strict=True)
                except (UnicodeError, OSError, RuntimeError):
                    refuse()
                if not raw or len(raw) > LIMIT or os.path.isabs(target) or not resolved.is_relative_to(root):
                    refuse()
                row.update(size=len(raw), sha256=sha256(raw), target=target)
            else:
                refuse()
            found.append(row)
            if row["type"] == "directory":
                visit(path)

    visit(root)
    _acyclic_links(root, found)
    return sorted(found, key=lambda row: row["path"].encode("utf-8"))


def _manifest(raw: bytes, root: Path) -> Object:
    value = decode(raw, limit=MANIFEST_LIMIT)
    fields(value, "version kind files")
    if value["kind"] != "driver-payload-manifest" or not isinstance(value["files"], list):
        refuse()
    if len(value["files"]) > MAX_ENTRIES:
        refuse()
    prior = b""
    normalized: set[str] = set()
    for row in value["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "type", "mode", "size", "sha256", "target"}:
            refuse()
        name = relative(row["path"])
        encoded = name.encode("utf-8")
        norm = unicodedata.normalize("NFC", name)
        if (encoded <= prior or norm in normalized or name in (MANIFEST, DESCRIPTOR)
                or not natural(row["mode"]) or row["mode"] > 4095 or not natural(row["size"])):
            refuse()
        prior = encoded
        normalized.add(norm)
        kind = row["type"]
        if kind == "directory":
            if row["size"] != 0 or row["sha256"] is not None or row["target"] is not None:
                refuse()
        elif kind == "file":
            if not valid_hash(row["sha256"]) or row["target"] is not None:
                refuse()
        elif kind == "symlink":
            target = row["target"]
            if (not isinstance(target, str) or not target or os.path.isabs(target)
                    or not valid_hash(row["sha256"])):
                refuse()
            try:
                data = target.encode("utf-8", "strict")
                destination = (root / name).resolve(strict=True)
            except (OSError, RuntimeError, UnicodeError):
                refuse()
            if (not destination.is_relative_to(root) or row["size"] != len(data)
                    or row["sha256"] != sha256(data)):
                refuse()
        else:
            refuse()
    return value


def _descriptor(raw: bytes, manifest: Object, manifest_raw: bytes, component: str, build: str) -> Object:
    value = decode(raw)
    fields(value, "version kind component build source interpreter entry helpers importRoots payloadManifestSha256 capabilities")
    if (value["kind"] != "driver-capability" or component not in (*COMPONENTS, "arbol")
            or value["component"] != component or value["build"] != build or not BUILD.fullmatch(build)
            or value["payloadManifestSha256"] != sha256(manifest_raw)):
        refuse()
    source = value["source"]
    if (not isinstance(source, dict) or set(source) != {"commit", "tree"}
            or any(not isinstance(source[key], str) or SOURCE.fullmatch(source[key]) is None for key in source)):
        refuse()
    if value["capabilities"] != {"subscriptionIdentity": 0 if component == "arbol" else 1, "driverMaintenance": 1}:
        refuse()
    # bool compares equal to int in Python; exact wire integer types remain required.
    if any(type(item) is not int for item in value["capabilities"].values()):
        refuse()
    indexed = {row["path"]: row for row in manifest["files"]}
    for name in (value["interpreter"], value["entry"]):
        if indexed.get(relative(name), {}).get("type") != "file":
            refuse()
    if not indexed[value["interpreter"]]["mode"] & 0o111:
        refuse()
    for key in ("helpers", "importRoots"):
        names = value[key]
        if (not isinstance(names, list) or not all(isinstance(name, str) for name in names)
                or names != sorted(set(names), key=lambda name: name.encode("utf-8", "strict"))):
            refuse()
        if key == "importRoots" and not names:
            refuse()
        for name in names:
            row = indexed.get(relative(name), {})
            if key == "helpers" and row.get("type") != "file":
                refuse()
            if key == "importRoots" and not (row.get("type") == "directory" or
                                              (row.get("type") == "file" and name.endswith(".zip"))):
                refuse()
    return value


@dataclass(frozen=True)
class Payload:
    root: Path
    descriptor: Object
    digest: str

    @property
    def component(self) -> str:
        return str(self.descriptor["component"])

    @property
    def build(self) -> str:
        return str(self.descriptor["build"])

    @property
    def prefix(self) -> list[str]:
        return [str(self.root / self.descriptor["interpreter"]), "-ISB", str(self.root / self.descriptor["entry"])]

    def helper_prefix(self, entry: str) -> list[str]:
        if entry not in self.descriptor["helpers"]:
            refuse()
        return [str(self.root / self.descriptor["interpreter"]), "-ISB", str(self.root / entry)]


def load(root: Path, component: str, build: str) -> Payload:
    physical(root)
    manifest_raw = read_bytes(root / MANIFEST, limit=MANIFEST_LIMIT)
    descriptor_raw = read_bytes(root / DESCRIPTOR)
    manifest = _manifest(manifest_raw, root)
    descriptor = _descriptor(descriptor_raw, manifest, manifest_raw, component, build)
    if manifest["files"] != inventory(root):
        refuse()
    for name in (descriptor["interpreter"], descriptor["entry"], *descriptor["helpers"]):
        contained(root, name, regular=True)
    for name in descriptor["importRoots"]:
        contained(root, name)
    return Payload(root, descriptor, sha256(descriptor_raw))


def emit(root: Path, *, component: str, build: str, commit: str, tree: str, interpreter: str,
         entry: str, helpers: list[str], import_roots: list[str]) -> Payload:
    """Package-source operation, called after all executable/provenance bytes have settled."""
    manifest: Object = {"version": 1, "kind": "driver-payload-manifest", "files": inventory(root)}
    raw = canonical(manifest)
    if len(raw) > MANIFEST_LIMIT:
        refuse()
    descriptor: Object = {"version": 1, "kind": "driver-capability", "component": component, "build": build,
                          "source": {"commit": commit, "tree": tree}, "interpreter": interpreter, "entry": entry,
                          "helpers": helpers, "importRoots": import_roots, "payloadManifestSha256": sha256(raw),
                          "capabilities": {"subscriptionIdentity": 0 if component == "arbol" else 1,
                                           "driverMaintenance": 1}}
    _descriptor(canonical(descriptor), manifest, raw, component, build)
    publish(root / MANIFEST, manifest, limit=MANIFEST_LIMIT)
    publish(root / DESCRIPTOR, descriptor)
    return load(root, component, build)


@dataclass(frozen=True)
class Gate:
    document: Object
    digest: str
    provider: Payload


def registered(registry: Path, component: str, build: str) -> Payload:
    """Resolve exactly one registered Build without accepting a current-source path."""
    from .launcher import named_runnable, valid_record

    if component not in (*COMPONENTS, "arbol") or BUILD.fullmatch(build) is None:
        refuse()
    private_directory(registry)
    folder = private_directory(registry / component / build)
    record = decode(read_bytes(folder / "build.json"), exact=False)
    if not valid_record(record, component, build) or not named_runnable(str(registry), record):
        refuse()
    payload = load(folder / SUBTREE, component, build)
    source = record.get("source")
    if (not isinstance(source, dict) or source.get("commit") != payload.descriptor["source"]["commit"]
            or source.get("uncommittedChanges") is not False):
        refuse()
    return payload


def resolve_provider(registry: Path, digest: str) -> Payload:
    """The digest includes the registered Build string, so it must resolve uniquely."""
    from .driver_admission import Refusal

    if not valid_hash(digest):
        refuse()
    folder = private_directory(registry / "arbol")
    matched: list[Payload] = []
    count = 0
    for item in folder.iterdir():
        count += 1
        if count > MAX_ENTRIES:
            refuse()
        if BUILD.fullmatch(item.name) is None:
            continue
        try:
            raw = read_bytes(item / SUBTREE / DESCRIPTOR)
        except (OSError, Refusal):
            continue  # An unrelated incomplete Build cannot select the gate's provider.
        if sha256(raw) == digest:
            matched.append(registered(registry, "arbol", item.name))
    if len(matched) != 1:
        refuse()
    return matched[0]


def verify_gate(registry: Path) -> Gate:
    private_directory(registry)
    raw = read_bytes(registry / ".driver-qualification" / "gate.json")
    value = decode(raw)
    fields(value, "version kind providerPayloadSha256 components")
    if value["kind"] != "driver-gate" or not valid_hash(value["providerPayloadSha256"]):
        refuse()
    components = value["components"]
    if not isinstance(components, list) or len(components) != len(COMPONENTS):
        refuse()
    routes: set[Path] = set()
    for component, row in zip(COMPONENTS, components, strict=True):
        if (not isinstance(row, dict) or set(row) != {"component", "launcher", "launcherSha256"}
                or row["component"] != component or not valid_hash(row["launcherSha256"])
                or not isinstance(row["launcher"], str)):
            refuse()
        path = physical(row["launcher"], directory=False)
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o022 or not info.st_mode & 0o111
                or path.name != component or path in routes):
            refuse()
        routes.add(path)
        if _file_hash(path)[1] != row["launcherSha256"]:
            refuse()
    provider = resolve_provider(registry, value["providerPayloadSha256"])
    return Gate(value, sha256(raw), provider)


def verify_acceptance(authority: Authority, payload: Payload, *, digest: str | None = None) -> Object:
    """Check owner-trust metadata; never issue it or infer qualification from D."""
    import pwd

    if payload.root != authority.registry / authority.component / payload.build / SUBTREE:
        refuse()
    qualification = authority.read("qualification")
    if qualification["component"] != authority.component:
        refuse()
    selected = qualification["acceptanceSha256"]
    if not valid_hash(selected) or (digest is not None and selected != digest):
        refuse()
    raw = read_bytes(authority.shared / "acceptances" / (selected + ".json"))
    value = decode(raw)
    fields(value, "version kind status scope contract providerPayloadSha256 producerPayloadSha256 gateSha256 platform evidenceSha256")
    if (sha256(raw) != selected or value["kind"] != "driver-qualification"
            or value["status"] not in ("candidate", "qualified")
            or value["scope"] != str(authority.registry) or value["contract"] != "DRV-browser-identity-1"
            or value["producerPayloadSha256"] != payload.digest):
        refuse()
    for key in ("providerPayloadSha256", "producerPayloadSha256", "gateSha256", "evidenceSha256"):
        if not valid_hash(value[key]):
            refuse()
    uname = os.uname()
    if (uname.sysname != "Darwin" or value["platform"] != {
            "system": "Darwin", "release": uname.release, "machine": uname.machine}):
        refuse()
    installed = Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library/Application Support/Arbol/builds"
    if value["status"] == "candidate" and authority.registry == installed.resolve():
        refuse()
    gate = verify_gate(authority.registry)
    if (value["gateSha256"] != gate.digest
            or value["providerPayloadSha256"] != gate.provider.digest):
        refuse()
    return value
