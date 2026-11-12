"""Fresh Root catalogue and versioned own-Root metadata, independent of database reads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .bridge import BRIDGE_VERSION, Error, Params, Registry, Snapshot, Topic
from .database import Database
from .model import ROOT_ID, Identity, Refused
from .process import GLOBAL_CATALOGUE, Programs


@dataclass(frozen=True)
class Catalogue:
    public: list[Params]
    databases: list[Params]


class Roots:
    def __init__(self, identity: Identity, programs: Programs, database: Database) -> None:
        self.identity, self.programs, self.database = identity, programs, database
        self.inflight: asyncio.Task[Catalogue | Error] | None = None
        self.current: Params | None = None

    async def catalogue_read(self) -> Catalogue:
        try:
            async with asyncio.timeout(0.8):
                value: Any = await self.programs.call("arbol-roots", ["list"], kind="list", key=GLOBAL_CATALOGUE)
        except (TimeoutError, Refused) as error:
            raise Error("no_answer", source="roots") from error
        if not isinstance(value, list):
            raise Error("no_answer", source="roots")
        rows = [self.info(row) for row in value]
        if sum(row["current"] for row in rows) > 1 or len({row["root"] for row in rows}) != len(rows):
            raise Error("no_answer", source="roots")
        databases = []
        for row, record in zip(rows, value, strict=True):
            name = record.get("database")
            valid = isinstance(name, str) and bool(name.strip()) and "\0" not in name and name.lower() not in {"postgres", "template0", "template1"}
            try:
                valid = valid and len(name.encode("utf-8")) <= 63
            except UnicodeError:
                valid = False
            entry = {"root": row["root"], "name": row["name"], "database": name if valid else ""}
            if not valid:
                entry["problem"] = "This Root's database name is not available."
            databases.append(entry)
        return Catalogue(rows, databases)

    async def catalogue_outcome(self) -> Catalogue | Error:
        # A cancelled shield must never leave an exception to asyncio's default logger.
        try:
            return await self.catalogue_read()
        except Refused:
            return Error("no_answer", source="roots")
        except Exception:
            return Error("no_answer", source="roots")

    async def shared_catalogue(self) -> Catalogue:
        if self.inflight is None or self.inflight.done():
            self.inflight = asyncio.create_task(self.catalogue_outcome())
        value = await asyncio.shield(self.inflight)
        if isinstance(value, Error):
            raise value
        return value

    async def catalogue(self) -> list[Params]:
        return (await self.shared_catalogue()).public

    async def database_records(self) -> list[Params]:
        return [dict(row) for row in (await self.shared_catalogue()).databases]

    @staticmethod
    def info(record: Any) -> Params:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("root"), str)
            or not ROOT_ID.fullmatch(record["root"])
            or not isinstance(record.get("name"), str)
            or not record["name"]
            or record.get("status") not in ("preparing", "working", "failed")
            or not isinstance(record.get("current"), bool)
        ):
            raise Error("no_answer", source="roots")
        result = {key: record[key] for key in ("root", "name", "status", "current")}
        if record["status"] == "failed":
            failed = record.get("failed")
            if isinstance(failed, dict) and isinstance(failed.get("at"), str):
                # Only a timestamp is allowed; diagnostic text on disk is never echoed.
                try:
                    datetime.fromisoformat(failed["at"])
                except ValueError:
                    pass
                else:
                    result["failed"] = {"at": failed["at"], "reason": "The Root is marked failed."}
        return result

    async def close(self) -> None:
        if self.inflight:
            self.inflight.cancel()
            await asyncio.gather(self.inflight, return_exceptions=True)


class Installation:
    """Bridge status observations do not grant permission to read or write."""

    def __init__(self, identity: Identity, database: Database, registry: Registry) -> None:
        self.identity, self.database = identity, database
        self.maintenance = "unknown"
        self.last: Params | None = None
        self.topic = Topic(self.snapshot)
        registry.method("installation.get", self.get)
        registry.topics["installation"] = self.topic

    def state(self) -> Params:
        schema = self.database.schema
        return {"database": schema.state, "schema": schema.pair(), "maintenance": self.maintenance}

    def publish(self) -> None:
        state = self.state()
        if state != self.last:
            self.last = state
            self.topic.publish({"kind": "changed", "installation": state})

    async def snapshot(self, params: Params) -> Snapshot:
        return Snapshot(self.topic.version, {"kind": "snapshot", "installation": self.state()})

    async def get(self, params: Params) -> Params:
        return {"installation": self.state()}

    async def hello(self) -> Params:
        return {"type": "hello", "bridge": BRIDGE_VERSION, "build": self.identity.build,
                "installation": self.state(), "trunkSelection": True}
