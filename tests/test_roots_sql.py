"""Runtime SQL selection and application use only private records and stand-ins."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_roots  # noqa: E402

from arbol_builds.launcher import open_use_guard  # noqa: E402
from arbol_roots.database import Database, DatabaseError  # noqa: E402
from arbol_roots.model import Places, Refused, save_record  # noqa: E402
from arbol_roots.sql import databases, layout, migrate, selected_sql  # noqa: E402


def image(paths: Places, number: str = "1", root: str = "sapling", older: str | None = None,
          **changes: Any) -> Path:
    test_roots.build_record(paths, "arbol-root", number, root=root, **changes)
    folder = paths.registry / "arbol-root" / number
    (folder / "layout").mkdir()
    for name in ["chat-tables.sql", "root-tables.sql", *(["migrate.sql"] if older else [])]:
        (folder / "layout" / name).write_text("-- private SQL fixture\n")
    manifest = {"component":"arbol-root", "root":root, "build":number,
                "layout":{"root":root,"rootContract":1,"grewFrom":older},
                "files":{str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (folder / "layout").iterdir()}}
    (folder / "package-manifest.json").write_text(json.dumps(manifest))
    return folder


class Selection(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = test_roots.record()
        (self.paths.roots / "sapling").mkdir(parents=True)
        save_record(self.paths, self.record)

    def test_newest_working_same_root_with_sql_is_selected_and_guarded(self) -> None:
        """roots.sql-selection"""
        image(self.paths)
        image(self.paths, "2")
        image(self.paths, "3", status="withdrawn")
        image(self.paths, "4", root="other")
        image(self.paths, "5", prunedAt="2026-10-26T20:00:00.000Z")
        image(self.paths, "6").joinpath("layout").rename(self.paths.home / "absent-sql")
        with selected_sql(self.paths, self.record, migration=False) as build:
            self.assertEqual(build.number, "2")
            self.assertEqual(list(build.files), ["chat-tables.sql", "root-tables.sql"])
            with self.assertRaises(BlockingIOError):
                open_use_guard(str(self.paths.registry), "arbol-root", "2", exclusive=True)

    def test_damaged_selected_files_or_manifest_fail_without_older_fallback(self) -> None:
        """roots.sql-preflight"""
        image(self.paths)
        folder = image(self.paths, "2")
        file = folder / "layout/root-tables.sql"
        original = file.read_bytes()
        for kind in ["changed", "missing", "symlink"]:
            file.unlink(missing_ok=True)
            if kind == "changed":
                file.write_text("changed")
            elif kind == "symlink":
                file.symlink_to(folder / "layout/chat-tables.sql")
            with self.assertRaises(Refused) as caught, selected_sql(self.paths, self.record, migration=False):
                self.fail("A damaged selected file was accepted.")
            self.assertEqual(caught.exception.code, "build_unavailable")
        file.unlink()
        file.write_bytes(original)
        manifest = json.loads((folder / "package-manifest.json").read_text())
        for version in [2, True]:
            manifest["layout"]["rootContract"] = version
            (folder / "package-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(Refused), selected_sql(self.paths, self.record, migration=False):
                self.fail("Wrong contract was accepted.")

    def test_pruner_lock_refuses_and_migration_requires_its_extra_file(self) -> None:
        """roots.sql-pruning"""
        folder = image(self.paths, older="older")
        self.record["grewFrom"] = "older"
        guard = open_use_guard(str(self.paths.registry), "arbol-root", "1", exclusive=True)
        try:
            with self.assertRaises(Refused) as caught, selected_sql(self.paths, self.record, migration=True):
                self.fail("An exclusively held Build was accepted.")
            self.assertEqual(caught.exception.code, "busy")
        finally:
            os.close(guard)
        (folder / "layout/migrate.sql").unlink()
        with self.assertRaises(Refused), selected_sql(self.paths, self.record, migration=True):
            self.fail("A missing migration script was accepted.")
        with selected_sql(self.paths, self.record, migration=False):
            pass

    def test_database_aliases_and_connection_string_forms_are_refused(self) -> None:
        """roots.sql-databases"""
        other = test_roots.record("other")
        other["database"] = self.record["database"]
        (self.paths.roots / "other").mkdir()
        save_record(self.paths, other)
        with self.assertRaises(Refused):
            databases(self.paths, self.record)
        (self.paths.roots / "other/root.json").unlink()
        for name in ["dbname=elsewhere", "postgresql://elsewhere/db", "postgres://elsewhere/db", "-"]:
            with self.subTest(name=name), self.assertRaises(Refused):
                databases(self.paths, {**self.record,"database":name})
        self.assertEqual(databases(self.paths, {**self.record,"database":"私の 'database'"}),
                         ("私の 'database'", None))


class Layout(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = test_roots.record(state="working")
        (self.paths.roots / "sapling").mkdir(parents=True)
        save_record(self.paths, self.record)
        self.folder = image(self.paths)

    def test_layout_runs_two_transactions_minimal_environment_and_keeps_metadata(self) -> None:
        """roots.layout"""
        header = self.paths.roots / "sapling/root.json"
        before = header.read_bytes()
        with mock.patch.dict(os.environ, {"PGHOST":"outside", "PGSERVICE":"outside", "UNRELATED":"private"}):
            with mock.patch("arbol_roots.database.subprocess.run", wraps=subprocess.run) as calls:
                reply = layout(self.paths, "sapling")
        self.assertEqual(reply, {"root":"sapling", "rootBuild":"1", "files":["chat-tables.sql","root-tables.sql"]})
        self.assertEqual(header.read_bytes(), before)
        self.assertEqual(len(calls.call_args_list), 3)
        for called, name in zip(calls.call_args_list[1:], reply["files"], strict=True):
            args = called.args[0]
            self.assertEqual(args[args.index("--file")+1], str((self.folder / "layout" / name).resolve()))
            self.assertEqual(args[-1], "postgresql://arbol@127.0.0.1:5433/arbol_sapling")
            for arg in ["--no-psqlrc", "--no-password", "ON_ERROR_STOP=1", "--single-transaction"]:
                self.assertIn(arg, args)
            self.assertEqual(set(called.kwargs["env"]), {"HOME","PATH","LANG","PGPASSWORD"})
            self.assertEqual(called.kwargs["timeout"], 60)
            self.assertNotIn("private-test-password", str(args))

    def test_sql_error_statuses_name_failure_redact_password_and_stop_immediately(self) -> None:
        """roots.sql-failure"""
        for status in [1, 2, 3]:
            with self.subTest(status=status):
                (self.paths.home / "calls.jsonl").unlink(missing_ok=True)
                (self.paths.home / "psql.json").write_text(json.dumps({
                    "status":status, "stderr":"psql:root-tables.sql:35: ERROR: private-test-password broken SQL"}))
                with self.assertRaises(DatabaseError) as error:
                    layout(self.paths, "sapling")
                self.assertIn(f"status {status}", str(error.exception))
                self.assertIn("root-tables.sql:35", str(error.exception))
                self.assertIn("[password removed]", str(error.exception))
                self.assertNotIn("private-test-password", str(error.exception))
                self.assertEqual((self.paths.home / "calls.jsonl").read_text().count('"kind": "psql"'), 1)

    def test_preparing_missing_tool_or_damaged_sql_runs_no_psql(self) -> None:
        """roots.layout-refusal"""
        before = (self.paths.roots / "sapling/root.json").read_bytes()
        for state in ["preparing", "working"]:
            save_record(self.paths, {**self.record,"status":state})
            with mock.patch("arbol_roots.sql.shutil.which", return_value=None):
                with self.assertRaises(Refused):
                    layout(self.paths, "sapling")
        (self.folder / "layout/root-tables.sql").unlink()
        with self.assertRaises(Refused):
            layout(self.paths, "sapling")
        self.assertFalse((self.paths.home / "calls.jsonl").exists())
        self.assertEqual((self.paths.roots / "sapling/root.json").read_bytes(), before)

    def test_layout_cli_is_json_and_needs_no_older_root_or_database(self) -> None:
        """roots.layout-cli"""
        self.record["grewFrom"] = "gone"
        save_record(self.paths, self.record)
        p = self.folder / "package-manifest.json"
        value = json.loads(p.read_text())
        value["layout"]["grewFrom"] = "gone"
        p.write_text(json.dumps(value))
        result = test_roots.roots_command(self.paths, "layout", "sapling")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["rootBuild"], "1")

    def test_file_timeout_is_a_bounded_uncertain_database_failure(self) -> None:
        """roots.sql-timeout"""
        database = Database(self.paths)
        with mock.patch("arbol_roots.database.subprocess.run", side_effect=subprocess.TimeoutExpired("psql", 60)):
            with self.assertRaisesRegex(DatabaseError, "60 seconds") as error:
                database.file("arbol_sapling", self.folder / "layout/chat-tables.sql")
        self.assertTrue(error.exception.uncertain)


class Migration(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = test_roots.database_fixture(self)
        self.record = {**test_roots.record("second"), "grewFrom":"sapling"}
        for record in [test_roots.record(state="working"), self.record]:
            (self.paths.roots / record["root"]).mkdir(parents=True)
            save_record(self.paths, record)
        self.folder = image(self.paths, root="second", older="sapling")
        client = test_roots.DATABASE_STAND_IN.replace(
            "'env': dict(os.environ)",
            "'env': dict(os.environ), 'cwd': os.getcwd(), 'mode': os.stat('.').st_mode & 511, 'pid': os.getpid()")
        client = client.replace("time.sleep(config.get('delay', 0))", """
migrating = kind == 'psql' and '--file' in sys.argv and sys.argv[sys.argv.index('--file')+1].endswith('migrate.sql')
if migrating:
    Path('private.copy').write_text('fictional copied rows')
time.sleep(config.get('delay', 0))""")
        client = client.replace("sys.exit(config.get('status', 0))",
                                "sys.exit(config.get('migrationStatus', 0) if migrating else config.get('status', 0))")
        Path(self.paths.psql).write_text(client)

    def calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in (self.paths.home / "calls.jsonl").read_text().splitlines()
                if json.loads(line)["kind"] == "psql"]

    def test_migration_recreates_then_runs_files_in_order_and_cleans_private_copies(self) -> None:
        """roots.migrate"""
        headers = {name:(self.paths.roots / name / "root.json").read_bytes() for name in ["sapling","second"]}
        for _ in range(2):
            reply = migrate(self.paths, "second")
            self.assertEqual(reply, {"root":"second","rootBuild":"1",
                                     "files":["chat-tables.sql","root-tables.sql","migrate.sql"]})
        for name, original in headers.items():
            self.assertEqual((self.paths.roots / name / "root.json").read_bytes(), original)
        calls = self.calls()
        self.assertEqual(len(calls), 10)
        for offset in [0,5]:
            group = calls[offset:offset+5]
            self.assertEqual([c["args"][-1] for c in group[:2]],
                             ['DROP DATABASE IF EXISTS "arbol_second"',
                              'CREATE DATABASE "arbol_second" TEMPLATE template0 ENCODING \'UTF8\''])
            self.assertEqual([Path(c["args"][c["args"].index("--file")+1]).name for c in group[2:]], reply["files"])
            last = group[-1]
            self.assertNotIn("--single-transaction", last["args"])
            self.assertIn("from_database=arbol_sapling", last["args"])
            self.assertIn("from_root=sapling", last["args"])
            self.assertEqual(last["mode"], 0o700)
            self.assertFalse(Path(last["cwd"]).exists())

    def test_failed_migration_names_file_and_leaves_preparing_with_no_copy_directory(self) -> None:
        """roots.migrate-failure"""
        (self.paths.home / "psql.json").write_text(json.dumps({
            "migrationStatus":3, "stderr":"psql:migrate.sql:35: ERROR: planted missing table"}))
        before = (self.paths.roots / "second/root.json").read_bytes()
        answer = test_roots.roots_command(self.paths, "migrate", "second")
        self.assertEqual(answer.returncode, 1)
        error = json.loads(answer.stdout)["error"]
        self.assertIn("migrate.sql:35", error["message"])
        self.assertIn("status 3", error["message"])
        self.assertEqual((self.paths.roots / "second/root.json").read_bytes(), before)
        self.assertFalse(Path(self.calls()[-1]["cwd"]).exists())

    def test_nonpreparing_or_incomplete_input_never_reaches_psql(self) -> None:
        """roots.migrate-refusal"""
        for state in ["working", "failed"]:
            value = {**self.record, "status":state}
            if state == "failed":
                value["failed"] = {"at":value["createdAt"],"reason":"private failure"}
            save_record(self.paths, value)
            with self.assertRaises(Refused):
                migrate(self.paths, "second")
        save_record(self.paths, self.record)
        (self.folder / "layout/migrate.sql").unlink()
        with self.assertRaises(Refused):
            migrate(self.paths, "second")
        self.assertFalse((self.paths.home / "calls.jsonl").exists())

    def test_interrupted_file_runner_still_removes_its_private_directory(self) -> None:
        """roots.migrate-interruption"""
        before = {number:signal.getsignal(number) for number in [signal.SIGINT, signal.SIGTERM]}
        with mock.patch.object(Database, "file", side_effect=[None,None,KeyboardInterrupt]) as calls:
            with self.assertRaises(KeyboardInterrupt):
                migrate(self.paths, "second")
        self.assertFalse(calls.call_args.kwargs["cwd"].exists())
        self.assertEqual({number:signal.getsignal(number) for number in before}, before)
        self.assertEqual(json.loads((self.paths.roots / "second/root.json").read_text())["status"], "preparing")

    def test_real_cli_signals_reap_the_sql_child_and_remove_private_copies(self) -> None:
        """roots.migrate-signals"""
        psql = Path(self.paths.psql)
        psql.write_text(psql.read_text().replace("time.sleep(config.get('delay', 0))",
                                               "time.sleep(60 if migrating else 0)"))
        for number in [signal.SIGINT, signal.SIGTERM]:
            with self.subTest(signal=number):
                (self.paths.home / "calls.jsonl").unlink(missing_ok=True)
                command = [sys.executable,"-I","-B",str(test_roots.ENTRY),"migrate","second",
                           "--roots-dir",str(self.paths.roots),"--settings-dir",str(self.paths.settings),
                           "--registry-dir",str(self.paths.registry),"--database-config",str(self.paths.database_config),
                           "--psql",self.paths.psql,"--security",self.paths.security]
                process = subprocess.Popen(command,env={**test_roots.ENV,"HOME":str(self.paths.home)},
                                           cwd=self.paths.home,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,start_new_session=True)
                folder: Path | None = None
                try:
                    deadline = time.monotonic()+10
                    while time.monotonic() < deadline:
                        try:
                            calls = self.calls()
                            last = calls[-1] if calls else {}
                            if "--file" in last.get("args",[]) and last["args"][last["args"].index("--file")+1].endswith("migrate.sql"):
                                candidate = Path(last["cwd"])
                                if (candidate / "private.copy").exists():
                                    folder = candidate
                                    break
                        except (FileNotFoundError, json.JSONDecodeError):
                            pass
                        if process.poll() is not None:
                            break
                        time.sleep(0.02)
                    self.assertIsNotNone(folder, "The real CLI never reached its running migration client.")
                    os.kill(process.pid, number)
                    out, err = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 1, out+err)
                    self.assertEqual(json.loads(out)["error"]["code"], "operation_failed")
                    with self.assertRaises(ProcessLookupError):
                        os.kill(last["pid"], 0)
                    assert folder is not None
                    self.assertFalse(folder.exists())
                    self.assertEqual(json.loads((self.paths.roots / "second/root.json").read_text())["status"], "preparing")
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=5)
