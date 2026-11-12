"""Expose the single runtime's Exchange inventory over the Bridge."""

from __future__ import annotations

from .bridge import Params, Registry
from .listings import Listings


class Discovery:
    def __init__(self, listings: Listings, registry: Registry) -> None:
        self.listings = listings
        registry.method("exchanges.list", self.get)

    async def get(self, params: Params) -> Params:
        return await self.listings.get()
