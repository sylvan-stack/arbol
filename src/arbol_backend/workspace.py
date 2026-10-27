"""Read-only renderer bootstrap of public readonly slots/defaults (BKD-D36)."""
from __future__ import annotations

import asyncio

from .bridge import Error, Params, Registry
from .model import Identity, Settings


class Workspace:
    def __init__(self, identity: Identity, settings: Settings, registry: Registry) -> None:
        self.home, self.settings = identity.home, settings
        registry.method("workspace.get", self.get)

    def read(self) -> Params:
        folder = self.home / "repos/sylvan-stack/readonly"
        try:
            repositories: list[Params] = [{"name": "sylvan-stack", "folder": str(folder),
                                          "route": self.settings.for_repository("sylvan-stack")}]
            for path in sorted(folder.iterdir(), key=lambda p: (p.name.casefold(), p.name)):
                if (not path.name.startswith(".") and not path.is_symlink() and path.is_dir()
                        and ((path / ".git").is_dir() or (path / ".git").is_file())):
                    repositories.append({"name": path.name, "folder": str(path),
                                         "route": self.settings.for_repository(path.name)})
            return {"repositories": repositories, "route": dict(self.settings.route)}
        except OSError as failure:
            raise Error("no_answer") from failure

    async def get(self, params: Params) -> Params:
        return await asyncio.to_thread(self.read)
