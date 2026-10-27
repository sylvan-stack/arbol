"""Generation-checked return snapshots, independent discovery and durable-note retries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from .bridge import Registry, Subscription
from .chats import Chats
from .discovery import Discovery
from .health import RETRY, Health
from .notes import Notes
from .settling import Settling
from .stuck import Stuck
from .views import View


class Recovery:
    def __init__(self, health: Health, chats: Chats, registry: Registry, settling: Settling,
                 notes: Notes, discovery: Discovery, stuck: Stuck, *, retry: float = RETRY) -> None:
        self.health, self.chats, self.registry = health, chats, registry
        self.settling, self.notes, self.discovery, self.stuck = settling, notes, discovery, stuck
        self.on_returned: Callable[[], None] | None = None
        self.closed = False
        self.retry = retry
        self.looks: set[asyncio.Task[None]] = set()
        health.on_away = self.pause
        health.on_return = self.returned
        settling.on_settled = self.settled

    def views(self) -> Iterable[View]:
        return (self.chats.list_view, self.chats.chat_view, *self.chats.extra_views.values())

    def pause(self) -> None:
        for view in self.views():
            view.invalidate()  # An older in-flight SQL read cannot publish across an outage.

    def valid(self, epoch: int) -> bool:
        return not self.closed and not self.health.database.away and self.health.epoch == epoch

    def settled(self, root: str) -> None:
        if root == self.chats.identity.root and not self.closed:
            self.notes.request()
            self.chats.invalidate()

    async def discover(self) -> None:
        try:
            await self.discovery.get({})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # Discovery's own Root-scoped result remains available to the next caller.

    async def refresh(self, epoch: int, subscriptions: list[Subscription]) -> None:
        first = subscriptions[0]
        view = next((view for view in self.views() if view.topic is first.topic), None)
        key = view.key(first.params) if view is not None else ""
        while self.valid(epoch) and any(sub.active for sub in subscriptions):
            try:
                generation = view.generations.get(key, 0) if view is not None else 0
                snapshot = await first.topic.snapshot(first.params)
                if not self.valid(epoch):
                    return
                # SQL publication and this check/enqueue have no await between them.
                current = snapshot.version == first.topic.version and (view is None or
                    generation == view.generations.get(key, 0))
                if current:
                    for sub in subscriptions:
                        if sub.active and sub.ready and sub.last_snapshot is not snapshot.event:
                            sub.send(snapshot.event)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Keep the existing display and stream, then retry this return obligation.
            await asyncio.sleep(self.retry)

    async def returned(self, epoch: int) -> None:
        if not self.valid(epoch):
            return
        self.pause()
        if self.on_returned:
            try:
                self.on_returned()
            except Exception:
                pass  # Storage observation cannot prevent this epoch's return snapshots.
        self.settling.request()
        self.notes.request()
        self.stuck.retry_notes()
        look = asyncio.create_task(self.discover())
        self.looks.add(look)
        look.add_done_callback(self.looks.discard)
        groups: dict[tuple[int, bytes], list[Subscription]] = {}
        for topic in self.registry.topics.values():
            for sub in list(topic.listeners):
                if sub.active and sub.ready:
                    groups.setdefault((id(topic), sub.key), []).append(sub)
        await asyncio.gather(*(self.refresh(epoch, group) for group in groups.values()))

    async def close(self) -> None:
        self.closed = True
        self.on_returned = None
        self.health.on_return = None
        self.health.on_away = None
        self.settling.on_settled = None
        tasks = list(self.looks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.looks.clear()
