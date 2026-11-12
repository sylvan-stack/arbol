"""Public installation state for Bridge 2."""

from __future__ import annotations

from .bridge import BRIDGE_VERSION, Params, Registry, Snapshot, Topic
from .database import Database
from .model import Identity


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
