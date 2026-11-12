"""Replay a pending Exchange with its recorded compatible Trunk Build."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from .database import Unavailable
from .exchange_admission import GENERATION_ENV, Admission, Lease
from .exchange_cleanup import cleanup
from .exchange_context import Context, Refusal
from .exchange_launcher import Reply, command_reply
from .exchange_listing import listing, lookup
from .model import Refused

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


async def stored_state(context: Context, exchange: str) -> str:
    database = context.database()
    try:
        async with asyncio.timeout(10):
            async with database.session() as session:
                await session.execute("BEGIN")
                await session.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [exchange])
                rows = await session.execute("SELECT state FROM public.exchanges WHERE id = %s", [exchange])
        if not rows:
            return "none"
        state = rows[0][0]
        if not isinstance(state, str) or state not in TERMINAL | {"open"}:
            raise Refusal("runtime_unavailable", "The Exchange has an unreadable saved state.")
        return state
    except (Unavailable, TimeoutError):
        raise Refusal("database_unavailable", "The database could not confirm the Exchange state.") from None
    finally:
        await database.close()


def failure(exchange: str, error: Refused) -> dict[str, Any]:
    value: dict[str, Any] = {"exchange": exchange, "error": {"code": error.code, "message": str(error)}}
    if isinstance(error, Refusal) and error.available is not None:
        value["available"] = error.available
    return value


def settle_after_stop(context: Context, exchange: str, lease: Lease) -> dict[str, Any]:
    lease.require()
    try:
        record = lookup(context, exchange)
        if record is None:
            if os.path.lexists(context.exchanges / f".{exchange}.new"):
                raise Refusal("in_progress", "The Exchange still has an unpublished folder.")
            state = asyncio.run(stored_state(context, exchange))
            if state == "open":
                raise Refusal("runtime_unavailable", "An open Exchange has no recoverable folder.")
            return {"exchange": exchange, "settled": state}
        if record["process"]["alive"]:
            raise Refusal("alive", "The Exchange's recorded process is still alive.")
        # Schema fit alone cannot qualify a different Build to replay this folder.
        # There are no alternate Builds qualified for this format.
        reply = command_reply(context, [record["trunk"], "-v", record["build"], "settle", exchange],
                              timeout=25.0, generation=lease.state.generation)
        if reply.status:
            return {**reply.value, "exchange": exchange}
        if reply.value.get("exchange") != exchange or reply.value.get("settled") not in TERMINAL | {"none"}:
            raise Refusal("trunk_unavailable", "The Trunk did not confirm a settled state for this Exchange.")
        return {"exchange": exchange, "settled": reply.value["settled"]}
    except Refused as error:
        return failure(exchange, error)


def settle(context: Context, exchange: str | None = None) -> Reply:
    admission = Admission(context.identity.folder)
    with admission.lease("controlled", generation=os.environ.get(GENERATION_ENV)) as lease:
        return settle_admitted(context, exchange, lease)


def settle_admitted(context: Context, exchange: str | None, lease: Lease) -> Reply:
    unreadable: set[str] = set()
    if exchange is None:
        cleanup(context, lambda uuid: asyncio.run(stored_state(context, uuid)))
        view = listing(context)
        targets = {entry["exchange"] for entry in view["exchanges"] if not entry["process"]["alive"]}
        unreadable = set(view["unreadable"])
    else:
        targets = {exchange}
    results = []
    for target in sorted(targets | unreadable):
        if target in unreadable:
            value = failure(target, Refusal("runtime_unavailable", "The Exchange folder or its process is unresolved."))
        else:
            value = settle_after_stop(context, target, lease)
        results.append(value)
        if value.get("error", {}).get("code") == "database_unavailable":
            break
    document: dict[str, Any] = {"results": results}
    failed = any("error" in value for value in results)
    if failed:
        document["error"] = {"code": "settlement_pending", "message": "Some Exchange results remain unresolved."}
    return Reply(document, int(failed))
