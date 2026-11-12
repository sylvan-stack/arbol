"""Backend adapter for the shared installation admission protocol."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING

from arbol_installation.admission import (
    DATABASE_WRITER_LOCK as DATABASE_WRITER_LOCK,
)
from arbol_installation.admission import (
    GATE as GATE,
)
from arbol_installation.admission import (
    GENERATION_ENV as GENERATION_ENV,
)
from arbol_installation.admission import (
    OWNER as OWNER,
)
from arbol_installation.admission import (
    SHA256 as SHA256,
)
from arbol_installation.admission import (
    WRITERS as WRITERS,
)
from arbol_installation.admission import (
    Admission as InstallationAdmission,
)
from arbol_installation.admission import (
    AdmissionRefusal,
    Mode,
)
from arbol_installation.admission import (
    Lease as Lease,
)
from arbol_installation.admission import (
    Source as Source,
)
from arbol_installation.admission import (
    State as State,
)
from arbol_installation.admission import (
    checked_source as checked_source,
)
from arbol_installation.admission import (
    directory as directory,
)
from arbol_installation.admission import (
    lock as lock,
)
from arbol_installation.admission import (
    prepare_directory as prepare_directory,
)
from arbol_installation.admission import (
    private_dir as private_dir,
)
from arbol_installation.admission import (
    read_state as read_state,
)
from arbol_installation.admission import (
    runtime_folder as runtime_folder,
)
from arbol_installation.admission import (
    write_state as write_state,
)

from .model import Refused as Refusal

if TYPE_CHECKING:
    from .database import Session


class Admission(InstallationAdmission):
    @contextmanager
    def lease(self, mode: Mode, *, generation: str | None = None) -> Iterator[Lease]:
        with ExitStack() as stack:
            try:
                lease = stack.enter_context(super().lease(mode, generation=generation))
            except AdmissionRefusal as error:
                raise Refusal(error.code, str(error)) from None
            yield lease


async def register_database_writer(session: Session, lease: Lease) -> None:
    """Bind an application connection to its file lease before issuing any writes."""
    try:
        lease.require()
    except AdmissionRefusal as error:
        raise Refusal(error.code, str(error)) from None
    source = lease.state.source
    info = session.connection.info
    if (info.host, info.port, info.dbname) != (source["host"], source["port"], source["database"]):
        raise Refusal("maintenance", "The database connection does not match the writer admission target.")
    rows = await session.execute("SELECT pg_catalog.pg_try_advisory_lock_shared(%s::bigint)", [DATABASE_WRITER_LOCK])
    if rows != [(True,)]:
        raise Refusal("maintenance", "PostgreSQL is fenced for migration.")
    rows = await session.execute(
        "SELECT oid FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database()")
    if rows != [(source["databaseOid"],)]:
        raise Refusal("maintenance", "PostgreSQL did not confirm the writer admission target.")
