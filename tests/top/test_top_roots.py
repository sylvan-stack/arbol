"""Individually selected top-tier cases. Shared fixtures retain their original paths."""
from __future__ import annotations

import test_roots as _support
from test_roots import (
    Creation,
    Database,
    DatabaseError,
    catalogue,
    json,
    record,
)


class DatabaseAccess(_support.DatabaseAccess):
    def test_roots_creation_retains_a_recovery_receipt_for_uncertain_outcomes_or_failed_rollback(self) -> None:
        """roots.creation-recovery: never drop a database after an uncertain CREATE or claim rollback succeeded."""
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain):
                paths = self.fixture()
                database = Database(paths)
                if uncertain:
                    (paths.home / "psql.json").write_text(json.dumps({"status": 2, "stderr": "lost connection"}))
                with self.assertRaisesRegex(DatabaseError, "recovery files are kept"):
                    with Creation(paths, record()) as attempt:
                        attempt.make_database(database)
                        (paths.home / "psql.json").write_text(json.dumps({"status": 3, "stderr": "drop refused"}))
                        raise RuntimeError("private local failure")
                self.assertTrue((paths.roots / "sapling/.creating.json").is_file())
                self.assertFalse((paths.roots / "sapling/root.json").exists())
                self.assertEqual(catalogue(paths), [])
                calls = [json.loads(line) for line in (paths.home / "calls.jsonl").read_text().splitlines()]
                self.assertEqual(len([row for row in calls if row["kind"] == "psql"]), 1 if uncertain else 2)
