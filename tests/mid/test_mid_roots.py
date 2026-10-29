"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import test_roots as _support
from test_roots import (Callable ,Creation ,Database ,Path ,ROOT ,Refused ,catalogue_lock ,database_fixture ,json ,mock ,os ,record ,remove ,roots_command ,save_record ,subprocess ,sys ,tempfile)


class Commands(_support.Commands):


# TEST-TIER-BEGIN tests/test_roots.py::Commands.test_roots_remove_database_failure_or_duplicate_claim_preserves_all_files
    def test_roots_remove_database_failure_or_duplicate_claim_preserves_all_files(self) -> None:
        """roots.remove-refusal: DROP failure, a shared database claim and symlink targets authorize no deletion."""
        paths = database_fixture(self)
        self.assertEqual(roots_command(paths, "create", "sapling", "--name", "First").returncode, 0)
        (paths.settings / "sapling/arbol.json").write_text("private settings")
        before = (paths.roots / "sapling/root.json").read_bytes()
        (paths.home / "psql.json").write_text(json.dumps({"status": 3, "stderr": "database has open connections"}))
        refused = roots_command(paths, "remove", "sapling")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(json.loads(refused.stdout)["error"]["code"], "database_unavailable")
        self.assertEqual((paths.roots / "sapling/root.json").read_bytes(), before)
        self.assertEqual((paths.settings / "sapling/arbol.json").read_text(), "private settings")
        (paths.roots / "second").mkdir()
        save_record(paths, {**record("second"), "database": "arbol_sapling"}, complete=True)
        calls_before = (paths.home / "calls.jsonl").read_bytes()
        refused = roots_command(paths, "remove", "sapling")
        self.assertEqual(json.loads(refused.stdout)["error"]["code"], "invalid_input")
        self.assertEqual((paths.home / "calls.jsonl").read_bytes(), calls_before)
        (paths.roots / "second/root.json").unlink()
        target = paths.home / "elsewhere"
        (paths.settings / "sapling").rename(target)
        (paths.settings / "sapling").symlink_to(target, target_is_directory=True)
        refused = roots_command(paths, "remove", "sapling")
        self.assertEqual(json.loads(refused.stdout)["error"]["code"], "invalid_input")
        self.assertEqual((paths.home / "calls.jsonl").read_bytes(), calls_before)
        self.assertEqual((target / "arbol.json").read_text(), "private settings")
# TEST-TIER-END tests/test_roots.py::Commands.test_roots_remove_database_failure_or_duplicate_claim_preserves_all_files

# TEST-TIER-BEGIN tests/test_roots.py::Commands.test_roots_remove_reports_partial_filesystem_cleanup_and_can_be_retried
    def test_roots_remove_reports_partial_filesystem_cleanup_and_can_be_retried(self) -> None:
        """roots.remove-retry: a completed DROP with failed folder cleanup retains its record for a truthful retry."""
        paths = database_fixture(self)
        self.assertEqual(roots_command(paths, "create", "sapling", "--name", "First").returncode, 0)
        with mock.patch("arbol_roots.operations.shutil.rmtree", side_effect=PermissionError("private cleanup failure")):
            with self.assertRaisesRegex(Refused, "database was removed.*cleanup.*incomplete"):
                remove(paths, "sapling")
        self.assertTrue((paths.roots / "sapling/root.json").exists())
        retried = roots_command(paths, "remove", "sapling")
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertFalse((paths.roots / "sapling").exists())
# TEST-TIER-END tests/test_roots.py::Commands.test_roots_remove_reports_partial_filesystem_cleanup_and_can_be_retried


class DatabaseAccess(_support.DatabaseAccess):


# TEST-TIER-BEGIN tests/test_roots.py::DatabaseAccess.test_roots_creation_cannot_redirect_publication_or_rollback_by_changing_its_record
    def test_roots_creation_cannot_redirect_publication_or_rollback_by_changing_its_record(self) -> None:
        """roots.creation-identity: the confirmed database, never later mutable metadata, is the rollback target."""
        paths = self.fixture()
        with self.assertRaisesRegex(Refused, "identity cannot change"):
            with Creation(paths, record()) as attempt:
                attempt.make_database(Database(paths))
                attempt.record["database"] = "some_other_database"
                attempt.publish()
        calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
        sql = [row["args"][-1] for row in calls if row["kind"] == "psql"]
        self.assertEqual(sql[-1], 'DROP DATABASE IF EXISTS "arbol_sapling"')
        self.assertFalse(any("some_other_database" in statement for statement in sql))
        self.assertFalse((paths.roots / "sapling").exists())
# TEST-TIER-END tests/test_roots.py::DatabaseAccess.test_roots_creation_cannot_redirect_publication_or_rollback_by_changing_its_record

# TEST-TIER-BEGIN tests/test_roots.py::DatabaseAccess.test_roots_catalogue_mutations_exclude_another_process_and_release_the_lock
    def test_roots_catalogue_mutations_exclude_another_process_and_release_the_lock(self) -> None:
        """roots.catalogue-lock: another process is busy while held, then acquires after release."""
        paths = self.fixture()
        script = ("import json,sys\n" + f"sys.path.insert(0,{str(ROOT / 'src')!r})\n"
                  "from arbol_roots.model import places,Refused\n"
                  "from arbol_roots.operations import catalogue_lock\n"
                  "try:\n"
                  f" with catalogue_lock(places({{'--roots-dir': {str(paths.roots)!r}}})):\n"
                  "  print('acquired')\n"
                  "except Refused as e:\n"
                  " print(e.code);sys.exit(1)\n")
        with catalogue_lock(paths):
            result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, timeout=20, check=False)
            self.assertEqual((result.returncode, result.stdout), (1, b"busy\n"))
        result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, timeout=20, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, b"acquired\n"))
# TEST-TIER-END tests/test_roots.py::DatabaseAccess.test_roots_catalogue_mutations_exclude_another_process_and_release_the_lock


class Catalogue(_support.Catalogue):
# TEST-TIER-BEGIN tests/test_roots.py::Catalogue.test_roots_install_package_preserves_its_previous_version_on_compile_failure_or_interrupted_rename
    def test_roots_install_package_preserves_its_previous_version_on_compile_failure_or_interrupted_rename(self) -> None:
        """roots.install-rollback: both global packages retain their earlier directory when staging cannot commit."""
        sys.path.insert(0, str(ROOT / "scripts"))
        import install_builds

        for name in ("arbol_builds", "arbol_roots"):
            for interrupted in (False, True):
                with self.subTest(package=name, interrupted=interrupted), tempfile.TemporaryDirectory() as temporary:
                    library = Path(temporary)
                    package = library / name
                    package.mkdir()
                    (package / "previous").write_text("previous version")
                    renamed = Path.rename

                    def rename(path: Path, target: str | os.PathLike[str], *, package_name: str = name,
                               original: Callable[[Path, str | os.PathLike[str]], Path] = renamed) -> Path:
                        if path.name.startswith("." + package_name + "-") and "-previous-" not in path.name:
                            raise SystemExit("private interrupted rename")
                        return original(path, target)

                    if interrupted:
                        with mock.patch.object(install_builds, "run_group"), mock.patch.object(Path, "rename", rename):
                            with self.assertRaisesRegex(SystemExit, "interrupted rename"):
                                install_builds.install_package(library, Path(sys.executable), name)
                    else:
                        with mock.patch.object(install_builds, "run_group", side_effect=ValueError("compile failure")):
                            with self.assertRaisesRegex(ValueError, "compile failure"):
                                install_builds.install_package(library, Path(sys.executable), name)
                    self.assertEqual((package / "previous").read_text(), "previous version")
                    self.assertEqual(list(library.iterdir()), [package])
# TEST-TIER-END tests/test_roots.py::Catalogue.test_roots_install_package_preserves_its_previous_version_on_compile_failure_or_interrupted_rename
