# Shared fixtures only; test bodies are in top/ and mid/. See TESTS.md.
"""The global Root catalogue: private homes and stand-ins, with a separate real-server example (SYL-160)."""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_roots.database import Database, DatabaseError, environment  # noqa: E402
from arbol_roots.model import Places, catalogue, places  # noqa: E402
from arbol_roots.operations import Creation  # noqa: E402

ENTRY = ROOT / "bin/roots_entry.py"
ENV = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}

DATABASE_STAND_IN = f"""#!{sys.executable} -I
import json, os, sys, time
from pathlib import Path
home = Path(os.environ['HOME'])
kind = Path(__file__).name
config = json.loads((home / (kind + '.json')).read_text())
with (home / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps({{'kind': kind, 'args': sys.argv[1:], 'env': dict(os.environ)}}) + '\\n')
time.sleep(config.get('delay', 0))
print(config.get('password', '') if kind == 'security' else config.get('stdout', '1'))
sys.stderr.write(config.get('stderr', ''))
sys.exit(config.get('status', 0))
"""


def record(name: str = "sapling", state: str = "preparing", created: str = "2026-10-26T09:00:00.000Z",
           version: int = 1) -> dict[str, Any]:
    value: dict[str, Any] = {"root": name, "name": name.title(), "status": state, "createdAt": created,
                             "database": "arbol_" + name, "app": "0", "rootContract": version}
    if state == "failed":
        value["failed"] = {"at": created, "reason": "private failure"}
    return value


def database_fixture(test: unittest.TestCase) -> Places:
    home = Path(tempfile.mkdtemp(prefix="Arbol's database access "))
    test.addCleanup(shutil.rmtree, home, True)
    config = home / "database.json"
    config.write_text(json.dumps({"address": "postgresql://arbol@127.0.0.1:5433"}))
    for kind, values in (("security", {"password": "private-test-password"}), ("psql", {})):
        program = home / kind
        program.write_text(DATABASE_STAND_IN)
        program.chmod(0o755)
        (home / (kind + ".json")).write_text(json.dumps(values))
    return replace(places({"--database-config": str(config), "--security": str(home / "security"),
                           "--psql": str(home / "psql"), "--roots-dir": str(home / "roots"),
                           "--settings-dir": str(home / "settings"), "--registry-dir": str(home / "registry")}), home=home)


def roots_command(paths: Places, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *args,
                           "--roots-dir", str(paths.roots), "--settings-dir", str(paths.settings),
                           "--registry-dir", str(paths.registry), "--database-config", str(paths.database_config),
                           "--psql", paths.psql, "--security", paths.security],
                          cwd=paths.home, env={**ENV, "HOME": str(paths.home)}, capture_output=True, timeout=20, check=False)


def build_record(paths: Places, component: str, number: str, **extra: Any) -> dict[str, Any]:
    folder = paths.registry / component / number
    folder.mkdir(parents=True)
    value: dict[str, Any] = {"component": component, "build": number, "packageVersion": "1.0.0", "status": "working",
                             "startedAt": "2026-10-26T09:00:00.000Z", "finishedAt": "2026-10-26T09:00:01.000Z",
                             "source": {"repository": "/private", "branch": "main", "commit": "fixture",
                                        "uncommittedChanges": False}, "entry": "program", "checks": [
                                 {"name": "private", "passed": True}], **extra}
    (folder / "build.json").write_text(json.dumps(value))
    (folder / "program").write_text("#!/bin/sh\nexit 0\n")
    (folder / "program").chmod(0o755)
    return value


def real_server_example(tool: str | None = None) -> dict[str, object]:
    """An explicit acceptance run, never part of unit discovery, using only this run's disposable databases."""
    owner = Path.home()
    keychain = owner / "Library/Keychains/login.keychain-db"
    psql = shutil.which("psql")
    if psql is None or not keychain.is_file():
        raise RuntimeError("The real-server example needs psql and the owner's existing login Keychain.")
    with tempfile.TemporaryDirectory(prefix="Arbol's real Root example ") as temporary:
        home = Path(temporary)
        delegate = home / "security"
        # An explicit Keychain avoids the empty default search list of a private HOME. No secret is stored here.
        delegate.write_text(f"#!{sys.executable} -I\nimport os,sys\nos.execv('/usr/bin/security',"
                            f"['security',*sys.argv[1:],{str(keychain)!r}])\n")
        delegate.chmod(0o755)
        paths = replace(places({"--roots-dir": str(home / "roots"), "--settings-dir": str(home / "settings"),
                                "--registry-dir": str(home / "registry"),
                                "--database-config": str(owner / ".arbol/database.json"),
                                "--psql": psql, "--security": str(delegate)}), home=home)
        database = Database(paths)
        token = uuid.uuid4().hex
        names = {root: "arbol_roots_probe_" + token + "_" + suffix
                 for root, suffix in (("sapling", "a"), ("second", "b"), ("third", "c"), ("collision", "d"))}
        attempted: list[str] = []
        prefix = [tool] if tool else [sys.executable, "-I", "-B", str(ENTRY)]

        def require(condition: object, message: str) -> None:
            if not condition:
                raise RuntimeError(message)

        def exists(name: str) -> bool:
            return database.run("SELECT count(*) FROM pg_database WHERE datname = '" + name + "'") == "1"

        def call(*args: str, code: int = 0) -> Any:
            result = subprocess.run([*prefix, *args, "--roots-dir", str(paths.roots),
                                     "--settings-dir", str(paths.settings), "--registry-dir", str(paths.registry),
                                     "--database-config", str(paths.database_config), "--psql", paths.psql,
                                     "--security", paths.security],
                                    env={**environment(paths)}, cwd=home, capture_output=True, timeout=40, check=False)
            require(result.returncode == code, "Real-server command failed: " + os.fsdecode(result.stdout))
            return json.loads(result.stdout)

        def empty(name: str) -> bool:
            address = urlsplit(database.address)._replace(path="/" + quote(name, safe="")).geturl()
            sql = ("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                   "AND n.nspname NOT LIKE 'pg_toast%'")
            # Only the acceptance checker connects to its own disposable Root DB to inspect emptiness.
            result = subprocess.run([psql, "--no-psqlrc", "--no-password", "--no-align", "--tuples-only",
                                     "--dbname", address, "--command", sql],
                                    env=environment(paths, database.password), cwd=home,
                                    capture_output=True, text=True, timeout=20, check=False)
            require(result.returncode == 0, "Could not inspect a disposable database's emptiness.")
            return result.stdout.strip() == "0"

        for name in names.values():
            require(not exists(name), "A randomly named probe database already exists; refusing to touch it.")
        build_record(paths, "arbol-trunk/trivial", "1", rootContracts=[1, 2])
        try:
            attempted.append(names["collision"])
            database.create(names["collision"])
            collision = call("create", "collision", "--name", "Must refuse", "--database-name", names["collision"], code=1)
            require(collision["error"]["code"] == "database_unavailable", "An existing database was not refused.")
            require(exists(names["collision"]), "A refused creation removed an existing database.")
            require(not (paths.roots / "collision").exists() and not (paths.settings / "collision").exists(),
                    "A confirmed duplicate-database refusal left an unpublished Root behind.")
            attempted.append(names["sapling"])
            first = call("create", "sapling", "--name", "First Sapling", "--database-name", names["sapling"])
            require(first["status"] == "preparing" and first["rootContract"] == 1, "First Root metadata differs.")
            require(empty(names["sapling"]), "The first new database is not empty.")
            exchanges = paths.roots / "sapling/exchanges"
            require(exchanges.is_dir() and stat.S_IMODE(exchanges.stat().st_mode) == 0o700,
                    "Creation did not provide a private Exchange coordination directory.")
            exchanges.rmdir()  # A Root created by an older catalogue needs the same bootstrap at ready.
            call("ready", "sapling")
            require(exchanges.is_dir() and stat.S_IMODE(exchanges.stat().st_mode) == 0o700,
                    "Readiness did not repair an older Root's missing Exchange directory.")
            (paths.settings / "sapling/arbol.json").write_text('{"brain":"private acceptance recipe"}\n')
            attempted.append(names["second"])
            second = call("create", "second", "--name", "Second", "--from", "sapling",
                          "--database-name", names["second"])
            require(second["grewFrom"] == "sapling" and second["rootContract"] == 1, "Lineage/version was not inherited.")
            require(empty(names["second"]), "The second new database is not empty.")
            require((paths.settings / "second/arbol.json").read_bytes()
                    == (paths.settings / "sapling/arbol.json").read_bytes(), "Settings were not copied.")
            require(call("show")["root"] == "sapling", "Preparing the second Root changed current.")
            call("ready", "second")
            require(call("show")["root"] == "second", "Ready did not move current to the newer Root.")
            call("fail", "second", "--reason", "private acceptance failure")
            require(call("show")["root"] == "sapling", "Fail did not restore the older current Root.")
            require(call("remove", "sapling", code=1)["error"]["code"] == "current_root",
                    "The current Root was not protected.")
            require(exists(names["sapling"]), "The refused removal changed the first database.")
            attempted.append(names["third"])
            third = call("create", "third", "--name", "Third", "--root-contract", "2",
                         "--database-name", names["third"])
            require(third["rootContract"] == 2 and empty(names["third"]), "Explicit version 2 creation failed.")
            call("fail", "sapling", "--reason", "private acceptance cleanup")
            for root in ("second", "third", "sapling"):
                call("remove", root)
                require(not exists(names[root]), "Remove left its disposable database behind.")
                require(not (paths.roots / root).exists() and not (paths.settings / root).exists(),
                        "Remove left the named Root's folders behind.")
            require(call("list") == [], "Acceptance cleanup left a Root record behind.")
        finally:
            # These names were generated here and proved absent before the first CREATE; no wildcard or owner DB.
            for name in attempted:
                database.drop(name)
        return {"passed": True, "checks": ["three-empty-databases", "settings-copy", "version-inheritance",
                                            "explicit-version-2", "ready-fail-current", "current-removal-refusal",
                                            "database-and-folder-removal", "existing-database-refusal",
                                            "private-exchange-directory", "legacy-exchange-directory-repair"],
                "databasesLeft": 0, "vendorRequests": 0}


class Commands(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


class DatabaseAccess(unittest.TestCase):
    def fixture(self) -> Places:
        return database_fixture(self)


class Catalogue(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.


if __name__ == "__main__":
    if "--real-server" in sys.argv:
        parser = argparse.ArgumentParser(description="Run the explicit private Root/database acceptance example.")
        parser.add_argument("--real-server", action="store_true")
        parser.add_argument("--tool")
        options = parser.parse_args()
        try:
            print(json.dumps(real_server_example(options.tool)))
        except Exception as error:
            print(json.dumps({"passed": False, "error": str(error)}))
            sys.exit(1)
    else:
        unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
