"""Stop and restart only the disposable socket-only PostgreSQL fixture."""

from __future__ import annotations

import asyncio
import subprocess
import time

from backend.support import PG, Cluster


async def offline(cluster: Cluster) -> None:
    result = await asyncio.to_thread(subprocess.run,
        [str(PG / "pg_ctl"), "-D", str(cluster.data), "-m", "fast", "-w", "stop"],
        capture_output=True, timeout=8)
    assert result.returncode == 0
    assert cluster.child is not None
    await asyncio.to_thread(cluster.child.wait, timeout=3)


async def online(cluster: Cluster) -> None:
    assert cluster.child is not None and cluster.child.poll() is not None
    cluster.child = subprocess.Popen(
        [str(PG / "postgres"), "-D", str(cluster.data), "-k", str(cluster.socket), "-h", "", "-p", "5432", "-F"],
        stdin=subprocess.DEVNULL, stdout=cluster.stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = await asyncio.to_thread(subprocess.run,
            [str(PG / "pg_isready"), "-h", str(cluster.socket), "-p", "5432", "-U", "bkd"],
            capture_output=True, timeout=2)
        if result.returncode == 0:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("Private PostgreSQL restart did not become ready.")
