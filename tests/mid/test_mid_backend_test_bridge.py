"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_bridge as _support
from backend.test_bridge import (
    Backend,
    Cluster,
    Connection,
    Diagnostics,
    Error,
    Frame,
    MAX_LINE,
    MAX_WAITING,
    Params,
    Path,
    PrivateRoot,
    ROOT,
    Refused,
    Registry,
    RootWire,
    Snapshot,
    Subscription,
    TEST_BUILD,
    TEST_ROOT,
    Topic,
    Wire,
    asyncio,
    decode,
    driver_id,
    encode,
    identity,
    mock,
    parse,
    signal,
    socket,
    subprocess,
    subscription_id,
    sys,
    time,
    unittest,
    uuid_id,
)


class Wire(_support.Wire):


# TEST-TIER-BEGIN tests/backend/test_bridge.py::Wire.test_registered_snapshot_race_and_cutoff
    async def test_registered_snapshot_race_and_cutoff(self) -> None:
        """bridge.snapshot-race"""
        entered, release = asyncio.Event(), asyncio.Event()
        async def snapshot(params: Params) -> Snapshot:
            entered.set()
            await release.wait()
            return Snapshot(0, {"kind": "snapshot", "value": 0})
        topic = Topic(snapshot)
        self.registry.topics["private"] = topic
        reader, writer = await self.open()
        await self.send(writer, {"type": "subscribe", "id": "s", "topic": "private"})
        await entered.wait()
        self.assertEqual(len(topic.listeners), 1)
        topic.publish({"kind": "changed", "value": 1})
        topic.publish({"kind": "future", "value": 2})
        self.assertEqual(self.connections[-1].subscriptions["s"].sent, 0)
        release.set()
        frames = [await self.read(reader) for _ in range(3)]
        self.assertEqual([f["seq"] for f in frames], [1, 2, 3])
        self.assertEqual([f["event"]["kind"] for f in frames], ["snapshot", "changed", "future"])
        await self.send(writer, {"type": "call", "id": "r", "method": "subscriptions.check"})
        self.assertEqual((await self.read(reader))["result"], {"subscriptions": [{"id": "s", "seq": 3}]})
        # A refresh that already contains the publication must not replay stale state after its snapshot.
        entered.clear()
        release.clear()
        async def newer(params: Params) -> Snapshot:
            entered.set()
            await release.wait()
            return Snapshot(topic.version, {"kind": "snapshot", "value": 3})
        topic.snapshot = newer
        await self.send(writer, {"type": "subscribe", "id": "s2", "topic": "private", "params": {"future": True}})
        self.assertEqual((await self.read(reader))["type"], "ended")
        await entered.wait()
        topic.publish({"kind": "changed", "value": 3})
        release.set()
        self.assertEqual((await self.read(reader))["seq"], 1)
        topic.publish({"kind": "changed", "value": 4})
        self.assertEqual((await self.read(reader))["seq"], 2)
# TEST-TIER-END tests/backend/test_bridge.py::Wire.test_registered_snapshot_race_and_cutoff


# TEST-TIER-BEGIN tests/backend/test_bridge.py::Wire.test_real_slow_socket_isolated_and_buffered_snapshot_bounded
    async def test_real_slow_socket_isolated_and_buffered_snapshot_bounded(self) -> None:
        """bridge.slow-reader"""
        entered = asyncio.Event()
        async def snapshot(params: Params) -> Snapshot:
            entered.set()
            await asyncio.Event().wait()
            return Snapshot(0, {})
        topic = Topic(snapshot)
        self.registry.topics["private"] = topic
        reader, writer = await self.open()
        await self.send(writer, {"type": "subscribe", "id": "pending", "topic": "private"})
        await entered.wait()
        for _ in range(9):
            topic.publish({"kind": "changed", "value": "x" * (8 * 1024 * 1024)})
        self.assertTrue(self.connections[-1].slow)
        self.assertEqual((await self.read(reader))["error"]["code"], "slow_reader")
        self.assertEqual(self.connections[-1].buffered, 0)
        # StreamReader itself must not absorb the backlog and masquerade as a slow page.
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.setblocking(False)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        await asyncio.get_running_loop().sock_connect(raw, str(self.fixture.root / "wire.sock"))
        self.addCleanup(raw.close)
        await asyncio.sleep(0.03)
        connection = self.connections[-1]
        for _ in range(9):
            connection.enqueue(Frame(encode({"type": "future", "data": "x" * (8 * 1024 * 1024)})))
            await asyncio.sleep(0)
        self.assertTrue(connection.slow)
        healthy, healthy_writer = await self.open()
        await self.send(healthy_writer, {"type": "call", "id": "ok", "method": "subscriptions.check"})
        self.assertEqual((await self.read(healthy))["result"], {"subscriptions": []})
        await asyncio.sleep(1.1)
        self.assertTrue(connection.writer.is_closing())
# TEST-TIER-END tests/backend/test_bridge.py::Wire.test_real_slow_socket_isolated_and_buffered_snapshot_bounded

# TEST-TIER-BEGIN tests/backend/test_bridge.py::Wire.test_oversize_results_end_safely_and_disconnect_detaches
    async def test_oversize_results_end_safely_and_disconnect_detaches(self) -> None:
        """bridge.output-boundary; bridge.disconnect"""
        async def large(params: Params) -> Params:
            return {"data": "x" * MAX_LINE}
        async def snapshot(params: Params) -> Snapshot:
            return Snapshot(0, {"kind": "snapshot", "data": "x" * MAX_LINE})
        topic = Topic(snapshot)
        self.registry.method("private.large", large)
        self.registry.topics["private.large"] = topic
        reader, writer = await self.open()
        await self.send(writer, {"type": "call", "id": "large", "method": "private.large"})
        self.assertEqual((await self.read(reader))["error"]["code"], "invalid_input")
        await self.send(writer, {"type": "subscribe", "id": "large-sub", "topic": "private.large"})
        self.assertEqual((await self.read(reader))["error"]["code"], "invalid_input")
        self.assertFalse(topic.listeners)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def pending(params: Params) -> Snapshot:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return Snapshot(0, {})
        topic.snapshot = pending
        await self.send(writer, {"type": "subscribe", "id": "pending", "topic": "private.large"})
        await entered.wait()
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(cancelled.wait(), 2)
        self.assertFalse(topic.listeners)
        await asyncio.wait_for(self.work[-1], 2)
        self.assertFalse(self.connections[-1].tasks)
# TEST-TIER-END tests/backend/test_bridge.py::Wire.test_oversize_results_end_safely_and_disconnect_detaches


class RootWire(_support.RootWire):


# TEST-TIER-BEGIN tests/backend/test_bridge.py::RootWire.test_cancelled_catalogue_does_not_log_a_late_failure
    async def test_cancelled_catalogue_does_not_log_a_late_failure(self) -> None:
        """bridge.catalogue-cancel-privacy"""
        await self.backend.roots.catalogue()
        entered, release = asyncio.Event(), asyncio.Event()
        async def failing() -> list[Params]:
            entered.set()
            await release.wait()
            raise Refused("no_answer", "credential=private-secret")
        loop = asyncio.get_running_loop()
        logged: list[Params] = []
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: logged.append(context))
        try:
            with mock.patch.object(self.backend.roots, "catalogue_read", side_effect=failing):
                caller = asyncio.create_task(self.backend.roots.catalogue())
                await entered.wait()
                caller.cancel()
                await asyncio.gather(caller, return_exceptions=True)
                release.set()
                assert self.backend.roots.inflight
                outcome = await self.backend.roots.inflight
                self.assertIsInstance(outcome, Error)
                self.assertNotIn("private-secret", str(outcome))
                await asyncio.sleep(0)
                self.assertEqual(logged, [])
        finally:
            loop.set_exception_handler(old_handler)
# TEST-TIER-END tests/backend/test_bridge.py::RootWire.test_cancelled_catalogue_does_not_log_a_late_failure
