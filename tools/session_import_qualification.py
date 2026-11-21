"""Verify the packaged session importer against a private installation and fictional native inputs."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import patch

from arbol_backend.exchange_context import Context
from arbol_backend.exchange_drain import begin_maintenance, freeze, reopen
from arbol_backend.model import Identity, Refused, identity, parse_import
from arbol_builds.service import write_launcher
from arbol_import.archive import ArchiveRoot
from arbol_import.command import ImportReport, run_import
from arbol_import.writer import ImportStore
from arbol_installation.admission import Source
from tools.backend_journeys import Bridge
from tools.imported_chat_journey import checked_package
from tools.session_import_drill import DATABASE, PORT, ROLE, Cluster, owner_only, private_folder, private_json, require

NATIVE = "00000000-0000-4000-8000-000000000101"
LEGACY = "00000000-0000-4000-8000-000000000102"
CHAT = "00000000-0000-4000-8000-000000000103"
EXCHANGE = "00000000-0000-4000-8000-000000000104"
CLAUDE = "00000000-0000-4000-8000-000000000105"
OLD = datetime(2026, 1, 1, tzinfo=UTC)
_BUILD_CHECKS = [{"name": "unit", "passed": True}, {"name": "roots-unit", "passed": True}]
_IMPORT_CHILD = """
import asyncio, json, os, signal, sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
action, folder, home, archive, *selected = sys.argv[1:]
package, home, archive = Path(folder), Path(home), Path(archive)
sys.path[:0] = [str(package / part) for part in ('src', 'runtime/site-packages')]
from arbol_backend.model import Refused, identity, parse_import
from arbol_import import command
from arbol_import.archive import ArchiveRoot
from arbol_import.writer import ImportStore
options = parse_import(['pi', *(word for native in selected for word in ('--session', native))])
current = replace(identity(package, {}, home=home), fixture=True)
if action == 'mercury':
    try:
        Path('/Volumes/Mercury').lstat()
    except PermissionError:
        pass
    else:
        raise RuntimeError('The disposable restriction did not deny Mercury.')
    with patch.object(command, '_reader', side_effect=AssertionError('Reader opened after Mercury refusal')):
        try:
            asyncio.run(command.run_import(current, options))
        except Refused as error:
            print(json.dumps({'code': error.code, 'denied': True}))
        else:
            raise RuntimeError('The real archive verifier admitted the restricted child.')
elif action == 'interrupt':
    original = ImportStore.apply
    async def committed(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        os.kill(os.getpid(), signal.SIGTERM)
        return result
    with patch.object(ImportStore, 'apply', committed):
        asyncio.run(command.run_import(current, options, archive=ArchiveRoot(archive, archive.parent.stat().st_dev)))
else:
    raise RuntimeError('Unknown disposable control.')
"""


def _ready(package: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((package / "build.json").read_bytes())
    require(record.get("component") == "arbol" and record.get("status") == "working"
            and record.get("installationLayout") == 2 and record.get("build") == package.name
            and record["source"]["uncommittedChanges"] is False and record["checks"] == _BUILD_CHECKS,
            "Expected a clean, working and fully checked private Backend.")
    return record


class RecoveryArchive:
    """Substitute only the volume binding for the real recorder and recovery tools."""

    def __init__(self, root: Path) -> None:
        self.root = owner_only(root)

    def backup_path(self, path: Path, *, allow_missing: bool = False) -> Path:
        canonical = path.resolve(strict=not allow_missing)
        require(path == canonical and canonical.is_relative_to(self.root),
                "Recovery output escaped its private volume.")
        return canonical


class Qualification:
    def __init__(self, root: Path, candidate: Path, prior: Path) -> None:
        self.root = owner_only(root)
        require(self.root.is_relative_to(Path("/private/tmp")) and not any(self.root.iterdir()),
                "Use a new private work directory under /private/tmp.")
        require(prior.is_relative_to(Path("/private/tmp")), "Use the working Backend from a prior private run.")
        self.build, self.commit = checked_package(candidate)
        old = _ready(prior)
        new = _ready(candidate)
        require(new["schemaCompatibility"] == [{"compatibilityVersion": 1, "minRevision": 5}]
                and old["schemaCompatibility"] == [{"compatibilityVersion": 1, "minRevision": 3}]
                and prior.name != candidate.name, "The two private Builds must have distinct numbers and schema floors.")
        self.home = private_folder(self.root / "home")
        self.settings = private_folder(self.home / ".arbol")
        self.runtime = private_folder(self.settings / "runtime")
        self.bin = private_folder(private_folder(self.home / ".local") / "bin")
        self.recovery = private_folder(self.root / "recovery")
        self.import_parent = private_folder(self.root / "archive")
        self.archive = ArchiveRoot(self.import_parent / "imports", self.import_parent.stat().st_dev)
        self.cluster = Cluster(self.root / "source")
        self.registry = private_folder(self.root / "registry")
        packages = private_folder(self.registry / "arbol")
        self.prior = packages / prior.name
        self.candidate = packages / candidate.name
        shutil.copytree(prior, self.prior, symlinks=True)
        shutil.copytree(candidate, self.candidate, symlinks=True)
        self.releases: dict[str, tuple[Path, str]] = {}
        self.fences = 0
        self.ident = replace(self.select(self.candidate), fixture=True)
        self.env = {**self.cluster.environment(), "HOME": str(self.home), "TMPDIR": str(self.root)}
        self.checks: list[str] = []

    def select(self, package: Path) -> Identity:
        return identity(package, {}, home=self.home)

    @property
    def source(self) -> Source:
        oid = int(self.cluster.psql("SELECT oid FROM pg_database WHERE datname = current_database()"))
        return {"host": str(self.cluster.socket), "port": PORT, "database": DATABASE, "databaseOid": oid}

    def check(self, test: bool, label: str) -> None:
        require(test, label)
        self.checks.append(label)

    def prepare(self) -> None:
        self.cluster.create(database=True)
        private_json(self.settings / "database.json", {"address": self.cluster.server_address, "database": DATABASE})
        write_launcher(str(self.bin), str(self.registry), "arbol", sys.executable)
        stage = self.bin / ".arbol-builds/schema"
        shutil.copytree(self.candidate / "runtime/site-packages", stage)
        shutil.copytree(self.candidate / "src/arbol_installation", stage.parent / "arbol_installation")
        database = self.candidate / "database"
        ledger = tomllib.loads((database / "migrations.toml").read_text())["migrations"]
        for name in ("migrations.toml", "migrate_schema.py", "database_server.py", *(row["file"] for row in ledger)):
            shutil.copy2(database / name, stage / name)
        command = [sys.executable, "-EsB", str(stage / "migrate_schema.py"), *self.connection(self.cluster),
                   "initialize", "--authorize-empty"]
        self.check(self.child(command)["revision"] == 1, "private schema initialized")
        self.capture("prior", self.prior)
        self.capture("candidate", self.candidate)

    @staticmethod
    def connection(cluster: Cluster) -> list[str]:
        return ["--database", DATABASE, "--socket", str(cluster.socket), "--port", str(PORT), "--user", ROLE]

    def child(self, command: list[str]) -> Any:
        result = subprocess.run(command, env=self.env, capture_output=True, timeout=150)
        if result.returncode:
            private_json(self.root / "child-failure.json", {
                "stderr": result.stderr.decode(errors="replace"), "stdout": result.stdout.decode(errors="replace"),
            })
            raise RuntimeError(f"A disposable qualification child failed with status {result.returncode}.")
        return json.loads(result.stdout.splitlines()[-1])

    def capture(self, label: str, package: Path) -> None:
        recovery_release = import_module("recovery_release")
        source = _ready(package)["source"]
        inventory = self.recovery / f"{label}-inventory.json"
        release = self.recovery / label
        private_json(inventory, {
            "kind": "current",
            "configuration": {"installation": str(self.settings / "database.json")},
            "builds": [{"directory": str(package), "checkout": source["repository"]}],
            "designCheckout": str(Path.home() / "repos/sylvan-stack/arbol-design-system"),
        })
        archive = RecoveryArchive(self.recovery)
        with patch.object(recovery_release, "require_archive", return_value=archive):
            digest = recovery_release.record_release(inventory, release)
        value, exact = recovery_release.verify_release(release, digest)
        self.check(exact == digest and value["builds"][0]["sourceCommit"] == source["commit"],
                   f"actual {label} release captured and read back")
        self.releases[label] = release, digest

    def fenced(self, *arguments: str) -> Any:
        fenced = import_module("backend.support").FENCED
        return self.child([sys.executable, "-I", "-B", "-c", fenced, str(self.candidate),
                           str(self.runtime), str(self.recovery), *arguments])

    def freeze(self, *, bootstrap: bool = False, package: Path | None = None) -> str:
        source = self.source
        token = begin_maintenance(source, runtime=self.runtime)
        selected = self.select(package or self.candidate)
        if bootstrap:
            selected = replace(selected, compatibility=((1, 1),))
        freeze(Context(selected), source, token)
        return token

    def reopen(self, label: str, token: str, revision: int) -> None:
        verify_release = import_module("recovery_release").verify_release
        package = self.prior if label == "prior" else self.candidate
        release, digest = self.releases[label]
        reopen(Context(self.select(package)), self.source, token, release=digest,
               schema={"compatibilityVersion": 1, "revision": revision},
               verify_release=lambda: verify_release(release, digest)[1])

    def upgrade(self, revision: int, label: str, *, bootstrap: bool = False) -> None:
        self.fences += 1
        token = self.freeze(bootstrap=bootstrap, package=self.prior)
        prior, previous_digest = self.releases["prior"]
        _, next_digest = self.releases[label]
        snapshot = self.recovery / f"snapshot-{revision}"
        attempt = self.recovery / f"restore-{revision}"
        self.fenced("recovery", *self.connection(self.cluster), "snapshot",
                    "--session", token, "--release", str(prior), "--output", str(snapshot))
        restored = Cluster(self.root / f"restore{self.fences}")
        try:
            restored.create(database=False)
            self.fenced("recovery", *self.connection(restored), "restore",
                        "--snapshot", str(snapshot), "--output", str(attempt))
            receipt = json.loads((attempt / "restore.json").read_bytes())
            self.check(receipt["status"] == "verified", f"isolated restore before revision {revision}")
        finally:
            require(restored.stop(), "The disposable restore server did not stop.")
        status = self.fenced("upgrade", DATABASE, str(self.cluster.socket), str(PORT), ROLE, str(revision),
                             token, previous_digest, next_digest, str(snapshot), str(attempt / "restore.json"))
        self.check(status == {"status": "ready", "revision": revision, "compatibilityVersion": 1},
                   f"fenced upgrade reached revision {revision}")
        self.reopen(label, token, revision)

    def seed_legacy(self) -> None:
        from arbol_import.archive import inspect_files, publish_session
        from arbol_import.readers import pi
        from arbol_import.readers.form import Session
        from arbol_import.readers.form import Source as ReaderSource

        path = _pi_file(self.home, LEGACY)
        _write_pi(path, LEGACY, 1)
        home = self.home / ".pi/agent"
        records = list(pi.read(ReaderSource(home, None, None, datetime.now(UTC), frozenset({LEGACY}))))
        require(len(records) == 1 and isinstance(records[0], Session), "The fictional legacy session did not parse.")
        session = records[0]
        assert isinstance(session, Session)
        self.archive.prepare()
        manifest = publish_session(self.archive, home, session, inspect_files(home, session.archive_files), OLD).manifest
        self.cluster.psql(f"""
            BEGIN;
            SET LOCAL arbol.importing = 'on';
            INSERT INTO chats VALUES ('{CHAT}', 'Fictional legacy session', '2026-01-01T00:00:00Z');
            INSERT INTO chat_imports (chat_id, tool, native_id, kind, origin, manifest, first_imported, last_imported)
            VALUES ('{CHAT}', 'pi', '{LEGACY}', 'owner', '{{}}', '{manifest}', '2026-01-01T00:00:00Z',
                    '2026-01-01T00:00:00Z');
            INSERT INTO chat_marks (chat_id, ongoing, archived_at, updated_at)
            VALUES ('{CHAT}', FALSE, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            INSERT INTO exchanges (id, chat_id, number, state, trunk, build, route, working_folder, accepted_at, ended_at)
            VALUES ('{EXCHANGE}', '{CHAT}', 1, 'completed', 'imported', '0', '{{"driver":"pi"}}', '/private',
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z');
            INSERT INTO exchange_imports VALUES ('{EXCHANGE}', '{CHAT}', 'user1', 'typed');
            COMMIT;
        """)

    def provenance(self) -> str:
        return self.cluster.psql("SELECT row_to_json(p)::text FROM chat_imports p ORDER BY native_id")

    def archived_tree(self) -> dict[str, str]:
        return {str(path.relative_to(self.archive.path)): sha256(path.read_bytes()).hexdigest()
                for path in self.archive.path.rglob("*") if path.is_file()}

    def execute(self, *words: str, dry: bool = False, archive: ArchiveRoot | None = None) -> ImportReport:
        arguments = [*words, *(["--dry-run"] if dry else [])]
        return asyncio.run(run_import(self.ident, parse_import(arguments),
                                      archive=None if dry else archive or self.archive))

    def session(self, native: str, *, dry: bool = False) -> ImportReport:
        return self.execute("pi", "--session", native, dry=dry)

    def sessions(self, *ids: str, dry: bool = False) -> ImportReport:
        return self.execute("pi", *(word for native in ids for word in ("--session", native)), dry=dry)

    def import_child(self, action: str, *ids: str, restrict: bool = False) -> subprocess.CompletedProcess[bytes]:
        command = [sys.executable, "-I", "-B", "-c", _IMPORT_CHILD, action,
                   str(self.candidate), str(self.home), str(self.archive.path), *ids]
        if restrict:
            profile = '(version 1)(allow default)(deny file-read* file-write* (subpath "/Volumes/Mercury"))'
            command = ["/usr/bin/sandbox-exec", "-p", profile, *command]
        return subprocess.run(command, env=self.env, capture_output=True, timeout=45)

    async def previous_playback(self) -> None:
        with (self.root / "previous-backend.log").open("wb") as log:
            command = [str(self.bin / "arbol"), "-v", self.prior.name, "backend"]
            child = subprocess.Popen(command, env=self.env, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT)
            try:
                async with asyncio.timeout(20):
                    endpoint = self.runtime / "backend.sock"
                    while not endpoint.is_socket():
                        require(child.poll() is None, "The previous numbered Backend could not start.")
                        await asyncio.sleep(0.05)
                    bridge = await Bridge.connect(endpoint)
                    try:
                        hello = next(row for row in bridge.events if row.get("type") == "hello")
                        response = await bridge.call("chats.page", {"archived": True})
                        require("result" in response, "The previous Backend refused the archived Chat Sessions query.")
                        self.check(hello["build"] == self.prior.name and any(
                            row["chat"] == CHAT and row["imported"] == {"tool": "pi", "kind": "owner"}
                            for row in response["result"]["chats"]
                        ), "previous numbered Backend reads original provenance at revision 5")
                    finally:
                        await bridge.close()
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        await asyncio.to_thread(child.wait, 10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        await asyncio.to_thread(child.wait, 10)


def _pi_file(home: Path, native: str) -> Path:
    return home / ".pi/agent/sessions/fictional" / f"2026-01-01T00-00-00Z_{native}.jsonl"


def _write_pi(path: Path, native: str, turns: int, *, live: bool = False) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    rows: list[dict[str, Any]] = [{"type": "session", "version": 3, "id": native,
                                  "timestamp": OLD.isoformat(), "cwd": "/private"}]
    parent = None
    for index in range(1, turns + 1):
        user, answer = f"user{index}", f"answer{index}"
        for position, identifier, message in (
            (0, user, {"role": "user", "content": "Fictional question."}),
            (1, answer, {"role": "assistant", "provider": "fixture", "model": "saved", "stopReason": "stop",
                         "usage": {"input": 3, "cacheRead": 2, "cacheWrite": 0, "output": 7},
                         "content": [{"type": "text", "text": "Fictional answer."}]}),
        ):
            at = OLD + timedelta(seconds=2 * index + position)
            rows.append({"type": "message", "id": identifier, "parentId": parent, "timestamp": at.isoformat(),
                         "message": {**message, "timestamp": int(at.timestamp() * 1000)}})
            parent = identifier
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    timestamp = datetime.now(UTC).timestamp() if live else OLD.timestamp()
    os.utime(path, (timestamp, timestamp))


def _write_claude(home: Path) -> None:
    project = home / ".claude/projects/fictional"
    sidecars = project / CLAUDE / "subagents"
    sidecars.mkdir(mode=0o700, parents=True)

    def message(lane: str, ordinal: int, role: str, content: object, end: str | None = None) -> dict[str, Any]:
        payload = {"role": role, "content": content}
        if role == "assistant":
            payload.update({"id": f"{lane}-message-{ordinal}", "model": "fixture-model", "stop_reason": end,
                            "usage": {"input_tokens": 4, "cache_creation_input_tokens": 0, "output_tokens": 2}})
        return {"type": role, "uuid": f"{lane}{ordinal}", "sessionId": CLAUDE, "cwd": "/private",
                "timestamp": (OLD + timedelta(seconds=ordinal)).isoformat(), "message": payload}

    files = {
        project / f"{CLAUDE}.jsonl": [
            message("main", 1, "user", "Fictional prompt."),
            message("main", 2, "assistant", [{"type": "tool_use", "id": "launch", "name": "Agent", "input": {}}],
                    "tool_use"),
            {"type": "attachment", "timestamp": (OLD + timedelta(seconds=3)).isoformat(),
             "attachment": {"type": "queued_command", "prompt": "Fictional follow-up."}},
            message("main", 6, "user", [{"type": "tool_result", "tool_use_id": "launch", "content": "Fictional."}]),
            message("main", 7, "assistant", [{"type": "text", "text": "Fictional completion."}], "end_turn"),
        ],
        sidecars / "agent-child.jsonl": [
            message("child", 4, "assistant", [{"type": "tool_use", "id": "nested", "name": "Bash",
                                               "input": {"command": "printf fixture"}}], "tool_use"),
            message("child", 5, "user", [{"type": "tool_result", "tool_use_id": "nested",
                                          "content": "ø\n" * (120 * 1024)}]),
        ],
    }
    for path, rows in files.items():
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        os.utime(path, (OLD.timestamp(), OLD.timestamp()))
    meta = sidecars / "agent-child.meta.json"
    private_json(meta, {"toolUseId": "launch"})
    os.utime(meta, (OLD.timestamp(), OLD.timestamp()))


def _outcome(report: ImportReport, expected: str) -> dict[str, Any]:
    require(report.error is None and len(report.sessions) == 1, "Expected one session report.")
    row = report.sessions[0]
    require(row.get("outcome") == expected, f"Expected {expected}; got {row.get('outcome')}.")
    return dict(row)


def _refusal(call: Callable[[], object], code: str) -> bool:
    try:
        call()
    except Refused as error:
        return error.code == code
    return False


def positive(qualification: Qualification) -> None:
    q = qualification
    q.upgrade(4, "prior", bootstrap=True)
    q.seed_legacy()
    q.check(_refusal(lambda: q.session(LEGACY, dry=True), "incompatible_schema"), "revision 4 refused before reading")
    q.upgrade(5, "candidate")
    asyncio.run(q.previous_playback())
    prior = q.cluster.psql("SELECT manifest || first_imported::text || last_imported::text FROM chat_imports "
                           "WHERE files_fingerprint IS NULL")
    q.check(bool(prior) and _outcome(q.session(LEGACY, dry=True), "failed")["error"]["code"] == "rows_refused",
            "legacy dry run requires recorded fingerprint")
    _outcome(q.session(LEGACY), "unchanged")
    repaired = q.cluster.psql("SELECT manifest || first_imported::text || last_imported::text FROM chat_imports "
                              "WHERE files_fingerprint IS NOT NULL")
    q.check(prior == repaired, "legacy fingerprint repaired without changing the prior receipt or times")

    path = _pi_file(q.home, NATIVE)
    _write_pi(path, NATIVE, 1)
    before, raw = q.provenance(), q.archived_tree()
    dry = q.session(NATIVE, dry=True)
    projected = _outcome(dry, "imported")
    q.check(dry.archive_bytes == 0 and "chat" not in projected and q.provenance() == before and q.archived_tree() == raw,
            "initial dry run preserved database and archive")
    real = q.session(NATIVE)
    actual = _outcome(real, "imported")
    q.check(real.archive_bytes > 0 and all(actual[key] == projected[key] for key in
            ("exchanges", "messages", "toolCalls", "subagentFallbacks")), "real import matches projected counts")
    q.check(q.cluster.psql("SELECT count(*) FROM runs r JOIN exchange_imports x USING(exchange_id) "
                            "WHERE x.turn_key='user1' AND r.usage->>'cacheWriteTokens'='0'").strip() == "1",
            "explicit zero cache write stored")
    _outcome(q.session(NATIVE), "unchanged")
    prior_rows = q.cluster.psql("SELECT exchange_id, turn_key FROM exchange_imports ORDER BY exchange_id")
    _write_pi(path, NATIVE, 2, live=True)
    _outcome(q.session(NATIVE), "deferred")
    os.utime(path, (OLD.timestamp(), OLD.timestamp()))
    _outcome(q.session(NATIVE), "extended")
    after = q.cluster.psql("SELECT exchange_id, turn_key FROM exchange_imports ORDER BY exchange_id")
    q.check(set(prior_rows.splitlines()) <= set(after.splitlines()), "saved Exchange identities survived the replay")

    before = q.provenance()
    empty_archive = q.import_parent / "temporarily-unavailable"
    q.archive.path.rename(empty_archive)
    try:
        q.check(q.session(NATIVE, dry=True).archive_bytes == 0, "dry run does not require an available archive")
        _outcome(q.session(NATIVE, dry=True), "unchanged")
        old = path.read_bytes()
        path.write_bytes(old + b'{"type":"custom","id":"meta","parentId":"answer2"}\n')
        os.utime(path, (OLD.timestamp(), OLD.timestamp()))
        changed = q.session(NATIVE, dry=True)
        _outcome(changed, "rearchived")
        q.check(changed.archive_bytes == 0 and q.provenance() == before, "file-only dry run preserved provenance")
    finally:
        empty_archive.rename(q.archive.path)
    _outcome(q.session(NATIVE), "rearchived")
    path.rename(path.with_name(path.name.replace("00-00-00", "00-00-01")))
    _outcome(q.session(NATIVE), "rearchived")
    _outcome(q.session(NATIVE), "unchanged")
    q.check(set(raw.items()) <= set(q.archived_tree().items()), "the prior manifest and its objects stayed byte exact")

    _write_claude(q.home)
    row = _outcome(q.execute("claude-code", "--session", CLAUDE), "imported")
    q.check((row["exchanges"], row["toolCalls"], row["subagentFallbacks"]) == (2, 2, 0),
            "a steer splits Exchanges and keeps the recorded launch")
    rows = q.cluster.value(f"""
        SELECT json_agg(json_build_array(x.turn_key, x.trigger, t.position, t.call_id, t.parent_call_id, t.name,
                                         t.truncated, octet_length(t.result::text)) ORDER BY x.turn_key, t.position)
        FROM exchange_imports x JOIN chat_imports c USING(chat_id) JOIN tool_calls t USING(exchange_id)
        WHERE c.native_id = '{CLAUDE}'
    """)
    q.check([item[:7] for item in rows] == [
        ["main1", "typed", 1, "launch", None, "Agent", False],
        ["main1", "typed", 2, "child/nested", "launch", "shell", True],
    ] and rows[1][7] <= 200 * 1024, "nested tool rows have dense positions and bounded results")


def _outcomes(report: ImportReport) -> list[object]:
    return [row.get("outcome") for row in report.sessions]


def negative(q: Qualification) -> None:
    draining, pending, killed, waiting, first, failure, rejected = (
        f"00000000-0000-4000-8000-{index:012d}" for index in range(106, 113)
    )
    files = {native: _pi_file(q.home, native) for native in (draining, pending, killed, waiting, first, failure, rejected)}
    for native, saved in files.items():
        _write_pi(saved, native, 1)
    snapshots = {saved: (sha256(saved.read_bytes()).hexdigest(), saved.stat().st_mtime_ns)
                 for saved in files.values()}

    denial = q.import_child("mercury", draining, restrict=True)
    q.check(denial.returncode == 0 and json.loads(denial.stdout) == {"code": "archive_unavailable", "denied": True},
            "real Mercury preflight refused before opening a reader inside verified restriction")
    lock = q.home / ".arbol/imports/import.lock"
    with lock.open("rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        q.check(_refusal(lambda: q.session(draining), "busy"), "a concurrent import was refused")

    original = ImportStore.apply
    token = None

    async def after_first(store: ImportStore, *args: Any, **options: Any) -> Any:
        nonlocal token
        result = await original(store, *args, **options)
        if token is None:
            token = begin_maintenance(q.source, runtime=q.runtime)
        return result

    with patch.object(ImportStore, "apply", after_first):
        report = q.sessions(draining, pending)
    q.check(report.error is not None and report.error["code"] == "maintenance"
            and _outcomes(report) == ["imported", None], "drain stopped between sessions with exact pending attribution")
    _outcome(q.session(pending, dry=True), "imported")
    assert token is not None
    freeze(Context(q.select(q.candidate)), q.source, token)
    q.check(_refusal(lambda: q.session(pending, dry=True), "maintenance"), "exclusive admission refused a dry run")
    q.reopen("candidate", token, 5)
    q.check(_outcomes(q.sessions(draining, pending)) == ["unchanged", "imported"], "drained import resumed safely")

    interrupted = q.import_child("interrupt", killed, waiting)
    q.check(interrupted.returncode == -signal.SIGTERM, "disposable importer was interrupted after its first commit")
    expected = q.cluster.psql(f"SELECT native_id FROM chat_imports WHERE native_id IN ('{killed}','{waiting}')")
    q.check(expected.strip() == killed, "interruption preserved only the committed session")
    q.check(_outcomes(q.sessions(killed, waiting)) == ["unchanged", "imported"], "interrupted import replayed safely")

    prefix = sha256(files[failure].read_bytes()).hexdigest()[:2]
    obstruction = q.archive.path / "objects" / prefix
    q.check(prefix != sha256(files[first].read_bytes()).hexdigest()[:2] and not obstruction.exists(),
            "the injected archive fault addresses only a later file")
    obstruction.touch(mode=0o600)
    try:
        refused = q.sessions(first, failure)
        q.check(refused.error is not None and refused.error["code"] == "archive_unavailable"
                and _outcomes(refused) == ["imported", None], "archive failure stopped before the later rows committed")
        count = q.cluster.psql(f"SELECT count(*) FROM chat_imports WHERE native_id='{failure}'")
        q.check(count.strip() == "0", "no later manifest reference was written after archive failure")
    finally:
        obstruction.unlink()
    q.check(_outcomes(q.sessions(first, failure)) == ["unchanged", "imported"], "archive failure replayed safely")

    q.cluster.psql(f"""
        CREATE FUNCTION public.qualify_refused_rows() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM public.exchanges e JOIN public.chat_imports c USING(chat_id)
                     WHERE e.id = NEW.exchange_id AND c.native_id = '{rejected}') THEN
            RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Fictional diagnostic must be hidden';
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER qualify_refused_rows BEFORE INSERT ON public.runs
          FOR EACH ROW EXECUTE FUNCTION public.qualify_refused_rows();
    """)
    try:
        refused = q.session(rejected)
        row = _outcome(refused, "failed")
        q.check(row["error"]["code"] == "rows_refused" and "Fictional diagnostic" not in json.dumps(row),
                "a confirmed row refusal hid database content")
        q.check(q.cluster.psql(f"SELECT count(*) FROM chat_imports WHERE native_id='{rejected}'").strip() == "0",
                "row refusal rolled back the entire session")
    finally:
        q.cluster.psql("DROP TRIGGER qualify_refused_rows ON public.runs; DROP FUNCTION public.qualify_refused_rows()")
    _outcome(q.session(rejected), "imported")
    q.check(all((sha256(saved.read_bytes()).hexdigest(), saved.stat().st_mtime_ns) == stamp
                for saved, stamp in snapshots.items()), "no import changed its native input bytes or mtimes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--prior", type=Path, required=True)
    args = parser.parse_args()
    q = Qualification(args.work, args.candidate.resolve(strict=True), args.prior.resolve(strict=True))
    try:
        q.prepare()
        positive(q)
        negative(q)
    finally:
        require(q.cluster.stop(), "The disposable source cluster did not stop.")
    print(json.dumps({"build": q.build, "source": q.commit, "checks": q.checks, "release": q.releases["candidate"][1]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
