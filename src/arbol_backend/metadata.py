"""Own-Root layout inspection and private, versioned attention metadata (BKD-D30)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .bridge import Params, Snapshot, Topic
from .database import Session

OWN_COLUMNS = {
    "drafts": {"id", "chat_id", "folder", "text", "revision", "sent_as", "sent_request", "updated_at"},
    "chat_settings": {"chat_id", "route", "working_folder", "updated_at"},
    "chat_marks": {"chat_id", "ongoing", "archived_at", "updated_at"},
    "exchange_notes": {"exchange_id", "kind", "at"},
}
PROVENANCE_COLUMNS = {"chat_id", "from_root", "from_chat", "ended_through", "migrated_at", "stale"}


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now() -> str:
    return iso(datetime.now(UTC))


class Attention:
    def __init__(self) -> None:
        self.items: dict[str, Params] = {}
        self.topic = Topic(self.snapshot)

    async def snapshot(self, params: Params) -> Snapshot:
        return Snapshot(self.topic.version, {"kind": "snapshot", "items": list(self.items.values())})

    def open(self, id: str, message: str, *, severity: str = "warning") -> None:
        item = {"id": id, "kind": id, "severity": severity, "message": message,
                "since": self.items.get(id, {}).get("since", now())}
        if self.items.get(id) != item:
            self.items[id] = item
            self.topic.publish({"kind": "opened", "item": item})

    def close(self, id: str) -> None:
        if self.items.pop(id, None) is not None:
            self.topic.publish({"kind": "closed", "id": id})


@dataclass(frozen=True)
class Layout:
    own: bool
    provenance: bool
    lineage: bool

    @property
    def complete(self) -> bool:
        return self.own and (not self.lineage or self.provenance)


async def inspect(session: Session, *, lineage: bool) -> Layout:
    rows = await session.execute(
        "SELECT c.relname,c.relkind,array_agg(a.attname) FILTER (WHERE a.attnum>0 AND NOT a.attisdropped) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "LEFT JOIN pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname='public' AND c.relname=ANY(%s) GROUP BY c.relname,c.relkind",
        [[*OWN_COLUMNS, "drafts_revision", "migrated_chats"]],
    )
    tables = {name: set(columns or []) for name, kind, columns in rows if kind in ("r", "p")}
    counter = any(name == "drafts_revision" and kind == "S" for name, kind, _ in rows)
    own = counter and all(columns <= tables.get(name, set()) for name, columns in OWN_COLUMNS.items())
    provenance = PROVENANCE_COLUMNS <= tables.get("migrated_chats", set())
    return Layout(own, provenance, lineage)
