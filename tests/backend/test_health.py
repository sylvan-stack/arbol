"""Actual private connection loss and classified failures keep attention available."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from backend.test_chat_wire import WindowFixture  # noqa: E402


class Availability(WindowFixture):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/backend/test_health.py::Availability.test_actual_loss_opens_attention_for_two_windows_and_probe_return_closes_it
#     async def test_actual_loss_opens_attention_for_two_windows_and_probe_return_closes_it(self) -> None:
#         """recovery.database-loss; recovery.attention; recovery.return"""
#         clients = [await self.open(), await self.open()]
#         for index, (r, w) in enumerate(clients):
#             snapshot = await self.subscribe(r, w, str(index), "attention", {})
#             self.assertNotIn("database_unreachable", [item["id"] for item in snapshot["items"]])
#         await offline(self.cluster)
#         before = time.monotonic()
#         with self.assertRaises(Refused) as caught:
#             await self.backend.database.execute("SELECT 1")
#         self.assertEqual(caught.exception.code, "database_unavailable")
#         self.assertLess(time.monotonic()-before, 5)
#         self.assertTrue(self.backend.database.away)
#         since = self.backend.chats.attention.items["database_unreachable"]["since"]
#         for index, (r, _) in enumerate(clients):
#             opened = await self.event(r, str(index), "opened")
#             self.assertEqual(opened["item"]["kind"], "database_unreachable")
#             self.assertIn("answers in progress go on", opened["item"]["message"])
#         r, w = await self.open()
#         before = time.monotonic()
#         snapshot = await self.subscribe(r, w, "late", "attention", {})
#         self.assertLess(time.monotonic()-before, 0.5)
#         self.assertEqual(snapshot["items"][0]["since"], since)
#         await online(self.cluster)
#         await self.backend.health.probe()
#         self.assertFalse(self.backend.database.away)
#         for index, (r, _) in enumerate(clients):
#             self.assertEqual((await self.event(r, str(index), "closed"))["id"], "database_unreachable")
#         self.assertEqual(await self.backend.database.execute("SELECT 42"), [(42,)])
# TEST-TIER-DISABLED-END tests/backend/test_health.py::Availability.test_actual_loss_opens_attention_for_two_windows_and_probe_return_closes_it

# TEST-TIER-DISABLED-BEGIN tests/backend/test_health.py::Availability.test_statement_timeout_or_sql_refusal_does_not_mark_a_server_away
#     async def test_statement_timeout_or_sql_refusal_does_not_mark_a_server_away(self) -> None:
#         """recovery.statement-timeout; recovery.sql-error-is-not-loss"""
#         self.backend.database.seconds = 0.08
#         with self.assertRaises(Refused) as caught:
#             await self.backend.database.execute("SELECT pg_sleep(3)")
#         self.assertEqual(caught.exception.code, "timeout")
#         self.assertFalse(self.backend.database.away)
#         with self.assertRaises(Refused):
#             await self.backend.database.execute("SELECT no_such_private_column")
#         self.assertFalse(self.backend.database.away)
#         self.assertNotIn("database_unreachable", self.backend.chats.attention.items)
#         self.assertEqual(await self.backend.database.execute("SELECT 1"), [(1,)])
# TEST-TIER-DISABLED-END tests/backend/test_health.py::Availability.test_statement_timeout_or_sql_refusal_does_not_mark_a_server_away

# TEST-TIER-DISABLED-BEGIN tests/backend/test_health.py::Availability.test_connection_deadline_is_unavailable_and_the_whole_probe_is_bounded
#     async def test_connection_deadline_is_unavailable_and_the_whole_probe_is_bounded(self) -> None:
#         """recovery.connection-deadline; recovery.probe-bound"""
#         self.assertEqual((SECONDS, RETRY), (5, 5))
#         writers: list[asyncio.StreamWriter] = []
#         def stalled(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
#             writers.append(writer)
#         server = await asyncio.start_server(stalled, "127.0.0.1", 0)
#         address = f"postgresql://bkd@127.0.0.1:{server.sockets[0].getsockname()[1]}/arbol_test"
#         db = Database(replace(self.backend.identity, database=address), seconds=0.12)
#         attention = Attention()
#         health = Health(db, attention)
#         try:
#             before = time.monotonic()
#             await health.probe()
#             self.assertLess(time.monotonic()-before, 0.4)
#             self.assertTrue(db.away)
#             self.assertEqual(attention.items["database_unreachable"]["kind"], "database_unreachable")
#             with self.assertRaises(Refused) as caught:
#                 await db.execute("SELECT 1")
#             self.assertEqual(caught.exception.code, "database_unavailable")
#         finally:
#             await health.close()
#             await db.close()
#             server.close()
#             for writer in writers:
#                 writer.close()
#             server.close_clients()
#             await server.wait_closed()
# TEST-TIER-DISABLED-END tests/backend/test_health.py::Availability.test_connection_deadline_is_unavailable_and_the_whole_probe_is_bounded

# TEST-TIER-DISABLED-BEGIN tests/backend/test_health.py::Availability.test_keychain_failure_timeout_exit44_and_secrets_are_classified_without_owner_lookup
#     async def test_keychain_failure_timeout_exit44_and_secrets_are_classified_without_owner_lookup(self) -> None:
#         """recovery.keychain-classification; recovery.safe-cause"""
#         folder = self.frame.home / ".arbol"
#         folder.mkdir()
#         (folder / "database.json").write_text('{"address":"postgresql://bkd@127.0.0.1:5433"}')
#         for failure, expected in ((Refused("timeout", "fictional-private-password"), "Keychain did not answer"),
#                                   (Refused("database_unavailable", "fictional-private-password"), "Keychain lookup failed")):
#             db = Database(replace(self.backend.identity, home=self.frame.home, database=None))
#             attention = Attention()
#             health = Health(db, attention)
#             try:
#                 with mock.patch("arbol_backend.database.password", side_effect=failure) as lookup:
#                     await health.probe()
#                 self.assertEqual(lookup.call_count, 1)
#                 self.assertIn(expected, attention.items["database_unreachable"]["message"])
#                 self.assertNotIn("fictional-private-password", json.dumps(attention.items))
#             finally:
#                 await health.close()
#                 await db.close()
#         db = Database(replace(self.backend.identity, home=self.frame.home, database=None))
#         attention = Attention()
#         health = Health(db, attention)
#         try:
#             with mock.patch("arbol_backend.database.password", return_value=""), mock.patch(
#                     "arbol_backend.database.AsyncConnection.connect", side_effect=psycopg.OperationalError("fictional-private-password")):
#                 await health.probe()
#             self.assertNotIn("Keychain", attention.items["database_unreachable"]["message"])
#             self.assertNotIn("fictional-private-password", json.dumps(attention.items))
#         finally:
#             await health.close()
#             await db.close()
# TEST-TIER-DISABLED-END tests/backend/test_health.py::Availability.test_keychain_failure_timeout_exit44_and_secrets_are_classified_without_owner_lookup

# TEST-TIER-DISABLED-BEGIN tests/backend/test_health.py::Availability.test_failed_configuration_can_be_corrected_and_retry_re_resolves_it
#     async def test_failed_configuration_can_be_corrected_and_retry_re_resolves_it(self) -> None:
#         """recovery.credentials-refresh; recovery.retry-cadence"""
#         db = Database(self.backend.identity, seconds=0.15)
#         attention = Attention()
#         health = Health(db, attention, retry=0.08)
#         from arbol_backend.database import credentials
#         parameters = await credentials(db.identity)
#         attempts: list[float] = []
#         async def resolve(identity: object) -> dict[str, str]:
#             attempts.append(time.monotonic())
#             if len(attempts) == 1:
#                 raise Refused("database_unavailable", "private cause")
#             return parameters
#         try:
#             with mock.patch("arbol_backend.database.credentials", side_effect=resolve):
#                 health.start()
#                 async with asyncio.timeout(2):
#                     while len(attempts) < 2 or db.away:
#                         await asyncio.sleep(0.01)
#             self.assertGreaterEqual(attempts[1]-attempts[0], 0.07)
#             self.assertFalse(db.away)
#             self.assertNotIn("database_unreachable", attention.items)
#         finally:
#             await health.close()
#             await db.close()
# TEST-TIER-DISABLED-END tests/backend/test_health.py::Availability.test_failed_configuration_can_be_corrected_and_retry_re_resolves_it

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:5
# import asyncio
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:5
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:6
# import json
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:6
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:8
# import time
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:8
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:9
# from dataclasses import replace
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:9
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:11
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:11
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:13
# import psycopg
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:13
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:19
# from arbol_backend.database import SECONDS, Database  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:19
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:20
# from arbol_backend.health import RETRY, Health  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:20
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:21
# from arbol_backend.metadata import Attention  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:21
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:22
# from arbol_backend.model import Refused  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:22
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_health.py:23
# from backend.recovery_support import offline, online  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_health.py:23
