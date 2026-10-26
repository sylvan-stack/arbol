"""Serialized catalogue mutations and creation compensation (ARC-D65–67)."""

import errno
import fcntl
import hashlib
import os
import re
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

from arbol_builds.launcher import BUILD_PATTERN, SAFE_INTEGER, Record, default_record, read_records
from arbol_builds.roots import current_root
from arbol_builds.service import atomic_write, json_text, now

from .database import Database, DatabaseError
from .model import (
    Places,
    Refused,
    catalogue,
    database_name,
    identifier,
    nonblank,
    save_record,
    selected,
    validate_record,
)


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


def contract_version(value: str) -> int:
    if len(value) > 16 or re.fullmatch(r"[1-9][0-9]*", value) is None or int(value) > SAFE_INTEGER:
        raise Refused("invalid_input", "A Root Contract version must be a positive safe whole number.")
    return int(value)


def create(paths: Places, root: str, options: dict[str, str]) -> Record:
    identifier(root)
    name = nonblank(options.get("--name"), "Display name")
    version = contract_version(options["--root-contract"]) if "--root-contract" in options else None
    target_database = database_name(options.get("--database-name", default_database_name(root)))
    source_name = identifier(options["--from"]) if "--from" in options else None
    if source_name == root:
        raise Refused("invalid_input", "A Root cannot grow from itself.")
    with catalogue_lock(paths):
        source = selected(paths, source_name) if source_name is not None else None
        if any(record.get("database") == target_database for record in catalogue(paths)):
            raise Refused("already_exists", "Another retained Root already names that database.")
        app = default_record(str(paths.registry), read_records(str(paths.registry), "arbol-app"))
        record: Record = {"root": root, "name": name, "status": "preparing", "createdAt": now(),
                          "database": target_database, "app": app["build"] if app is not None else "0",
                          "rootContract": version if version is not None else source["rootContract"] if source else 1}
        if source is not None:
            record["grewFrom"] = source["root"]
        with Creation(paths, record) as attempt:
            if source is not None:
                settings = paths.settings / source["root"]
                if os.path.lexists(settings):
                    if not settings.is_dir():
                        raise Refused("operation_failed", "The source Root's settings are not a directory.")
                    shutil.copytree(settings, attempt.settings, symlinks=True, dirs_exist_ok=True)
            attempt.make_database(Database(paths))
            attempt.publish()
        return record


def exchanges_directory(root: Path) -> None:
    """Establish the Root-owned coordination directory without following or replacing a link."""
    target = root / "exchanges"
    try:
        try:
            target.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(target.lstat().st_mode):
            raise Refused("operation_failed", "The Root's exchanges path must be a directory, not a file or symlink.")
    except OSError as error:
        raise Refused("operation_failed", "Cannot establish the Root's exchanges directory.") from error


def ready(paths: Places, root: str) -> Record:
    with catalogue_lock(paths):
        record = dict(selected(paths, root))
        candidates = [build for build in read_records(str(paths.registry), "arbol-trunk/trivial")
                      if record["rootContract"] in build["rootContracts"]]
        if default_record(str(paths.registry), candidates) is None:
            raise Refused("no_fit", f"Root {root} needs a runnable working Trivial Trunk Build for Root Contract "
                                    f"{record['rootContract']}.")
        exchanges_directory(paths.roots / root)
        record["status"] = "working"
        record.pop("failed", None)
        save_record(paths, record)
        return record


def fail(paths: Places, root: str, reason: object) -> Record:
    explanation = nonblank(reason, "Failure reason")
    with catalogue_lock(paths):
        record = dict(selected(paths, root))
        if record["status"] != "working":
            raise Refused("invalid_input", "Only a working Root can be marked failed.")
        record["status"] = "failed"
        record["failed"] = {"at": now(), "reason": explanation}
        save_record(paths, record)
        return record


def app(paths: Places, root: str, number: str) -> Record:
    if BUILD_PATTERN.fullmatch(number) is None:
        raise Refused("invalid_input", "An App Build number is canonical lower-case hexadecimal, without leading zero.")
    with catalogue_lock(paths):
        record = dict(selected(paths, root))
        validate_record(record)
        found = default_record(str(paths.registry), [build for build in read_records(str(paths.registry), "arbol-app")
                                                     if build["build"] == number])
        if found is None:
            raise Refused("build_unavailable", f"No runnable working arbol-app@{number} Build is available.")
        if int(number, 16) < int(record.get("app", "0"), 16):
            raise Refused("invalid_input", "The App minimum may be raised or repeated, never lowered.")
        record["app"] = number
        save_record(paths, record)
        return record


def distinct_targets(state: Path, settings: Path) -> None:
    a, b = state.resolve(), settings.resolve()
    if a.is_relative_to(b) or b.is_relative_to(a):
        raise Refused("invalid_input", "The Root's state and settings targets must not overlap.")


def remove(paths: Places, root: str) -> Record:
    with catalogue_lock(paths):
        record = selected(paths, root)
        records = catalogue(paths)
        current = current_root(records)
        if current is not None and current["root"] == root:
            raise Refused("current_root", "The current Root cannot be removed.")
        name = database_name(record.get("database"))
        if any(other["root"] != root and other.get("database") == name for other in records):
            raise Refused("invalid_input", "Another retained Root names the same database; removal is refused.")
        state, settings = paths.roots / root, paths.settings / root
        if state.is_symlink() or settings.is_symlink():
            raise Refused("invalid_input", "The Root's removal targets must not be symlinks.")
        distinct_targets(state, settings)
        if not state.is_dir() or (os.path.lexists(settings) and not settings.is_dir()):
            raise Refused("operation_failed", "The Root's state/settings targets must be directories.")
        Database(paths).drop(name)
        try:
            if settings.exists():
                shutil.rmtree(settings)
            # Keep root.json until all payload has gone, so an ordinary cleanup failure can be retried.
            for child in state.iterdir():
                if child.name == "root.json":
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            (state / "root.json").unlink()
            state.rmdir()
        except OSError as error:
            if state.is_dir() and not state.is_symlink() and not (state / "root.json").exists():
                try:
                    save_record(paths, record)
                except Exception:
                    pass
            raise Refused("operation_failed", f"The database was removed, but folder cleanup for Root {root} "
                                              "is incomplete; retry remove or inspect its remaining files.") from error
        return record


class Creation:
    """Own only the folders and database this attempt made; keep a receipt when rollback cannot be proved."""

    def __init__(self, paths: Places, record: Record) -> None:
        validate_record(record, complete=True)
        self.paths = paths
        self.record = dict(record)
        self.root_name = record["root"]
        self.database_name = record["database"]
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
        distinct_targets(self.root, self.settings)
        if os.path.lexists(self.root) or os.path.lexists(self.settings):
            raise Refused("already_exists", "The Root's state or settings target already exists.")
        try:
            self.root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.mkdir(mode=0o700)
            self.root_owned = True
            exchanges_directory(self.root)
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
            database.create(self.database_name)
        except DatabaseError as error:
            self.uncertain = error.uncertain
            raise
        self.database_created = True
        atomic_write(str(self.receipt), json_text({"record": self.record, "databaseCreated": True}, 2) + b"\n")

    def publish(self) -> None:
        if self.record.get("root") != self.root_name or self.record.get("database") != self.database_name:
            raise Refused("invalid_input", "A creation's Root/database identity cannot change after reservation.")
        save_record(self.paths, self.record, complete=True)
        self.receipt.unlink()
        self.committed = True

    def rollback(self) -> None:
        if self.uncertain:
            raise DatabaseError(f"Database creation has an uncertain outcome; recovery files are kept in {self.root}.",
                                uncertain=True)
        if self.database_created and self.database is not None:
            try:
                self.database.drop(self.database_name)
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
