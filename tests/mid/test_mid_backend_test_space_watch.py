"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import backend.test_space_watch as _support
from backend.test_space_watch import (
    Any,
    Callable,
    Clock,
    GIB,
    INTERVAL,
    LocalDisk,
    Measurements,
    Params,
    Path,
    ROOT,
    Registry,
    Sequence,
    Session,
    Trunk,
    Watching,
    WindowFixture,
    asyncio,
    chat,
    mock,
    offline,
    online,
    signal,
    sys,
    until,
)


class Watching(_support.Watching):


# TEST-TIER-BEGIN tests/backend/test_space_watch.py::Watching.test_shutdown_cancels_measurement_utility_and_watcher_but_keeps_a_live_producer
    async def test_shutdown_cancels_measurement_utility_and_watcher_but_keeps_a_live_producer(self) -> None:
        """measurement.shutdown; measurement.utility-reaped; measurement.no-trunk-signal"""
        service = self.backend.measurements
        producer = await Trunk.make(self.frame, chat(1))
        program = self.frame.bin / "space-du"
        program.write_text("#!/bin/sh\nexec /bin/sleep 30\n")
        program.chmod(0o700)
        service.disk = LocalDisk(program=str(program))
        children: list[asyncio.subprocess.Process] = []
        create = asyncio.create_subprocess_exec
        async def captured(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
            child = await create(*args, **kwargs)
            if args[0] == str(program):
                children.append(child)
            return child
        with mock.patch("arbol_backend.storage.asyncio.create_subprocess_exec", side_effect=captured):
            caller = asyncio.create_task(service.measure({}))
            await until(lambda: bool(children))
            await asyncio.wait_for(service.close(), 0.5)
            with self.assertRaises(asyncio.CancelledError):
                await caller
        self.assertEqual(children[0].returncode, -signal.SIGKILL)
        self.assertIsNone(producer.child.poll())
        assert service.watcher
        self.assertTrue(service.watcher.done())
# TEST-TIER-END tests/backend/test_space_watch.py::Watching.test_shutdown_cancels_measurement_utility_and_watcher_but_keeps_a_live_producer
