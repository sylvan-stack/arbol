"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_roots_sql as _support
from test_roots_sql import (
    Any,
    Database,
    DatabaseError,
    InUseModes,
    Layout,
    Migration,
    Path,
    Places,
    ROOT,
    Refused,
    Selection,
    databases,
    hashlib,
    image,
    json,
    layout,
    migrate,
    mock,
    open_use_guard,
    os,
    save_record,
    selected_sql,
    signal,
    subprocess,
    sys,
    test_roots,
    time,
    unittest,
)


class Selection(_support.Selection):
# TEST-TIER-BEGIN tests/test_roots_sql.py::Selection.test_newest_working_same_root_with_sql_is_selected_and_guarded
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
# TEST-TIER-END tests/test_roots_sql.py::Selection.test_newest_working_same_root_with_sql_is_selected_and_guarded

# TEST-TIER-BEGIN tests/test_roots_sql.py::Selection.test_damaged_selected_files_or_manifest_fail_without_older_fallback
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
# TEST-TIER-END tests/test_roots_sql.py::Selection.test_damaged_selected_files_or_manifest_fail_without_older_fallback

# TEST-TIER-BEGIN tests/test_roots_sql.py::Selection.test_pruner_lock_refuses_and_migration_requires_its_extra_file
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
# TEST-TIER-END tests/test_roots_sql.py::Selection.test_pruner_lock_refuses_and_migration_requires_its_extra_file

# TEST-TIER-BEGIN tests/test_roots_sql.py::Selection.test_database_aliases_and_connection_string_forms_are_refused
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
# TEST-TIER-END tests/test_roots_sql.py::Selection.test_database_aliases_and_connection_string_forms_are_refused



class Layout(_support.Layout):
# TEST-TIER-BEGIN tests/test_roots_sql.py::Layout.test_layout_runs_two_transactions_minimal_environment_and_keeps_metadata
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
# TEST-TIER-END tests/test_roots_sql.py::Layout.test_layout_runs_two_transactions_minimal_environment_and_keeps_metadata

# TEST-TIER-BEGIN tests/test_roots_sql.py::Layout.test_sql_error_statuses_name_failure_redact_password_and_stop_immediately
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
# TEST-TIER-END tests/test_roots_sql.py::Layout.test_sql_error_statuses_name_failure_redact_password_and_stop_immediately

# TEST-TIER-BEGIN tests/test_roots_sql.py::Layout.test_preparing_missing_tool_or_damaged_sql_runs_no_psql
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
# TEST-TIER-END tests/test_roots_sql.py::Layout.test_preparing_missing_tool_or_damaged_sql_runs_no_psql

# TEST-TIER-BEGIN tests/test_roots_sql.py::Layout.test_layout_cli_is_json_and_needs_no_older_root_or_database
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
# TEST-TIER-END tests/test_roots_sql.py::Layout.test_layout_cli_is_json_and_needs_no_older_root_or_database

# TEST-TIER-BEGIN tests/test_roots_sql.py::Layout.test_file_timeout_is_a_bounded_uncertain_database_failure
    def test_file_timeout_is_a_bounded_uncertain_database_failure(self) -> None:
        """roots.sql-timeout"""
        database = Database(self.paths)
        with mock.patch("arbol_roots.database.subprocess.run", side_effect=subprocess.TimeoutExpired("psql", 60)):
            with self.assertRaisesRegex(DatabaseError, "60 seconds") as error:
                database.file("arbol_sapling", self.folder / "layout/chat-tables.sql")
        self.assertTrue(error.exception.uncertain)
# TEST-TIER-END tests/test_roots_sql.py::Layout.test_file_timeout_is_a_bounded_uncertain_database_failure



class Migration(_support.Migration):
# TEST-TIER-BEGIN tests/test_roots_sql.py::Migration.test_migration_recreates_then_runs_files_in_order_and_cleans_private_copies
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
# TEST-TIER-END tests/test_roots_sql.py::Migration.test_migration_recreates_then_runs_files_in_order_and_cleans_private_copies

# TEST-TIER-BEGIN tests/test_roots_sql.py::Migration.test_failed_migration_names_file_and_leaves_preparing_with_no_copy_directory
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
# TEST-TIER-END tests/test_roots_sql.py::Migration.test_failed_migration_names_file_and_leaves_preparing_with_no_copy_directory

# TEST-TIER-BEGIN tests/test_roots_sql.py::Migration.test_nonpreparing_or_incomplete_input_never_reaches_psql
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
# TEST-TIER-END tests/test_roots_sql.py::Migration.test_nonpreparing_or_incomplete_input_never_reaches_psql

# TEST-TIER-BEGIN tests/test_roots_sql.py::Migration.test_interrupted_file_runner_still_removes_its_private_directory
    def test_interrupted_file_runner_still_removes_its_private_directory(self) -> None:
        """roots.migrate-interruption"""
        before = {number:signal.getsignal(number) for number in [signal.SIGINT, signal.SIGTERM]}
        with mock.patch.object(Database, "file", side_effect=[None,None,KeyboardInterrupt]) as calls:
            with self.assertRaises(KeyboardInterrupt):
                migrate(self.paths, "second")
        self.assertFalse(calls.call_args.kwargs["cwd"].exists())
        self.assertEqual({number:signal.getsignal(number) for number in before}, before)
        self.assertEqual(json.loads((self.paths.roots / "second/root.json").read_text())["status"], "preparing")
# TEST-TIER-END tests/test_roots_sql.py::Migration.test_interrupted_file_runner_still_removes_its_private_directory

# TEST-TIER-BEGIN tests/test_roots_sql.py::Migration.test_real_cli_signals_reap_the_sql_child_and_remove_private_copies
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
# TEST-TIER-END tests/test_roots_sql.py::Migration.test_real_cli_signals_reap_the_sql_child_and_remove_private_copies



class InUseModes(_support.InUseModes):
# TEST-TIER-BEGIN tests/test_roots_sql.py::InUseModes.test_check_and_chat_run_only_selected_script_without_drop_layout_or_metadata_write
    def test_check_and_chat_run_only_selected_script_without_drop_layout_or_metadata_write(self) -> None:
        """roots.migrate-in-use"""
        before = {root:(self.paths.roots/root/"root.json").read_bytes() for root in ["sapling","second"]}
        for mode in ["check","chat"]:
            self.configure(self.result(mode))
            with mock.patch("arbol_roots.database.subprocess.run",wraps=subprocess.run) as calls:
                reply = migrate(self.paths,"second",check=mode=="check",chat=self.CHAT if mode=="chat" else None)
            self.assertEqual(reply,{"root":"second","rootBuild":"1",**self.result(mode)})
            self.assertEqual(len(calls.call_args_list),2)  # Keychain and one psql file, no maintenance connection.
            called = calls.call_args
            args = called.args[0]
            self.assertIn("arbol_migrate_check=1" if mode=="check" else "arbol_migrate_chat="+self.CHAT,args)
            self.assertIn("from_database=arbol_sapling",args)
            self.assertNotIn("--single-transaction",args)
            self.assertFalse(called.kwargs["cwd"].exists())
        for root,content in before.items():
            self.assertEqual((self.paths.roots/root/"root.json").read_bytes(),content)
# TEST-TIER-END tests/test_roots_sql.py::InUseModes.test_check_and_chat_run_only_selected_script_without_drop_layout_or_metadata_write

# TEST-TIER-BEGIN tests/test_roots_sql.py::InUseModes.test_capability_damage_unknown_versions_and_legacy_modes_refuse_before_any_client
    def test_capability_damage_unknown_versions_and_legacy_modes_refuse_before_any_client(self) -> None:
        """roots.migrate-capabilities"""
        path = self.folder/"layout/migration-modes.json"
        for damage in ["missing","hash","symlink","boolean","unknown","legacy"]:
            self.capability()
            if damage=="missing":
                path.unlink()
            elif damage=="hash":
                path.write_text('{"changed":true}')
            elif damage=="symlink":
                path.unlink()
                path.symlink_to(self.paths.home/"psql.json")
            else:
                manifest = json.loads((self.folder/"package-manifest.json").read_text())
                if damage=="legacy":
                    manifest["layout"].pop("migrationModes")
                else:
                    manifest["layout"]["migrationModes"]["version"] = True if damage=="boolean" else 2
                    path.write_text(json.dumps(manifest["layout"]["migrationModes"]))
                    manifest["files"]["layout/migration-modes.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
                (self.folder/"package-manifest.json").write_text(json.dumps(manifest))
            with self.subTest(damage=damage),self.assertRaises(Refused) as caught:
                migrate(self.paths,"second",check=True)
            self.assertEqual(caught.exception.code,"build_unavailable")
            path.unlink(missing_ok=True)
        self.assertFalse((self.paths.home/"calls.jsonl").exists())
# TEST-TIER-END tests/test_roots_sql.py::InUseModes.test_capability_damage_unknown_versions_and_legacy_modes_refuse_before_any_client

# TEST-TIER-BEGIN tests/test_roots_sql.py::InUseModes.test_mutual_flags_states_lineage_and_noncanonical_uuid_refuse_without_psql
    def test_mutual_flags_states_lineage_and_noncanonical_uuid_refuse_without_psql(self) -> None:
        """roots.migrate-mode-input"""
        for args in [("--check","--chat",self.CHAT),("--chat","ABC"),("--chat",self.CHAT.upper()),
                     ("--check=true",),("--chat",),("--check","--check")]:
            if args==("--chat",self.CHAT.upper()) and self.CHAT.upper()==self.CHAT:
                continue
            answer = test_roots.roots_command(self.paths,"migrate","second",*args)
            self.assertEqual(answer.returncode,1)
            self.assertEqual(json.loads(answer.stdout)["error"]["code"],"invalid_input")
        for value in [{**self.record,"status":"preparing"},test_roots.record("second",state="working")]:
            save_record(self.paths,value)
            with self.assertRaises(Refused):
                migrate(self.paths,"second",check=True)
        self.assertFalse((self.paths.home/"calls.jsonl").exists())
# TEST-TIER-END tests/test_roots_sql.py::InUseModes.test_mutual_flags_states_lineage_and_noncanonical_uuid_refuse_without_psql

# TEST-TIER-BEGIN tests/test_roots_sql.py::InUseModes.test_sqlstate_unknown_chat_and_busy_are_structured_and_bad_results_require_inspection
    def test_sqlstate_unknown_chat_and_busy_are_structured_and_bad_results_require_inspection(self) -> None:
        """roots.migrate-mode-errors"""
        for state,code in [("P0002","unknown_chat"),("55P03","busy"),("40P01","busy"),("42P01","database_unavailable")]:
            self.configure(None,status=3,stderr=f"psql:/fixture/migrate.sql:35: ERROR:  {state}: fictional refusal\nLOCATION: secret internal")
            answer = test_roots.roots_command(self.paths,"migrate","second","--chat",self.CHAT)
            self.assertEqual(answer.returncode,1)
            error = json.loads(answer.stdout)["error"]
            self.assertEqual(error["code"],code)
            if code=="unknown_chat":
                self.assertIn(self.CHAT,error["message"])
            self.assertNotIn("LOCATION",error["message"])
        for result in [None,{**self.result(),"chat":"wrong"},{**self.result(),"action":"copied"},
                       {**self.result(),"endedThrough":True},{**self.result(),"snapshotAt":"2026-10-27"},
                       {**self.result("check"),"checked":True},self.result("check")|{"stale":[self.CHAT,self.CHAT]}]:
            self.configure(result)
            with self.assertRaises(Refused) as error:
                migrate(self.paths,"second",check=isinstance(result,dict) and result.get("mode")=="check",
                        chat=None if isinstance(result,dict) and result.get("mode")=="check" else self.CHAT)
            self.assertEqual(error.exception.code,"operation_failed")
            self.assertIn("inspect",str(error.exception))
        self.configure(self.result(action="copied"))
        self.assertEqual(migrate(self.paths,"second",chat=self.CHAT)["action"],"copied")
# TEST-TIER-END tests/test_roots_sql.py::InUseModes.test_sqlstate_unknown_chat_and_busy_are_structured_and_bad_results_require_inspection

# TEST-TIER-BEGIN tests/test_roots_sql.py::InUseModes.test_in_use_file_failure_and_signals_keep_state_neutral_cleanup
    def test_in_use_file_failure_and_signals_keep_state_neutral_cleanup(self) -> None:
        """roots.migrate-mode-cleanup"""
        header = (self.paths.roots/"second/root.json").read_bytes()
        for failure in [KeyboardInterrupt(),DatabaseError("timeout",uncertain=True),
                        Refused("operation_failed","Migration interrupted by SIGTERM; the Root record was not changed.")]:
            with mock.patch.object(Database,"file",side_effect=failure) as call:
                with self.assertRaises(type(failure)):
                    migrate(self.paths,"second",check=True)
            self.assertFalse(call.call_args.kwargs["cwd"].exists())
            self.assertEqual((self.paths.roots/"second/root.json").read_bytes(),header)
# TEST-TIER-END tests/test_roots_sql.py::InUseModes.test_in_use_file_failure_and_signals_keep_state_neutral_cleanup
