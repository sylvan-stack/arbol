"""Verify layout 2 and missing-archive refusal on one disposable PostgreSQL server."""

from __future__ import annotations

import json
import os
import pwd
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE / "database"), str(SOURCE / "src")]

import probe_database_server as probe  # noqa: E402
import recovery  # noqa: E402
from archive_volume import MERCURY, ArchiveUnavailable, require_archive  # noqa: E402
from database_server import BIN, Places, postmaster_pid, run  # noqa: E402
from migrate_schema import Refusal, Target, Upgrade, initialize, load_manifest, lookup, upgrade  # noqa: E402

from arbol_installation.admission import DIRECTORY, prepare_directory, runtime_folder  # noqa: E402


def postgres(places: Places, name: str, *arguments: str) -> None:
    result = run([str(BIN / name), *arguments], places.home, timeout=90)
    if result.returncode:
        raise RuntimeError(f"{name} refused the disposable server operation: {result.stderr.strip()}")


def external_disk_refused(context: probe.Context) -> None:
    def external_df(command: list[str], home: Path) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["/bin/df", "-Pk"]:
            command = [*command[:2], str(MERCURY)]
        return run(command, home)

    if not MERCURY.is_mount():
        raise RuntimeError("The external-disk check needs the mounted Mercury volume.")
    with patch.object(probe, "run", side_effect=external_df):
        try:
            probe.check_data_folder(context)
        except probe.Failed as error:
            if "does not lie on the Mac's own disk" in str(error):
                return
            raise
    raise AssertionError("The data-folder probe accepted Mercury's filesystem.")


def refuse_archive(command: Callable[[], object]) -> None:
    try:
        command()
    except ArchiveUnavailable:
        return
    except Refusal as error:
        if error.status == "archive_unavailable":
            return
        raise
    raise AssertionError("The archive-dependent operation was accepted.")


def forbidden(*arguments: object, **keywords: object) -> NoReturn:
    raise AssertionError("Missing Mercury permitted an exclusive lease or a recovery proof.")


def journey(places: Places) -> dict[str, object]:
    refuse_archive(require_archive)
    places.prepare()
    places.folder.mkdir(mode=0o700)
    places.socket.mkdir(mode=0o700)
    runtime = runtime_folder(places.home)
    prepare_directory(runtime)
    owner = pwd.getpwuid(os.getuid()).pw_name
    port = 5433
    target = Target("layout_proof", str(places.socket), port, owner)
    manifest = load_manifest()
    postgres(places, "initdb", "-D", str(places.data), "-U", owner, "-A", "trust", "-E", "UTF8", "--no-instructions")
    try:
        options = shlex.join(["-c", "listen_addresses=", "-k", str(places.socket), "-p", str(port)])
        postgres(places, "pg_ctl", "-D", str(places.data), "-l", str(places.launchd_log), "-w", "-o", options, "start")
        postgres(places, "createdb", "-h", str(places.socket), "-p", str(port), "-U", owner, target.database)
        initialize(target, manifest, authorized=True)
        original = lookup(target, manifest)
        if original != {"status": "ready", "revision": 1, "compatibilityVersion": 1}:
            raise AssertionError("The disposable baseline needs schema revision 1.")
        context = probe.Context(places, restart=False)
        internal = probe.check_data_folder(context)
        external_disk_refused(context)
        admission = runtime / DIRECTORY
        locks = {path.name: path.stat().st_ino for path in admission.iterdir()}
        destination = places.home / "unused-archive"
        snapshot, restore = destination / "snapshot", destination / "restore"
        refuse_archive(lambda: recovery.capture(target, destination / "release", snapshot,
                                                maintenance_session="a" * 32, exclusive=forbidden))
        refuse_archive(lambda: recovery.restore(target, snapshot, restore))
        request = Upgrade(2, "a" * 32, "b" * 64, "c" * 64, snapshot, restore / "restore.json")
        refuse_archive(lambda: upgrade(target, manifest, request, exclusive=forbidden, verify_recovery=forbidden))
        if (destination.exists() or lookup(target, manifest) != original
                or {path.name: path.stat().st_ino for path in admission.iterdir()} != locks):
            raise AssertionError("Archive refusal changed the schema, admission or recovery destination.")
        if (places.home / "Library/Application Support/Arbol").exists():
            raise AssertionError("The disposable installation created a layout-1 directory.")
        return {"schema": original, "internal": internal["internal"], "externalDiskRefused": True,
                "data": str(places.data), "socket": str(places.socket),
                "archiveUnavailable": ["snapshot", "restore", "upgrade"], "admissionPreserved": True}
    finally:
        if postmaster_pid(places.data) is not None:
            postgres(places, "pg_ctl", "-D", str(places.data), "-w", "-m", "fast", "stop")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="arbol-layout2-", dir="/private/tmp") as workspace:
        home = Path(workspace) / "home"
        home.mkdir(mode=0o700)
        print(json.dumps(journey(Places(home))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
