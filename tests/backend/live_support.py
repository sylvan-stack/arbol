"""Contract-format Trunk fixture backed by one owned, separately grouped child."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from arbol_backend.database import Database
from arbol_backend.exchange_files import processes
from arbol_backend.metadata import iso
from backend.support import Frame

ROUTE = {"driver": "claude", "subscription": "private", "model": "private-model"}


def now() -> str:
    return iso(datetime.now(UTC))


class Trunk:
    def __init__(self, frame: Frame, chat: str, exchange: str, child: subprocess.Popen[bytes],
                 started: datetime, *, staged: bool = False) -> None:
        self.frame, self.chat, self.exchange, self.child = frame, chat, exchange, child
        parent = frame.root / "exchanges"
        parent.mkdir(mode=0o700, exist_ok=True)
        self.folder = parent / ("." + exchange + ".new" if staged else exchange)
        self.folder.mkdir(mode=0o700)
        self.n = 0
        self.value: dict[str, Any] = {"rootContract": 1, "root": frame.record["root"], "exchange": exchange,
            "chat": chat, "trunk": "trivial", "build": "0", "route": ROUTE, "workingFolder": str(frame.base),
            "process": {"pid": child.pid, "startedAt": iso(started)},
            "signsOfLife": {"heartbeat": 1, "waitingFor": "driver", "since": now()}}
        self.save_record()
        for name in ("events.jsonl", "control"):
            (self.folder / name).touch(mode=0o600)

    @classmethod
    async def make(cls, frame: Frame, chat: str, *, exchange: str | None = None, staged: bool = False) -> Trunk:
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(600)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True)
        frame.children.append(child)
        starts = await processes({child.pid})
        started = starts[child.pid]
        assert started is not None
        return cls(frame, chat, exchange or str(uuid4()), child, started, staged=staged)

    def save_record(self) -> None:
        temporary = self.folder / "record.json.new"
        temporary.write_text(json.dumps(self.value, separators=(",", ":")))
        temporary.chmod(0o600)
        temporary.replace(self.folder / "record.json")

    def publish(self) -> None:
        target = self.folder.parent / self.exchange
        self.folder.rename(target)
        self.folder = target

    def append(self, raw: bytes) -> None:
        descriptor = os.open(self.folder / "events.jsonl", os.O_WRONLY | os.O_APPEND)
        try:
            assert os.write(descriptor, raw) == len(raw)
        finally:
            os.close(descriptor)

    def event(self, kind: str, **fields: Any) -> dict[str, Any]:
        self.n += 1
        value = {"n": self.n, "event": {"runId": self.exchange + ".1", "seq": self.n, "at": now(),
                                      "type": kind, **fields}}
        self.append((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        return value

    async def accept(self, database: Database, *, message: str = "private request") -> None:
        await database.execute("INSERT INTO chats(id,created_at) VALUES(%s,clock_timestamp()) ON CONFLICT DO NOTHING", [self.chat])
        await database.execute(
            "INSERT INTO exchanges(id,chat_id,number,state,trunk,build,route,working_folder,accepted_at) "
            "SELECT %s,%s,coalesce(max(number),0)+1,'open','trivial','0',%s,%s,clock_timestamp() FROM exchanges WHERE chat_id=%s",
            [self.exchange, self.chat, Jsonb(ROUTE), str(self.frame.base), self.chat])
        await database.execute("INSERT INTO messages VALUES(%s,0,'user',%s)", [self.exchange, message])
        self.value["acceptedAt"] = now()
        self.save_record()

    def end(self, state: str = "completed", *, error: dict[str, Any] | None = None) -> None:
        self.n += 1
        end = {"state": state, "at": now(), **({"error": error} if error is not None else {})}
        self.append((json.dumps({"n": self.n, "end": end}, separators=(",", ":")) + "\n").encode())
        self.value["end"] = end
        self.save_record()

    async def save(self, database: Database, *, state: str = "completed", answer: str = "saved answer",
                   remove: bool = True) -> None:
        error = {"code": "private_failure", "message": "A private fixture failed."} if state == "failed" else None
        if "end" not in self.value:
            self.end(state, error=error)
        await database.execute("INSERT INTO messages VALUES(%s,1,'assistant',%s)", [self.exchange, answer])
        await database.execute("UPDATE exchanges SET state=%s,error=%s,ended_at=clock_timestamp() WHERE id=%s",
                               [state, Jsonb(error) if error is not None else None, self.exchange])
        if remove:
            self.remove()

    def remove(self) -> None:
        target = self.folder.parent / ("." + self.exchange + ".old")
        self.folder.rename(target)
        shutil.rmtree(target)

    def die(self) -> None:
        if self.child.poll() is None:
            self.child.terminate()
        self.child.wait(timeout=3)
