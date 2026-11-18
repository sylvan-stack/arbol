"""Individually selected top-tier cases. Shared fixtures retain their original paths."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))

import psycopg  # noqa: E402
from backend.support import Cluster  # noqa: E402

CHAT_A = UUID(int=0xA)
CHAT_B = UUID(int=0xB)
EXCHANGE = """INSERT INTO public.exchanges (id, chat_id, number, state, trunk, build, route, working_folder,
                                           accepted_at, ended_at)
              VALUES (%s, %s, %s, 'completed', 'imported', '0', '{}', '/', now(), now())"""


class ImportedChats(unittest.TestCase):
    """Revision 3's insert trigger on `exchanges` (IMP-0.16) on the canonical baseline of a private cluster."""

    def setUp(self) -> None:
        self.cluster = Cluster(baseline=ROOT)
        self.addCleanup(self.cluster.close)
        revision = (ROOT / "database/003-session-imports.sql").read_bytes()
        self.cluster.sql(b"BEGIN;\n" + revision + b"\nCOMMIT;\n")
        self.cluster.sql(
            f"INSERT INTO public.chats (id, created_at) VALUES ('{CHAT_A}', now()), ('{CHAT_B}', now());"
            f"INSERT INTO public.chat_imports (chat_id, tool, native_id, kind, origin, manifest, first_imported,"
            f" last_imported) VALUES ('{CHAT_A}', 'codex', 'fictional-session', 'owner', '{{}}', '{'0' * 64}',"
            f" now(), now());".encode())
        # One session throughout; each `transaction()` is an explicit BEGIN … COMMIT or ROLLBACK.
        self.connection = psycopg.connect(self.cluster.address, autocommit=True)
        self.addCleanup(self.connection.close)
        self.number = 0

    def insert(self, chat: UUID) -> None:
        self.number += 1
        self.connection.execute(EXCHANGE, (UUID(int=self.number), chat, self.number))

    def test_import_bypass_ends_with_its_transaction(self) -> None:
        """IMP-0.16: only the importer's own transaction, with SET LOCAL arbol.importing = 'on', adds an Exchange to
        an imported chat. A bypass that outlived that transaction would let a later send on the same pooled session
        add an Exchange to an imported chat."""
        with self.assertRaises(psycopg.errors.RaiseException) as refused:
            with self.connection.transaction():
                self.insert(CHAT_A)
        self.assertEqual((refused.exception.sqlstate, refused.exception.diag.message_primary), ("P0001", "imported_chat"))
        with self.connection.transaction():
            self.insert(CHAT_B)
        with self.connection.transaction():
            self.connection.execute("SET LOCAL arbol.importing = 'on'")
            self.insert(CHAT_A)
        with self.assertRaises(psycopg.errors.RaiseException) as again:
            with self.connection.transaction():
                setting = self.connection.execute("SELECT current_setting('arbol.importing', true)").fetchone()
                self.assertEqual(setting, ("",))
                self.insert(CHAT_A)
        self.assertEqual((again.exception.sqlstate, again.exception.diag.message_primary), ("P0001", "imported_chat"))
        with self.connection.transaction():
            rows = self.connection.execute(
                "SELECT chat_id, count(*) FROM public.exchanges GROUP BY chat_id ORDER BY chat_id").fetchall()
        self.assertEqual(rows, [(CHAT_A, 1), (CHAT_B, 1)])
