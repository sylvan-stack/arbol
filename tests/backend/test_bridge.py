"""Private socket and PostgreSQL qualification of BKD-1; never use owner credentials."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/site-packages"))
sys.path.insert(0, str(ROOT / "tests"))
from arbol_backend.bridge import (  # noqa: E402
    MAX_LINE,
    Connection,
    Params,
    Registry,
    decode,
    encode,
)
from arbol_backend.model import identity, parse  # noqa: E402
from arbol_backend.server import Backend  # noqa: E402
from backend.support import TEST_BUILD, TEST_ROOT  # noqa: E402
from backend.support import Frame as PrivateRoot  # noqa: E402


class Wire(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = PrivateRoot()
        self.registry = Registry()
        self.connections: list[Connection] = []
        self.work: list[asyncio.Task[None]] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.header = {"type": "hello", "bridge": 1, "root": {"root": TEST_ROOT, "name": "Test Root",
                       "status": "working", "current": True}, "build": TEST_BUILD}
        async def hello() -> Params:
            return self.header
        def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            connection = Connection(reader, writer, self.registry)
            self.connections.append(connection)
            self.work.append(asyncio.create_task(connection.run(hello)))
        self.server = await asyncio.start_unix_server(
            connected, path=str(self.fixture.root / "wire.sock"), limit=MAX_LINE - 1
        )

    async def asyncTearDown(self) -> None:
        for writer in self.writers:
            writer.close()
        self.server.close()
        self.server.close_clients()
        for task in self.work:
            task.cancel()
        await asyncio.gather(*self.work, return_exceptions=True)
        await self.server.wait_closed()
        self.fixture.close()

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(
            str(self.fixture.root / "wire.sock"), limit=MAX_LINE - 1
        )
        self.writers.append(writer)
        self.assertEqual(await self.read(reader), self.header)
        return reader, writer

    async def read(self, reader: asyncio.StreamReader, seconds: float = 2) -> Params:
        async with asyncio.timeout(seconds):
            return decode(await reader.readuntil(b"\n"))

    async def send(self, writer: asyncio.StreamWriter, message: Params) -> None:
        writer.write(encode(message))
        await writer.drain()

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_complete_line_boundary_and_hello_first
#     async def test_complete_line_boundary_and_hello_first(self) -> None:
#         """bridge.frames"""
#         reader, writer = await self.open()
#         prefix = b'{"type":"call","id":"limit","method":"unknown","future":"'
#         suffix = b'"}\n'
#         exact = prefix + b'x' * (MAX_LINE - len(prefix) - len(suffix)) + suffix
#         self.assertEqual(len(exact), MAX_LINE)
#         writer.write(exact)
#         await writer.drain()
#         reply = await self.read(reader)
#         self.assertEqual(reply["error"]["code"], "unknown_method")
#         writer.write(exact[:-1] + b' \n')
#         try:
#             await writer.drain()
#         except ConnectionError:
#             pass
#         self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
#         self.assertEqual(len(encode({"x": "x" * (MAX_LINE - len(b'{"x":""}\n'))})), MAX_LINE)
#         with self.assertRaises(Refused):
#             encode({"x": "x" * MAX_LINE})
#         await self.open()  # A malformed window did not end the server.
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_complete_line_boundary_and_hello_first

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_malformed_frames_close_privately
#     async def test_malformed_frames_close_privately(self) -> None:
#         """bridge.malformed"""
#         for data in (b'[]\n', b'{"type":"call","type":"other"}\n', b'{"x":NaN}\n', b'{"x":1e999}\n', b'\xff\n',
#                      b'{bad secret-token}\n', b'{"type":"call","id":null}\n'):
#             reader, writer = await self.open()
#             writer.write(data)
#             await writer.drain()
#             self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
#         reader, writer = await self.open()
#         writer.write(b'{"type":"call"')
#         writer.write_eof()
#         self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_malformed_frames_close_privately

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_calls_independent_one_reply_and_additive_fields
#     async def test_calls_independent_one_reply_and_additive_fields(self) -> None:
#         """bridge.calls; bridge.compatibility; bridge.errors"""
#         release = asyncio.Event()
#         async def wait(params: Params) -> Params:
#             await release.wait()
#             return {"done": True}
#         async def fail(params: Params) -> None:
#             raise Refused("database_unavailable", "password=must-not-escape")
#         async def forwarded(params: Params) -> None:
#             raise Error("chat_busy", source="trunk")
#         self.registry.method("wait", wait)
#         self.registry.method("fail", fail)
#         self.registry.method("forward", forwarded)
#         reader, writer = await self.open()
#         for value in ({"type": "future", "secret": "ignored"},
#                       {"type": "call", "id": "slow", "method": "wait", "params": {"future": True}},
#                       {"type": "call", "id": "fast", "method": "absent", "future": "ignored"}):
#             await self.send(writer, value)
#         self.assertEqual((await self.read(reader))["id"], "fast")
#         for id, method, params, code in (("error", "fail", {}, "database_unavailable"),
#                                         ("forward", "forward", {}, "chat_busy"),
#                                         ("bad", "wait", [], "invalid_input")):
#             await self.send(writer, {"type": "call", "id": id, "method": method, "params": params})
#             reply = await self.read(reader)
#             self.assertEqual(reply["error"]["code"], code)
#             self.assertNotIn("must-not-escape", str(reply))
#             self.assertEqual(reply["error"].get("source"), "trunk" if id == "forward" else None)
#         release.set()
#         self.assertEqual((await self.read(reader)), {"type": "reply", "id": "slow", "result": {"done": True}})
#         await self.send(writer, {"type": "call", "id": "receipt", "method": "subscriptions.check"})
#         self.assertEqual((await self.read(reader))["result"], {"subscriptions": []})
#         with self.assertRaises(ValueError):
#             Error("x", source="secret-program")
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_calls_independent_one_reply_and_additive_fields

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_identifiers_before_effects_and_reused_id
#     async def test_identifiers_before_effects_and_reused_id(self) -> None:
#         """bridge.identifiers"""
#         effects: list[Params] = []
#         async def validate(params: Params) -> Params:
#             return {"chat": uuid_id(params.get("chat")), "exchange": uuid_id(params.get("exchange")),
#                     "driver": driver_id(params.get("driver"), {"claude"}),
#                     "subscription": subscription_id(params.get("subscription"), {"test-anthropic"})}
#         async def effect(params: Params) -> Params:
#             effects.append(params)
#             return {}
#         self.registry.method("private.effect", effect, validate)
#         reader, writer = await self.open()
#         valid = {"chat": "aabbccdd-1234-4123-8123-123456789012", "exchange": "00000000-0000-0000-0000-000000000000",
#                  "driver": "claude", "subscription": "test-anthropic"}
#         for index, (key, bad) in enumerate((("chat", "../../x"), ("chat", valid["chat"].upper()),
#                                            ("exchange", 42), ("driver", "../claude"),
#                                            ("driver", "codex"), ("subscription", "unknown"))):
#             await self.send(writer, {"type": "call", "id": str(index), "method": "private.effect",
#                                      "params": {**valid, key: bad}})
#             self.assertEqual((await self.read(reader))["error"]["code"], "invalid_input")
#         self.assertEqual(effects, [])
#         self.assertEqual(self.fixture.calls(), [])
#         await self.send(writer, {"type": "call", "id": "ok", "method": "private.effect", "params": valid})
#         self.assertEqual((await self.read(reader))["result"], {})
#         await self.send(writer, {"type": "call", "id": "ok", "method": "private.effect", "params": valid})
#         self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
#         self.assertEqual(effects, [valid])
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_identifiers_before_effects_and_reused_id

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_registered_snapshot_race_and_cutoff
#     async def test_registered_snapshot_race_and_cutoff(self) -> None:
#         """bridge.snapshot-race"""
#         entered, release = asyncio.Event(), asyncio.Event()
#         async def snapshot(params: Params) -> Snapshot:
#             entered.set()
#             await release.wait()
#             return Snapshot(0, {"kind": "snapshot", "value": 0})
#         topic = Topic(snapshot)
#         self.registry.topics["private"] = topic
#         reader, writer = await self.open()
#         await self.send(writer, {"type": "subscribe", "id": "s", "topic": "private"})
#         await entered.wait()
#         self.assertEqual(len(topic.listeners), 1)
#         topic.publish({"kind": "changed", "value": 1})
#         topic.publish({"kind": "future", "value": 2})
#         self.assertEqual(self.connections[-1].subscriptions["s"].sent, 0)
#         release.set()
#         frames = [await self.read(reader) for _ in range(3)]
#         self.assertEqual([f["seq"] for f in frames], [1, 2, 3])
#         self.assertEqual([f["event"]["kind"] for f in frames], ["snapshot", "changed", "future"])
#         await self.send(writer, {"type": "call", "id": "r", "method": "subscriptions.check"})
#         self.assertEqual((await self.read(reader))["result"], {"subscriptions": [{"id": "s", "seq": 3}]})
#         # A refresh that already contains the publication must not replay stale state after its snapshot.
#         entered.clear()
#         release.clear()
#         async def newer(params: Params) -> Snapshot:
#             entered.set()
#             await release.wait()
#             return Snapshot(topic.version, {"kind": "snapshot", "value": 3})
#         topic.snapshot = newer
#         await self.send(writer, {"type": "subscribe", "id": "s2", "topic": "private", "params": {"future": True}})
#         self.assertEqual((await self.read(reader))["type"], "ended")
#         await entered.wait()
#         topic.publish({"kind": "changed", "value": 3})
#         release.set()
#         self.assertEqual((await self.read(reader))["seq"], 1)
#         topic.publish({"kind": "changed", "value": 4})
#         self.assertEqual((await self.read(reader))["seq"], 2)
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_registered_snapshot_race_and_cutoff

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_replacement_unsubscribe_and_snapshot_cancellation
#     async def test_replacement_unsubscribe_and_snapshot_cancellation(self) -> None:
#         """bridge.subscription-end"""
#         entered, cancelled = asyncio.Event(), asyncio.Event()
#         async def snapshot(params: Params) -> Snapshot:
#             entered.set()
#             try:
#                 await asyncio.Event().wait()
#             finally:
#                 cancelled.set()
#             return Snapshot(0, {})
#         topic = Topic(snapshot)
#         self.registry.topics["private"] = topic
#         reader, writer = await self.open()
#         await self.send(writer, {"type": "subscribe", "id": "old", "topic": "private"})
#         await entered.wait()
#         await self.send(writer, {"type": "unsubscribe", "id": "old"})
#         self.assertEqual(await self.read(reader), {"type": "ended", "id": "old"})
#         await cancelled.wait()
#         topic.publish({"kind": "changed"})
#         self.assertFalse(topic.listeners)
#         await self.send(writer, {"type": "subscribe", "id": "unknown", "topic": "absent"})
#         self.assertEqual((await self.read(reader))["error"]["code"], "unknown_method")
#         await self.send(writer, {"type": "subscribe", "id": "bad", "topic": "private", "params": []})
#         self.assertEqual((await self.read(reader))["error"]["code"], "invalid_input")
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_replacement_unsubscribe_and_snapshot_cancellation

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_normalized_topic_params_replace_and_publications_are_isolated
#     async def test_normalized_topic_params_replace_and_publications_are_isolated(self) -> None:
#         """bridge.topic-params"""
#         async def validate(params: Params) -> Params:
#             return {key: params[key] for key in params if key in ("chat", "part")}
#         async def snapshot(params: Params) -> Snapshot:
#             return Snapshot(topic.version, {"kind": "snapshot", "params": params})
#         topic = Topic(snapshot, validate)
#         self.registry.topics["private"] = topic
#         reader, writer = await self.open()
#         for id, params in (("first", {"chat": "a", "part": 1}),
#                            ("second", {"part": 1, "future": "ignored", "chat": "a"})):
#             await self.send(writer, {"type": "subscribe", "id": id, "topic": "private", "params": params})
#             if id == "second":
#                 self.assertEqual(await self.read(reader), {"type": "ended", "id": "first"})
#             self.assertEqual((await self.read(reader))["id"], id)
#         await self.send(writer, {"type": "subscribe", "id": "other", "topic": "private",
#                                  "params": {"chat": "b", "part": 1}})
#         self.assertEqual((await self.read(reader))["id"], "other")
#         topic.publish({"kind": "changed"}, params={"chat": "b", "part": 1})
#         self.assertEqual((await self.read(reader))["id"], "other")
#         await self.send(writer, {"type": "call", "id": "receipt", "method": "subscriptions.check"})
#         self.assertEqual((await self.read(reader))["result"]["subscriptions"],
#                          [{"id": "second", "seq": 1}, {"id": "other", "seq": 2}])
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_normalized_topic_params_replace_and_publications_are_isolated

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_receipt_counts_handoff_not_queue
#     async def test_receipt_counts_handoff_not_queue(self) -> None:
#         """bridge.receipts"""
#         reader, _ = await self.open()
#         connection = self.connections[-1]
#         assert connection.sender
#         connection.sender.cancel()
#         await asyncio.gather(connection.sender, return_exceptions=True)
#         async def snapshot(params: Params) -> Snapshot:
#             return Snapshot(0, {"kind": "snapshot"})
#         topic = Topic(snapshot)
#         sub = Subscription(connection, "s", topic, {}, b"key")
#         connection.subscriptions["s"] = sub
#         sub.send({"kind": "snapshot"})
#         self.assertEqual((sub.seq, sub.sent), (1, 0))
#         connection.sender = connection.task(connection.send())
#         self.assertEqual((await self.read(reader))["seq"], 1)
#         self.assertEqual(sub.sent, 1)
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_receipt_counts_handoff_not_queue

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_exact_backlog_boundary_includes_transport_and_pending
#     async def test_exact_backlog_boundary_includes_transport_and_pending(self) -> None:
#         """bridge.backlog-boundary"""
#         reader, _ = await self.open()
#         connection = self.connections[-1]
#         assert connection.sender
#         connection.sender.cancel()
#         await asyncio.gather(connection.sender, return_exceptions=True)
#         async def snapshot(params: Params) -> Snapshot:
#             return Snapshot(0, {})
#         sub = Subscription(connection, "s", Topic(snapshot), {}, b"key")
#         connection.subscriptions[sub.id] = sub
#         # The actual threshold, not a reduced fixture constant. Isolate byte accounting from socket scheduling.
#         with mock.patch.object(connection.writer.transport, "get_write_buffer_size", return_value=13):
#             connection.buffered = 7
#             sub.pending.append((1, b"1234567"))
#             connection.enqueue(Frame(b'x' * (MAX_WAITING - 20)))
#             self.assertEqual(connection.waiting(), MAX_WAITING)
#             self.assertFalse(connection.slow)
#             connection.enqueue(Frame(b'x'))
#             self.assertTrue(connection.slow)
#         self.assertEqual((await self.read(reader))["error"]["code"], "slow_reader")
#         self.assertFalse(sub.active)
#         self.assertEqual((connection.queued, connection.buffered), (0, 0))
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_exact_backlog_boundary_includes_transport_and_pending

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_real_slow_socket_isolated_and_buffered_snapshot_bounded
#     async def test_real_slow_socket_isolated_and_buffered_snapshot_bounded(self) -> None:
#         """bridge.slow-reader"""
#         entered = asyncio.Event()
#         async def snapshot(params: Params) -> Snapshot:
#             entered.set()
#             await asyncio.Event().wait()
#             return Snapshot(0, {})
#         topic = Topic(snapshot)
#         self.registry.topics["private"] = topic
#         reader, writer = await self.open()
#         await self.send(writer, {"type": "subscribe", "id": "pending", "topic": "private"})
#         await entered.wait()
#         for _ in range(9):
#             topic.publish({"kind": "changed", "value": "x" * (8 * 1024 * 1024)})
#         self.assertTrue(self.connections[-1].slow)
#         self.assertEqual((await self.read(reader))["error"]["code"], "slow_reader")
#         self.assertEqual(self.connections[-1].buffered, 0)
#         # StreamReader itself must not absorb the backlog and masquerade as a slow page.
#         raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
#         raw.setblocking(False)
#         raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
#         await asyncio.get_running_loop().sock_connect(raw, str(self.fixture.root / "wire.sock"))
#         self.addCleanup(raw.close)
#         await asyncio.sleep(0.03)
#         connection = self.connections[-1]
#         for _ in range(9):
#             connection.enqueue(Frame(encode({"type": "future", "data": "x" * (8 * 1024 * 1024)})))
#             await asyncio.sleep(0)
#         self.assertTrue(connection.slow)
#         healthy, healthy_writer = await self.open()
#         await self.send(healthy_writer, {"type": "call", "id": "ok", "method": "subscriptions.check"})
#         self.assertEqual((await self.read(healthy))["result"], {"subscriptions": []})
#         await asyncio.sleep(1.1)
#         self.assertTrue(connection.writer.is_closing())
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_real_slow_socket_isolated_and_buffered_snapshot_bounded

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_oversize_results_end_safely_and_disconnect_detaches
#     async def test_oversize_results_end_safely_and_disconnect_detaches(self) -> None:
#         """bridge.output-boundary; bridge.disconnect"""
#         async def large(params: Params) -> Params:
#             return {"data": "x" * MAX_LINE}
#         async def snapshot(params: Params) -> Snapshot:
#             return Snapshot(0, {"kind": "snapshot", "data": "x" * MAX_LINE})
#         topic = Topic(snapshot)
#         self.registry.method("private.large", large)
#         self.registry.topics["private.large"] = topic
#         reader, writer = await self.open()
#         await self.send(writer, {"type": "call", "id": "large", "method": "private.large"})
#         self.assertEqual((await self.read(reader))["error"]["code"], "invalid_input")
#         await self.send(writer, {"type": "subscribe", "id": "large-sub", "topic": "private.large"})
#         self.assertEqual((await self.read(reader))["error"]["code"], "invalid_input")
#         self.assertFalse(topic.listeners)
#         entered, cancelled = asyncio.Event(), asyncio.Event()
#         async def pending(params: Params) -> Snapshot:
#             entered.set()
#             try:
#                 await asyncio.Event().wait()
#             finally:
#                 cancelled.set()
#             return Snapshot(0, {})
#         topic.snapshot = pending
#         await self.send(writer, {"type": "subscribe", "id": "pending", "topic": "private.large"})
#         await entered.wait()
#         writer.close()
#         await writer.wait_closed()
#         await asyncio.wait_for(cancelled.wait(), 2)
#         self.assertFalse(topic.listeners)
#         await asyncio.wait_for(self.work[-1], 2)
#         self.assertFalse(self.connections[-1].tasks)
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_oversize_results_end_safely_and_disconnect_detaches

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Wire.test_invalid_correlation_and_id_limit_close_without_effect
#     async def test_invalid_correlation_and_id_limit_close_without_effect(self) -> None:
#         """bridge.correlation"""
#         for id in ("", "x" * 129, "x\n", "é" * 65):
#             reader, writer = await self.open()
#             await self.send(writer, {"type": "call", "id": id, "method": "subscriptions.check"})
#             self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
#         reader, writer = await self.open()
#         with mock.patch("arbol_backend.bridge.MAX_IDS", 2):
#             for id in ("1", "2"):
#                 await self.send(writer, {"type": "call", "id": id, "method": "subscriptions.check"})
#                 self.assertEqual((await self.read(reader))["id"], id)
#             await self.send(writer, {"type": "call", "id": "3", "method": "subscriptions.check"})
#             self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Wire.test_invalid_correlation_and_id_limit_close_without_effect


class RootWire(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fixture = PrivateRoot()
        self.fixture.behavior = {"arbol-roots": {"output": [{**self.fixture.record, "current": True,
                                                          "password": "private-secret"}]}}
        self.fixture.configure()
        self.selected = identity(ROOT, parse(self.fixture.options()), home=self.fixture.home)
        self.backend = Backend(self.selected)
        self.work = asyncio.create_task(self.backend.run())
        for _ in range(100):
            if (self.fixture.root / "backend.sock").exists():
                break
            await asyncio.sleep(0.01)
        self.writers: list[asyncio.StreamWriter] = []

    async def asyncTearDown(self) -> None:
        for writer in self.writers:
            writer.close()
        self.backend.stopped.set()
        await asyncio.wait_for(self.work, 2)
        self.fixture.close()

    async def open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_unix_connection(str(self.fixture.root / "backend.sock"))
        self.writers.append(writer)
        hello = await self.read(reader)
        self.assertEqual((hello["type"], hello["bridge"], hello["build"]), ("hello", 1, TEST_BUILD))
        self.assertTrue(hello["root"]["current"])
        self.assertNotIn("private-secret", str(hello))
        return reader, writer

    async def read(self, reader: asyncio.StreamReader) -> Params:
        return decode(await asyncio.wait_for(reader.readuntil(b"\n"), 5))

    async def send(self, writer: asyncio.StreamWriter, message: Params) -> None:
        writer.write(encode(message))
        await writer.drain()

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::RootWire.test_root_snapshot_name_state_current_and_error_within_five_seconds
#     async def test_root_snapshot_name_state_current_and_error_within_five_seconds(self) -> None:
#         """bridge.root-observation; bridge.privacy"""
#         reader, writer = await self.open()
#         await self.send(writer, {"type": "subscribe", "id": "root", "topic": "root"})
#         self.assertEqual((await self.read(reader))["seq"], 1)
#         self.fixture.record.update(name="Renamed Root", status="failed",
#                                    failed={"at": "2026-10-27T08:00:00Z", "reason": "password=private-secret"})
#         self.fixture.save_root()
#         self.fixture.behavior["arbol-roots"]["output"][0]["current"] = False
#         self.fixture.configure()
#         started = time.monotonic()
#         event = await self.read(reader)
#         self.assertLess(time.monotonic() - started, 5)
#         self.assertEqual(event["seq"], 2)
#         self.assertEqual(event["event"]["root"]["name"], "Renamed Root")
#         self.assertFalse(event["event"]["root"]["current"])
#         self.assertEqual(event["event"]["root"]["status"], "failed")
#         self.assertNotIn("private-secret", str(event))
#         self.fixture.behavior["arbol-roots"] = {"sleep": 4}
#         self.fixture.configure()
#         started = time.monotonic()
#         ended = await self.read(reader)
#         self.assertLess(time.monotonic() - started, 5)
#         self.assertEqual((ended["type"], ended["error"]["code"], ended["error"]["source"]),
#                          ("ended", "no_answer", "roots"))
#         self.assertFalse(self.backend.roots.topic.listeners)
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::RootWire.test_root_snapshot_name_state_current_and_error_within_five_seconds

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::RootWire.test_catalogue_current_fresh_coalesced_and_only_rootinfo_fields
#     async def test_catalogue_current_fresh_coalesced_and_only_rootinfo_fields(self) -> None:
#         """bridge.root-catalogue"""
#         if self.backend.discovery.task is not None:
#             await self.backend.discovery.task
#         reader, writer = await self.open()
#         for index, current in enumerate((True, False)):
#             self.fixture.behavior["arbol-roots"]["output"][0]["current"] = current
#             self.fixture.configure()
#             before = len([row for row in self.fixture.calls() if row["program"] == "arbol-roots"])
#             for n in range(3):
#                 await self.send(writer, {"type": "call", "id": f"{index}-{n}", "method": "roots.list"})
#             for _ in range(3):
#                 result = (await self.read(reader))["result"]
#                 self.assertEqual(result["roots"][0]["root"]["current"], current)
#                 self.assertEqual(set(result["roots"][0]["root"]), {"root", "name", "status", "current"})
#             self.assertEqual(len([row for row in self.fixture.calls() if row["program"] == "arbol-roots"]) - before, 1)
#         self.assertEqual(list(self.fixture.settings.iterdir()), [])
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::RootWire.test_catalogue_current_fresh_coalesced_and_only_rootinfo_fields

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::RootWire.test_cancelled_catalogue_does_not_log_a_late_failure
#     async def test_cancelled_catalogue_does_not_log_a_late_failure(self) -> None:
#         """bridge.catalogue-cancel-privacy"""
#         await self.backend.roots.catalogue()
#         entered, release = asyncio.Event(), asyncio.Event()
#         async def failing() -> list[Params]:
#             entered.set()
#             await release.wait()
#             raise Refused("no_answer", "credential=private-secret")
#         loop = asyncio.get_running_loop()
#         logged: list[Params] = []
#         old_handler = loop.get_exception_handler()
#         loop.set_exception_handler(lambda loop, context: logged.append(context))
#         try:
#             with mock.patch.object(self.backend.roots, "catalogue_read", side_effect=failing):
#                 caller = asyncio.create_task(self.backend.roots.catalogue())
#                 await entered.wait()
#                 caller.cancel()
#                 await asyncio.gather(caller, return_exceptions=True)
#                 release.set()
#                 assert self.backend.roots.inflight
#                 outcome = await self.backend.roots.inflight
#                 self.assertIsInstance(outcome, Error)
#                 self.assertNotIn("private-secret", str(outcome))
#                 await asyncio.sleep(0)
#                 self.assertEqual(logged, [])
#         finally:
#             loop.set_exception_handler(old_handler)
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::RootWire.test_cancelled_catalogue_does_not_log_a_late_failure

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::RootWire.test_root_get_private_database_presence_failure_and_concurrency
#     async def test_root_get_private_database_presence_failure_and_concurrency(self) -> None:
#         """bridge.root-get"""
#         cluster: Cluster | None = await asyncio.to_thread(Cluster)
#         assert cluster is not None
#         try:
#             from dataclasses import replace
#
#             from arbol_backend.database import Database
#             old = self.backend.database
#             db = Database(replace(self.selected, database=cluster.address))
#             self.backend.database = db
#             self.backend.roots.database = db
#             self.backend.chats.database = db
#             self.backend.chats.reader.database = db
#             await old.close()
#             reader, writer = await self.open()
#             async def get(id: str) -> Params:
#                 await self.send(writer, {"type": "call", "id": id, "method": "root.get"})
#                 return await self.read(reader)
#             self.assertFalse((await get("absent"))["result"]["layoutComplete"])
#             await db.execute((ROOT / "tests/backend/own-layout.sql").read_text())
#             self.assertTrue((await get("present"))["result"]["layoutComplete"])
#             await db.execute("DROP TABLE drafts")
#             self.assertFalse((await get("missing"))["result"]["layoutComplete"])
#             await db.execute("CREATE VIEW drafts AS SELECT 1 AS id")
#             self.assertFalse((await get("view"))["result"]["layoutComplete"])
#             entered, release = asyncio.Event(), asyncio.Event()
#             original = self.backend.roots.complete
#             assert original is not None
#             async def delayed() -> bool:
#                 entered.set()
#                 await release.wait()
#                 return await original()
#             with mock.patch.object(self.backend.roots, "complete", side_effect=delayed):
#                 await self.send(writer, {"type": "call", "id": "blocked", "method": "root.get"})
#                 await entered.wait()
#                 await self.send(writer, {"type": "call", "id": "fast", "method": "subscriptions.check"})
#                 self.assertEqual((await self.read(reader))["id"], "fast")
#                 second, second_writer = await self.open()
#                 await self.send(second_writer, {"type": "call", "id": "other", "method": "roots.list"})
#                 self.assertEqual((await self.read(second))["id"], "other")
#                 release.set()
#                 self.assertEqual((await self.read(reader))["id"], "blocked")
#             await asyncio.to_thread(cluster.close)
#             cluster = None
#             result = await get("down")
#             self.assertEqual(result["error"]["code"], "database_unavailable")
#             self.assertNotIn("result", result)
#         finally:
#             if cluster:
#                 await asyncio.to_thread(cluster.close)
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::RootWire.test_root_get_private_database_presence_failure_and_concurrency


class Diagnostics(unittest.TestCase):
    pass  # TEST-TIER-EMPTY-SUITE; helpers remain importable.
# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Diagnostics.test_listing_kill_handles_macos_exit_race
#     def test_listing_kill_handles_macos_exit_race(self) -> None:
#         """backend.child-cancel-race"""
#         from arbol_backend.process import Child, Programs
#         process = mock.Mock()
#         process.poll.return_value = None
#         process.wait.return_value = 0
#         child = Child(process, True, mock.Mock())
#         with mock.patch("os.killpg", side_effect=PermissionError("private-secret")):
#             Programs.kill(child)
#         process.wait.assert_called_once_with(timeout=0.01)
#         process.wait.reset_mock()
#         process.wait.side_effect = subprocess.TimeoutExpired("private-child", 0.01)
#         with mock.patch("os.killpg", side_effect=PermissionError("private-secret")):
#             with self.assertRaises(Refused) as caught:
#                 Programs.kill(child)
#         self.assertEqual(process.wait.call_count, 3)
#         self.assertNotIn("private-secret", str(caught.exception))
#         self.assertEqual(caught.exception.code, "no_answer")
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Diagnostics.test_listing_kill_handles_macos_exit_race

# TEST-TIER-DISABLED-BEGIN tests/backend/test_bridge.py::Diagnostics.test_private_process_never_logs_input_or_root_diagnostics
#     def test_private_process_never_logs_input_or_root_diagnostics(self) -> None:
#         """bridge.private-diagnostics"""
#         fixture = PrivateRoot()
#         self.addCleanup(fixture.close)
#         fixture.record.update(status="failed", failed={"at": "2026-10-27T08:00:00Z", "reason": "password=private-secret"})
#         fixture.save_root()
#         fixture.behavior["arbol-roots"] = {"output": [{**fixture.record, "current": True,
#                                                       "authenticationKey": "private-secret"}]}
#         fixture.configure()
#         child = fixture.start()
#         fixture.line(child)
#         client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
#         client.settimeout(2)
#         self.addCleanup(client.close)
#         client.connect(str(fixture.root / "backend.sock"))
#         stream = client.makefile("rb")
#         self.addCleanup(stream.close)
#         self.assertNotIn(b"private-secret", stream.readline())
#         client.sendall(b'{"type":"call","id":"safe","method":"root.get","params":[],"key":"private-secret"}\n')
#         self.assertNotIn(b"private-secret", stream.readline())
#         pipeline = b''.join(encode({'type': 'call', 'id': str(n), 'method': 'subscriptions.check'}) for n in range(16))
#         client.sendall(pipeline + b'{bad private-secret}\n')
#         self.assertEqual(stream.read(), b"")
#         child.send_signal(signal.SIGTERM)
#         out, err = child.communicate(timeout=2)
#         self.assertEqual((child.returncode, out, err), (0, b"", b""))
# TEST-TIER-DISABLED-END tests/backend/test_bridge.py::Diagnostics.test_private_process_never_logs_input_or_root_diagnostics


if __name__ == "__main__":
    unittest.main()

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:6
# import signal
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:6
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:7
# import socket
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:7
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:8
# import subprocess
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:8
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:10
# import time
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:10
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:13
# from unittest import mock
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:13
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:19
# from arbol_backend.bridge import (  # noqa: E402
#     MAX_LINE,
#     MAX_WAITING,
#     Connection,
#     Error,
#     Frame,
#     Params,
#     Registry,
#     Snapshot,
#     Subscription,
#     Topic,
#     decode,
#     driver_id,
#     encode,
#     subscription_id,
#     uuid_id,
# )
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:19
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:36
# from arbol_backend.model import Refused, identity, parse  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:36
# TEST-TIER-IMPORTS-BEGIN tests/backend/test_bridge.py:38
# from backend.support import TEST_BUILD, TEST_ROOT, Cluster  # noqa: E402
# TEST-TIER-IMPORTS-END tests/backend/test_bridge.py:38
