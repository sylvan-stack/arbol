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
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .driver_admission import (
    COMPONENTS,
    LIMIT,
    MANIFEST_LIMIT,
    Authority,
    Object,
    canonical,
    canonical_uuid,
    decode,
    fields,
    natural,
    physical,
    private_directory,
    publish,
    read,
    read_bytes,
    refuse,
    sha256,
    valid_hash,
    valid_token,
    validate,
)

MANIFEST = "driver-payload-manifest.json"
DESCRIPTOR = "driver-capability.json"
SUBTREE = "driver-payload"
MAX_ENTRIES = 100000
BUILD = re.compile(r"[1-9a-f][0-9a-f]*\Z", re.ASCII)
SOURCE = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)


def optional_descriptor(folder: Path) -> bytes | None:
    """An older physical Build may genuinely have no declared payload yet."""
    physical(folder)
    root = folder / SUBTREE
    try:
        root.lstat()
    except FileNotFoundError:
        return None
    private_directory(root)
    path = root / DESCRIPTOR
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    # Once observed, disappearance or replacement is uncertainty, not absence.
    return read_bytes(path)


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


@contextmanager
def pin_payloads(registry: Path, payloads: list[Payload]) -> Iterator[None]:
    """Independently guard every exact tuple before publishing a durable reference.

    Call before control mutex acquisition. Closing these guards is safe only
    after publication made the tuple visible to the final prune recheck.
    """
    from .launcher import open_use_guard

    held: list[int] = []
    try:
        tuples: dict[tuple[str, str], Payload] = {}
        for payload in payloads:
            key = (payload.component, payload.build)
            if key in tuples and tuples[key].digest != payload.digest:
                refuse()
            tuples[key] = payload
        for (component, build), payload in sorted(tuples.items()):
            descriptor = open_use_guard(str(registry), component, build)
            held.append(descriptor)
            info = os.fstat(descriptor)
            named = (registry / component / ".uses" / build).lstat()
            if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                    or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
                refuse()
            current = registered(registry, component, build)
            if current.root != payload.root or current.digest != payload.digest:
                refuse()
        yield
    finally:
        for descriptor in reversed(held):
            os.close(descriptor)


@dataclass(frozen=True)
class Retention:
    builds: frozenset[str] = frozenset()
    all_builds: bool = False
    uncertain: bool = False


def _retention_gate(raw: bytes) -> Object:
    value = decode(raw)
    fields(value, "version kind providerPayloadSha256 components")
    if (value["kind"] != "driver-gate" or not valid_hash(value["providerPayloadSha256"])
            or not isinstance(value["components"], list) or len(value["components"]) != len(COMPONENTS)):
        refuse()
    for component, row in zip(COMPONENTS, value["components"], strict=True):
        if (not isinstance(row, dict) or set(row) != {"component", "launcher", "launcherSha256"}
                or row["component"] != component or not valid_hash(row["launcherSha256"])):
            refuse()
        path = physical(row["launcher"], directory=False)
        if path.name != component or _file_hash(path)[1] != row["launcherSha256"]:
            refuse()
    return value


def _retention_acceptance(shared: Path, component: str, digest: str, refs: dict[str, set[str]],
                          registry: Path) -> None:
    if not valid_hash(digest):
        refuse()
    raw = read_bytes(shared / "acceptances" / (digest + ".json"))
    value = decode(raw)
    fields(value, "version kind status scope contract providerPayloadSha256 producerPayloadSha256 gateSha256 platform evidenceSha256")
    if (sha256(raw) != digest or value["kind"] != "driver-qualification"
            or value["status"] not in ("candidate", "qualified") or value["scope"] != str(registry)
            or value["contract"] != "DRV-browser-identity-1"):
        refuse()
    for key in ("providerPayloadSha256", "producerPayloadSha256", "gateSha256", "evidenceSha256"):
        if not valid_hash(value[key]):
            refuse()
    refs["arbol"].add(value["providerPayloadSha256"])
    refs[component].add(value["producerPayloadSha256"])


def _retention_records(folder: Path, *, depth: int = 0) -> list[tuple[Path, Object]]:
    """Bounded registry-only scan; never traverse payloads, state or symlinks."""
    if depth > 5:
        refuse()
    private_directory(folder)
    found: list[tuple[Path, Object]] = []
    entries: list[Path] = []
    for path in folder.iterdir():
        if len(entries) >= MAX_ENTRIES:
            refuse()
        entries.append(path)
    for path in sorted(entries):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            found.extend(_retention_records(path, depth=depth + 1))
        elif stat.S_ISREG(info.st_mode) and path.name.endswith(".json"):
            found.append((path, read(path)))
        else:
            refuse()
        if len(found) > MAX_ENTRIES:
            refuse()
    return found


def _retention_component(authority: Authority, refs: dict[str, set[str]]) -> bool:
    control = authority.read("control")
    qualification = authority.read("qualification")
    if qualification["component"] != authority.component:
        refuse()
    _retention_acceptance(authority.shared, authority.component, qualification["acceptanceSha256"],
                          refs, authority.registry)
    retain_all = False
    try:
        taint = authority.read("taint")
    except FileNotFoundError:
        taint = None
    if taint is not None:
        if taint["component"] != authority.component:
            refuse()
        if taint["payloadSha256"] is None:
            retain_all = True  # Unknown old payload cannot be guessed from a dead main.
        else:
            refs[authority.component].add(taint["payloadSha256"])
    folders = [(authority.folder / "writers", "writer"), (authority.folder / "handoffs", "handoff")]
    pending_archive = authority.folder / "archive" / "custody-pending.json"
    if pending_archive.exists():
        journal = read(pending_archive)
        fields(journal, "version kind epoch archive phase")
        if (journal["kind"] != "driver-custody-archive" or not valid_token(journal["archive"])
                or not valid_token(journal["epoch"])
                or journal["phase"] not in ("prepared", "writers", "handoffs", "complete")):
            refuse()
        archived = authority.folder / "archive" / ("custody-" + journal["archive"])
        folders += [(archived / "writers", "writer"), (archived / "handoffs", "handoff")]
    for folder, kind in folders:
        if not folder.exists():
            if pending_archive.exists():
                continue
            refuse()
        for path, value in _retention_records(folder):
            if path.name.endswith(".context.json"):
                # The matching handoff/writer pin is authoritative; context also
                # retains its exact old acceptance while transfer is unresolved.
                from .driver_admission import normal_context
                normal_context(value)
                if value["component"] != authority.component:
                    refuse()
                _retention_acceptance(authority.shared, authority.component, value["acceptanceSha256"],
                                      refs, authority.registry)
            else:
                validate(kind, value)
                if value["component"] != authority.component or not valid_hash(value["payloadSha256"]):
                    refuse()
                refs[authority.component].add(value["payloadSha256"])
    sessions = private_directory(authority.folder / "sessions")
    count = 0
    for session in sessions.iterdir():
        count += 1
        if count > MAX_ENTRIES or not canonical_uuid(session.name):
            refuse()
        private_directory(session)
        contexts = session / "contexts"
        if os.path.lexists(contexts):
            for path, value in _retention_records(contexts):
                is_request = path.name.endswith(".request.json")
                attempt = path.name.removesuffix(".request.json" if is_request else ".json")
                if not valid_token(attempt) or path.parent != contexts:
                    refuse()
                context = read(contexts / (attempt + ".json")) if is_request else value
                validate("context", context)
                if (context["component"] != authority.component or context["session"] != session.name
                        or context["attempt"] != attempt):
                    refuse()
                if is_request:
                    request_binding(value, context)
                archived = session / "attempts" / attempt / ("request.json" if is_request else "context.json")
                if control["phase"] == "normal" and archived.exists() and read(archived) == value:
                    continue
                refs[authority.component].add(context["payloadSha256"])
                _retention_acceptance(authority.shared, authority.component, context["acceptanceSha256"],
                                      refs, authority.registry)
        operation = session / "operation.json"
        active = operation.exists()
        records: list[tuple[Path, Object]] = []
        if active:
            value = read(operation)
            validate("operation", value)
            if value["epoch"] != control["epoch"]:
                refuse()
            records.append((operation, value))
        result = session / "result.json"
        if result.exists():
            value = read(result)
            validate("result", value)
            if active or control["phase"] != "normal" or value["epoch"] == control["epoch"]:
                records.append((result, value))
        if (active or control["phase"] != "normal") and (session / "attempts").exists():
            for path, value in _retention_records(session / "attempts"):
                if path.name in ("operation.json", "result.json"):
                    validate("operation" if path.name == "operation.json" else "result", value)
                    records.append((path, value))
                elif path.name in ("context.json", "request.json"):
                    context = read(path.parent / "context.json") if path.name == "request.json" else value
                    validate("context", context)
                    if context["component"] != authority.component or context["session"] != session.name:
                        refuse()
                    if path.name == "request.json":
                        request_binding(value, context)
                    refs[authority.component].add(context["payloadSha256"])
                    _retention_acceptance(authority.shared, authority.component, context["acceptanceSha256"],
                                          refs, authority.registry)
        for path, value in records:
            if value["component"] != authority.component or not valid_hash(value["payloadSha256"]):
                refuse()
            refs[authority.component].add(value["payloadSha256"])
            if path.name == "operation.json":
                _retention_acceptance(authority.shared, authority.component, value["acceptanceSha256"],
                                      refs, authority.registry)
    return retain_all


def _retention_builds(registry: Path, component: str, digests: set[str]) -> frozenset[str]:
    """Map only exact D digests, not executable names, timestamps or defaults."""
    if not digests:
        return frozenset()
    remaining, found = set(digests), set()
    count = 0
    for folder in private_directory(registry / component).iterdir():
        count += 1
        if count > MAX_ENTRIES:
            refuse()
        if not BUILD.fullmatch(folder.name):
            continue
        raw = optional_descriptor(folder)
        if raw is None:
            continue
        digest = sha256(raw)
        if digest not in digests:
            continue
        value = decode(raw)
        fields(value, "version kind component build source interpreter entry helpers importRoots payloadManifestSha256 capabilities")
        if (value["kind"] != "driver-capability" or value["component"] != component
                or value["build"] != folder.name or not valid_hash(value["payloadManifestSha256"])):
            refuse()
        remaining.discard(digest)
        found.add(folder.name)
    if remaining:
        refuse()  # A missing/corrupt pinned tuple retains affected candidates.
    return frozenset(found)


def retention(registry: str, component: str) -> Retention:
    """A preliminary snapshot, also repeated under .uses EX immediately before deletion."""
    if component not in (*COMPONENTS, "arbol"):
        return Retention()
    root = Path(os.path.abspath(registry))
    shared = root / ".driver-qualification"
    names = COMPONENTS if component == "arbol" else (component,)
    present = (os.path.lexists(shared / "gate.json") or os.path.lexists(shared / "deployment.json")
               or any(os.path.lexists(root / name / ".driver-admission") for name in names))
    if not present:
        return Retention()
    try:
        private_directory(root)
        refs: dict[str, set[str]] = {name: set() for name in (*COMPONENTS, "arbol")}
        with ExitStack() as stack:
            authorities = [Authority(root, name) for name in names]
            for authority in authorities:
                stack.enter_context(authority.mutex(seconds=0))
            gate = _retention_gate(read_bytes(shared / "gate.json"))
            refs["arbol"].add(gate["providerPayloadSha256"])
            deployment = shared / "deployment.json"
            if deployment.exists():
                value = read(deployment)
                validate("deployment", value)
                if value["phase"] != "complete":
                    # Includes before-images and all old/new tuples during a
                    # partially installed/restaged all-four rollout.
                    return Retention(all_builds=True)
            retain_all = False
            for authority in authorities:
                retain_all = _retention_component(authority, refs) or retain_all
            if retain_all:
                return Retention(all_builds=True)
            return Retention(builds=_retention_builds(root, component, refs[component]))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return Retention(uncertain=True)


def protected_payloads(registry: str, component: str, numbers: list[str]) -> set[str]:
    value = retention(registry, component)
    return set(numbers) if value.all_builds or value.uncertain else set(value.builds)


def retention_status(registry: str, component: str, number: str) -> str | None:
    value = retention(registry, component)
    if value.uncertain:
        return "unverifiable"
    if value.all_builds or number in value.builds:
        return "inUse"
    return None


METADATA_ROOTS = ("format", "identity.json", "identity-maintenance.json", "identity-upgrade.json")
SUBSCRIPTION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}\Z", re.ASCII)
MAINTENANCE_OPERATIONS = frozenset(("upgrade", "identity-reset", "restore", "identity-recover"))


def metadata_name(value: object) -> str:
    if not isinstance(value, str):
        refuse()
    if value in METADATA_ROOTS:
        return value
    parts = value.split("/")
    if (len(parts) != 3 or parts[0] != "subscriptions" or SUBSCRIPTION.fullmatch(parts[1]) is None
            or parts[2] not in ("identity.json", "identity-pending.json")):
        refuse()
    return value


def metadata_marker(value: Object) -> Object:
    fields(value, "version component session epoch operation attempt payloadSha256 generation phase sourceSha256 backupSha256")
    if (value["component"] not in COMPONENTS or not canonical_uuid(value["session"])
            or value["operation"] not in MAINTENANCE_OPERATIONS or value["phase"] not in ("pending", "complete")
            or any(not valid_token(value[key]) for key in ("epoch", "attempt", "generation"))
            or any(not valid_hash(value[key]) for key in ("payloadSha256", "backupSha256"))
            or (value["sourceSha256"] is not None and not valid_hash(value["sourceSha256"]))
            or (value["sourceSha256"] is not None) != (value["operation"] == "restore")):
        refuse()
    return value


def metadata_upgrade(value: Object) -> Object:
    fields(value, "version from to generation backup backupSha256")
    if (type(value["from"]) is not int or value["from"] != 1
            or type(value["to"]) is not int or value["to"] != 2
            or not valid_token(value["generation"]) or not valid_hash(value["backupSha256"])):
        refuse()
    canonical_path(value["backup"])
    return value


def canonical_path(value: object) -> str:
    """Lexical validation only; retention never reads a Driver state/backup tree."""
    if (not isinstance(value, str) or not value or "\0" in value or not os.path.isabs(value)
            or os.path.normpath(value) != value or value.startswith("//")
            or len(value.encode("utf-8", "strict")) > LIMIT):
        refuse()
    return value


def request_binding(value: Object, context: Object) -> None:
    validate("context", context)
    names = ("version kind component session epoch attempt payloadSha256 acceptanceSha256 contextSha256 "
             "build stateDirectory operation backup source")
    if context["operation"] == "identity-recover":
        names += " subscription"
    fields(value, names)
    if (value["kind"] != "driver-maintenance-request" or not valid_hash(value["contextSha256"])
            or value["contextSha256"] != sha256(canonical(context))
            or not isinstance(value["build"], str) or BUILD.fullmatch(value["build"]) is None
            or any(value[key] != context[key] for key in (
                "component", "session", "epoch", "attempt", "payloadSha256", "acceptanceSha256", "stateDirectory", "operation"))):
        refuse()
    for key in ("stateDirectory", "backup"):
        canonical_path(value[key])
    if (value["source"] is not None) != (context["operation"] == "restore"):
        refuse()
    if value["source"] is not None:
        canonical_path(value["source"])
    if context["operation"] == "identity-recover" and (
            value["subscription"] != context["subscription"] or not isinstance(value["subscription"], str)
            or SUBSCRIPTION.fullmatch(value["subscription"]) is None):
        refuse()


def metadata_document(name: str, raw: bytes) -> Object:
    name = metadata_name(name)
    value = decode(raw)
    if name == "identity.json":
        fields(value, "version generation")
        if not valid_token(value["generation"]):
            refuse()
    elif name.endswith("/identity.json"):
        fields(value, "version witness state")
        if not valid_token(value["witness"]) or value["state"] not in ("active", "retired"):
            refuse()
    elif name.endswith("/identity-pending.json"):
        fields(value, "version operation witness phase")
        if (value["operation"] not in ("create", "remove") or not valid_token(value["witness"])
                or value["phase"] not in ("prepared", "committed")):
            refuse()
    elif name == "identity-upgrade.json":
        metadata_upgrade(value)
    elif name == "identity-maintenance.json":
        metadata_marker(value)
    else:
        refuse()
    return value


@dataclass(frozen=True)
class MetadataBackup:
    directory: Path
    manifest: Object
    digest: str
    contents: dict[str, bytes | None]


def metadata_backup(directory: Path, *, source: bool = False) -> MetadataBackup:
    """Verify only the exact bounded metadata entry, never arbitrary backup files."""
    private_directory(directory)
    raw = read_bytes(directory / "manifest.json", limit=MANIFEST_LIMIT)
    manifest = decode(raw, limit=MANIFEST_LIMIT)
    fields(manifest, "version kind format files")
    if (manifest["kind"] != "driver-identity-backup"
            or (manifest["format"] is not None and (type(manifest["format"]) is not int or manifest["format"] not in (1, 2)))
            or not isinstance(manifest["files"], list) or len(manifest["files"]) > MAX_ENTRIES):
        refuse()
    expected = {"manifest.json"}
    contents: dict[str, bytes | None] = {}
    prior = b""
    size = len(raw)
    for row in manifest["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "present", "size", "sha256"}:
            refuse()
        name = metadata_name(row["path"])
        if (name.encode("utf-8") <= prior or type(row["present"]) is not bool
                or not natural(row["size"]) or row["size"] > LIMIT):
            refuse()
        prior = name.encode("utf-8")
        if not row["present"]:
            if row["size"] != 0 or row["sha256"] is not None:
                refuse()
            contents[name] = None
            continue
        if not valid_hash(row["sha256"]):
            refuse()
        content = read_bytes(directory / name, limit=min(LIMIT, MANIFEST_LIMIT - size))
        if len(content) != row["size"] or sha256(content) != row["sha256"]:
            refuse()
        size += len(content)
        contents[name] = content
        expected.add(name)
        expected.update("/".join(name.split("/")[:index]) for index in range(1, len(name.split("/"))))
    if not set(METADATA_ROOTS) <= contents.keys():
        refuse()
    format_raw = contents["format"]
    number = {b"1": 1, b"2": 2}.get(format_raw.strip()) if format_raw is not None else None
    if number != manifest["format"] or (source and number not in (1, 2)):
        refuse()
    actual: set[str] = set()

    def visit(folder: Path) -> None:
        for path in folder.iterdir():
            name = path.relative_to(directory).as_posix()
            if name not in expected or len(actual) >= MAX_ENTRIES * 3 + 1:
                refuse()
            actual.add(name)
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                private_directory(path)
                visit(path)
            elif not stat.S_ISREG(info.st_mode):
                refuse()
    visit(directory)
    if actual != expected:
        refuse()
    if source:
        if number == 2 and contents["identity.json"] is None:
            refuse()
        for name, source_bytes in contents.items():
            if source_bytes is not None and name != "format":
                metadata_document(name, source_bytes)
    return MetadataBackup(directory, manifest, sha256(raw), contents)
