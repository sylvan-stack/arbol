"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_roots_sql as _support
from test_roots_sql import (Path ,Refused ,image ,json ,os ,selected_sql ,signal ,subprocess ,sys ,test_roots ,time)


class Selection(_support.Selection):

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


class Migration(_support.Migration):


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
