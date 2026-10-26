"""Serialized catalogue mutations and creation compensation (ARC-D65–67)."""

import errno
import fcntl
import hashlib
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType

from arbol_builds.launcher import Record
from arbol_builds.service import atomic_write, json_text

from .database import Database, DatabaseError
from .model import Places, Refused, identifier, save_record, validate_record


@contextmanager
def catalogue_lock(paths: Places) -> Iterator[None]:
    paths.roots.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(paths.roots / ".catalogue.lock", os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise Refused("operation_failed", "Cannot open the catalogue mutation lock.") from error
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refused("operation_failed", "The catalogue mutation lock must be a regular file.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise Refused("busy", "Another catalogue mutation is in progress.") from error
            raise Refused("operation_failed", "Cannot acquire the catalogue mutation lock.") from error
        yield
    finally:
        os.close(fd)


def default_database_name(root: str) -> str:
    identifier(root)
    if len(root) <= 57:
        return "arbol_" + root
    return "arbol_" + root[:40] + "_" + hashlib.sha256(root.encode("ascii")).hexdigest()[:16]


class Creation:
    """Own only the folders and database this attempt made; keep a receipt when rollback cannot be proved."""

    def __init__(self, paths: Places, record: Record) -> None:
        validate_record(record, complete=True)
        self.paths = paths
        self.record = record
        self.root = paths.roots / record["root"]
        self.settings = paths.settings / record["root"]
        self.receipt = self.root / ".creating.json"
        self.root_owned = False
        self.settings_owned = False
        self.database: Database | None = None
        self.database_created = False
        self.uncertain = False
        self.committed = False

    def __enter__(self) -> Creation:
        a, b = self.root.resolve(), self.settings.resolve()
        if a.is_relative_to(b) or b.is_relative_to(a):
            raise Refused("invalid_input", "The Root's state and settings targets must not overlap.")
        if os.path.lexists(self.root) or os.path.lexists(self.settings):
            raise Refused("already_exists", "The Root's state or settings target already exists.")
        try:
            self.root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.mkdir(mode=0o700)
            self.root_owned = True
            self.settings.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.settings.mkdir(mode=0o700)
            self.settings_owned = True
            atomic_write(str(self.receipt), json_text({"record": self.record, "databaseCreated": False}, 2) + b"\n")
        except BaseException:
            self.rollback()
            raise
        return self

    def make_database(self, database: Database) -> None:
        self.database = database
        try:
            database.create(self.record["database"])
        except DatabaseError as error:
            self.uncertain = error.uncertain
            raise
        self.database_created = True
        atomic_write(str(self.receipt), json_text({"record": self.record, "databaseCreated": True}, 2) + b"\n")

    def publish(self) -> None:
        save_record(self.paths, self.record, complete=True)
        self.receipt.unlink()
        self.committed = True

    def rollback(self) -> None:
        if self.uncertain:
            raise DatabaseError(f"Database creation has an uncertain outcome; recovery files are kept in {self.root}.",
                                uncertain=True)
        if self.database_created and self.database is not None:
            try:
                self.database.drop(self.record["database"])
            except Exception as error:
                raise DatabaseError(f"Creation rollback could not remove the new database; recovery files are kept "
                                    f"in {self.root}.", uncertain=True) from error
        try:
            if self.settings_owned:
                shutil.rmtree(self.settings)
            if self.root_owned:
                shutil.rmtree(self.root)
        except OSError as error:
            raise Refused("operation_failed", f"Creation rollback could not remove its folders; recovery location: "
                                              f"{self.root}.") from error

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 traceback: TracebackType | None) -> None:
        if not self.committed:
            self.rollback()
