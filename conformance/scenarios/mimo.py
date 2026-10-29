# Test implementations moved to tests/mid/archived/conformance/scenarios/mimo.py.
"""Mimo qualification is retained for a future explicit testing task."""


SCOPES: dict[str, str] = {}


async def prepare(*args: object, **kwargs: object) -> None:
    raise RuntimeError("Required Mimo mid-tier scenarios are disabled; restore them only for an explicit testing task.")


async def run(*args: object, **kwargs: object) -> None:
    raise RuntimeError("Required Mimo mid-tier scenarios are disabled; restore them only for an explicit testing task.")
