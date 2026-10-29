"""Drills of the installed `arbol vigor`, the backend's tick and the learner (SYL-298, SYL-299); records go outside git.

    uv run --no-sync python scripts/radar_drill.py read [--arbol <launcher>] [--seconds <n>]
    uv run --no-sync python scripts/radar_drill.py refresh [--arbol <launcher>]
    uv run --no-sync python scripts/radar_drill.py tick [--arbol <launcher>] [--seconds <n>]
    uv run --no-sync python scripts/radar_drill.py learn [--arbol <launcher>]

`read` starts the installed backend by its name in a clean login shell, as the owner would, waits for its first tick,
stops it through its standard input, then runs `arbol vigor` and `arbol vigor --text` the same way: the owner's own
Subscriptions through the owner's current Root, with no vendor contacted. `refresh` runs the installed `arbol vigor
--refresh --text` and then a plain read in a private Root space: a private home whose Driver state folders are the
Drivers' test state folders, a private launcher folder with the installed Driver launchers, and a private PostgreSQL
cluster with the chat tables and the Vigor tables; the vendors of the test Subscriptions are contacted, the owner's
Subscriptions and Root are not. `tick` runs the installed backend in such a private Root space for `--seconds` and
counts the results its ticks recorded, at its first wake and three minutes later. `learn` is the scenario of
SGM-1.11 over the owner's own records: `arbol vigor learn`, then `arbol vigor profiles` as JSON and as text, by name in a
clean login shell on the owner's current Root; it may write a proposed profile and approves nothing, and no Driver
runs. `--arbol` names another launcher,
such as `bin/arbol` of a checkout, in place of the installed one. Every drill writes its record to
`~/Library/Logs/Arbol/radar-drill-<name>-<time>.json` and prints it.
"""

from __future__ import annotations

import json
import os
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from backend.support import PG, Cluster  # noqa: E402

HOME = Path.home()
LOGS = HOME / "Library/Logs/Arbol"
DRIVERS = ("claude", "codex", "pi")
TEST_STATE = {driver: HOME / f"Library/Application Support/Arbol/drivers/arbol-{driver}-driver" for driver in DRIVERS}
USAGE = (
    "Usage: uv run --no-sync python scripts/radar_drill.py read|refresh|tick|learn [--arbol <launcher>] [--seconds <n>]"
)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def login_shell(command: str, *, home: Path = HOME, stdin: int | None = None) -> subprocess.Popen[bytes]:
    """The command in a clean login shell, as the Instructions Hub prescribes for every CLI on this Mac."""
    return subprocess.Popen(
        [
            "/usr/bin/env",
            "-i",
            f"HOME={home}",
            f"USER={os.environ.get('USER', '')}",
            f"LOGNAME={os.environ.get('LOGNAME', '')}",
            "TERM=xterm-256color",
            "/bin/zsh",
            "-l",
            "-i",
            "-c",
            command,
        ],
        stdin=stdin if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def login_path() -> str:
    """The search path of the owner's clean login shell, so a program run with a private home finds the same tools."""
    child = login_shell('printf "%s" "$PATH"')
    out, _ = child.communicate(timeout=30)
    return out.decode()


def run(command: list[str], *, env: dict[str, str], timeout: float = 120) -> dict[str, Any]:
    """Run a command to its end and keep what it printed, its status and how long it took."""
    started = time.monotonic()
    child = subprocess.run(command, env=env, capture_output=True, timeout=timeout, check=False)
    return {
        "command": command,
        "status": child.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "stdout": child.stdout.decode(errors="replace"),
        "stderr": child.stderr.decode(errors="replace"),
    }


def first_line(child: subprocess.Popen[bytes], seconds: float) -> dict[str, Any] | None:
    """The backend's ready or error line, within the deadline; None when nothing came."""
    assert child.stdout is not None
    if not select.select([child.stdout], [], [], seconds)[0]:
        return None
    line = child.stdout.readline()
    try:
        value: object = json.loads(line)
    except ValueError:
        return {"raw": line.decode(errors="replace")}
    return value if isinstance(value, dict) else {"raw": line.decode(errors="replace")}


def stop(child: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Stop a backend through the end of its standard input, as the Swift App would, and keep how it ended."""
    assert child.stdin is not None
    started = time.monotonic()
    child.stdin.close()
    try:
        out, err = child.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        child.kill()
        out, err = child.communicate(timeout=10)
    return {
        "status": child.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "stdout": out.decode(errors="replace"),
        "stderr": err.decode(errors="replace"),
    }


class Space:
    """A private Root space: a home with the Drivers' test state folders, a launcher folder, a Root folder, a cluster."""

    def __init__(self, root: str, launcher: Path) -> None:
        self.root_id = root
        # Under /private/tmp, the resolved folder: the Pi Driver refuses a state path with a symbolic link in it,
        # and /tmp is one on macOS; the Pi test state folder is copied for the same reason, the others are linked.
        self.temp = tempfile.TemporaryDirectory(prefix="radar-", dir="/private/tmp")
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.bin = self.base / "bin"
        self.root = self.base / "root"
        self.settings = self.base / "settings"
        for folder in (self.home, self.bin, self.root, self.settings):
            folder.mkdir(mode=0o700)
        drivers = self.home / "Library/Application Support/Arbol/drivers"
        drivers.mkdir(parents=True, mode=0o700)
        for driver in DRIVERS:
            if not TEST_STATE[driver].is_dir():
                raise RuntimeError(f"The {driver} Driver's test state folder is missing: {TEST_STATE[driver]}")
            if driver == "pi":
                shutil.copytree(TEST_STATE[driver], drivers / driver, ignore=shutil.ignore_patterns("research"))
            else:
                (drivers / driver).symlink_to(TEST_STATE[driver])
            (self.bin / f"arbol-{driver}-driver").symlink_to(HOME / ".local/bin" / f"arbol-{driver}-driver")
        if (HOME / ".pi").is_dir():
            (self.home / ".pi").symlink_to(HOME / ".pi")  # Pi's own store, which holds the test Kimi token
        (self.home / ".arbol").mkdir(mode=0o700)
        for name in ("arbol-claude-driver.json", "arbol-codex-driver.json", "arbol-pi-driver.json"):
            source = HOME / ".arbol" / name
            if source.is_file():
                (self.home / ".arbol" / name).write_bytes(source.read_bytes())  # a Driver's settings, never a secret
        (self.root / "root.json").write_text(
            json.dumps(
                {
                    "root": root,
                    "name": "Radar drill",
                    "status": "working",
                    "database": "arbol_test",
                    "createdAt": now(),
                    "rootContract": 1,
                    "app": "0",
                }
            )
        )
        self.cluster = Cluster()
        try:
            subprocess.run(
                [str(PG / "psql"), "-X", "-v", "ON_ERROR_STOP=1", "-h", str(self.cluster.socket), "-p", "5432"]
                + ["-U", "bkd", "-d", "arbol_test"],
                input=(ROOT / "tests/radar/layout.sql").read_bytes(),
                capture_output=True,
                check=True,
                timeout=10,
            )
        except BaseException:
            self.cluster.close()
            raise

    def options(self) -> list[str]:
        """The Root and the isolation options: the Root is named for a checkout's launcher, which has no Build."""
        return [
            "--root",
            self.root_id,
            "--root-dir",
            str(self.root),
            "--bin-dir",
            str(self.bin),
            "--settings-dir",
            str(self.settings),
            "--database",
            self.cluster.address,
        ]

    def env(self, path: str) -> dict[str, str]:
        return {"HOME": str(self.home), "PATH": path, "TERM": "xterm-256color", "LC_ALL": "C.UTF-8"}

    def count(self, table: str) -> int:
        out = subprocess.check_output(
            [str(PG / "psql"), "-X", "-At", "-h", str(self.cluster.socket), "-p", "5432", "-U", "bkd", "-d"]
            + ["arbol_test", "-c", f"SELECT count(*) FROM {table}"],
            timeout=10,
        )
        return int(out.decode().strip())

    def rows(self, sql: str) -> list[str]:
        out = subprocess.check_output(
            [str(PG / "psql"), "-X", "-At", "-h", str(self.cluster.socket), "-p", "5432", "-U", "bkd", "-d"]
            + ["arbol_test", "-c", sql],
            timeout=10,
        )
        return out.decode().splitlines()

    def close(self) -> None:
        self.cluster.close()
        self.temp.cleanup()


def installed_entry(launcher: Path, root: str) -> Path:
    """The program a private Root space runs: the newest working Build's own entry for the installed launcher.

    The launcher chooses the Build through the owner's home folder, which a private space replaces, so the space runs
    the chosen Build's `bin/arbol` itself; a checkout's launcher is run as it is.
    """
    if launcher != HOME / ".local/bin/arbol":
        return launcher
    child = login_shell("arbol-builds list arbol")
    out, _ = child.communicate(timeout=30)
    records: object = json.loads(out)
    assert isinstance(records, list)
    working = [
        record
        for record in records
        if isinstance(record, dict) and record.get("status") == "working" and record.get("root") == root
    ]
    if not working:
        raise RuntimeError(f"No working arbol Build for the Root {root}.")
    newest = max(working, key=lambda record: int(str(record["build"]), 16))
    return HOME / "Library/Application Support/Arbol/builds/arbol" / str(newest["build"]) / "bin/arbol"


def current_root() -> str:
    child = login_shell("arbol-roots list")
    out, _ = child.communicate(timeout=30)
    rows: object = json.loads(out)
    assert isinstance(rows, list)
    current = [row["root"] for row in rows if isinstance(row, dict) and row.get("current") is True]
    if len(current) != 1:
        raise RuntimeError("The Root catalogue names no current Root.")
    return str(current[0])


def read(launcher: Path, seconds: float) -> dict[str, Any]:
    """The owner's read: the backend for one tick, then `arbol vigor` and `arbol vigor --text`, all by name."""
    name = launcher.name if launcher == HOME / ".local/bin/arbol" else str(launcher)
    record: dict[str, Any] = {"drill": "read", "launcher": name, "startedAt": now()}
    backend = login_shell(f"{shlex.quote(name)} backend", stdin=subprocess.PIPE)
    record["backend"] = {"first": first_line(backend, 30)}
    if backend.poll() is None:
        time.sleep(seconds)
        record["backend"]["stopped"] = stop(backend)
    else:
        record["backend"]["stopped"] = stop(backend)
    for extra in ("", " --text"):
        child = login_shell(f"{shlex.quote(name)} vigor{extra}")
        out, err = child.communicate(timeout=60)
        record["vigor" + extra.replace(" --", "-")] = {
            "status": child.returncode,
            "stdout": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace"),
        }
    return record


def learn(launcher: Path) -> dict[str, Any]:
    """The scenario of SGM-1.11: the learner over the owner's records, then every profile; nothing is approved."""
    installed = launcher == HOME / ".local/bin/arbol"
    root = current_root()
    # A checkout's launcher names the Root itself, since only a Build knows its Root.
    name = launcher.name if installed else f"{shlex.quote(str(launcher))} --root {shlex.quote(root)}"
    record: dict[str, Any] = {"drill": "learn", "launcher": name, "root": root, "startedAt": now()}
    for key, words in (
        ("learn", "vigor learn"),
        ("profiles", "vigor profiles"),
        ("profilesText", "vigor profiles --text"),
    ):
        child = login_shell(f"{name} {words}")
        out, err = child.communicate(timeout=120)
        answer: dict[str, Any] = {"status": child.returncode, "stdout": out.decode(errors="replace")}
        answer["stderr"] = err.decode(errors="replace")
        if key != "profilesText" and child.returncode == 0:
            answer["document"] = json.loads(out)
        record[key] = answer
    document = record["learn"].get("document")
    if isinstance(document, dict):
        record["summary"] = {
            "subscriptions": document["subscriptions"],
            "observations": len(document["observations"]),
            "trusted": sum(1 for item in document["observations"] if item["trusted"]),
            "estimates": document["estimates"],
            "proposed": (document["proposed"] or {}).get("version"),
        }
    return record


def refresh(launcher: Path) -> dict[str, Any]:
    """The refresh against the test Subscriptions in a private Root space, then a plain read of what it recorded."""
    root = current_root()
    program = installed_entry(launcher, root)
    space = Space(root, launcher)
    try:
        env = space.env(login_path())
        record: dict[str, Any] = {"drill": "refresh", "launcher": str(launcher), "program": str(program), "root": root}
        record["startedAt"] = now()
        record["refresh"] = run([str(program), "vigor", "--refresh", "--text", *space.options()], env=env, timeout=300)
        record["counts"] = {table: space.count(table) for table in ("vigor_reports", "vigor_results")}
        record["reports"] = space.rows(
            "SELECT driver || '/' || subscription || ' ' || outcome || ' ' || fetched_at FROM vigor_reports ORDER BY 1"
        )
        record["read"] = run([str(program), "vigor", *space.options()], env=env)
        record["countsAfterRead"] = {table: space.count(table) for table in ("vigor_reports", "vigor_results")}
        return record
    finally:
        space.close()


def tick(launcher: Path, seconds: float) -> dict[str, Any]:
    """The backend in a private Root space for `seconds`: the results its ticks recorded, one per Subscription each."""
    root = current_root()
    program = installed_entry(launcher, root)
    space = Space(root, launcher)
    try:
        env = space.env(login_path())
        record: dict[str, Any] = {"drill": "tick", "launcher": str(launcher), "program": str(program), "root": root}
        record["startedAt"] = now()
        backend = subprocess.Popen(
            [str(program), "backend", *space.options()],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        record["first"] = first_line(backend, 30)
        time.sleep(seconds)
        record["results"] = space.rows(
            "SELECT driver || '/' || subscription || ' ' || moment || ' ' || coalesce(vigor::text, 'unknown: ' || unknown)"
            " FROM vigor_results ORDER BY moment, driver, subscription"
        )
        record["counts"] = {table: space.count(table) for table in ("vigor_reports", "vigor_results")}
        record["ticks"] = space.rows("SELECT DISTINCT moment FROM vigor_results ORDER BY moment")
        record["stopped"] = stop(backend)
        return record
    finally:
        space.close()


def main(argv: list[str]) -> int:
    words: list[str] = []
    options: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i] in ("--arbol", "--seconds") and i + 1 < len(argv):
            options[argv[i]] = argv[i + 1]
            i += 2
        elif argv[i].startswith("--"):
            print(USAGE, file=sys.stderr)
            return 2
        else:
            words.append(argv[i])
            i += 1
    if len(words) != 1 or words[0] not in ("read", "refresh", "tick", "learn"):
        print(USAGE, file=sys.stderr)
        return 2
    launcher = Path(options.get("--arbol", str(HOME / ".local/bin/arbol"))).expanduser().resolve()
    seconds = float(options.get("--seconds", "10" if words[0] == "read" else "200"))
    if not launcher.is_file():
        print(f"No launcher at {launcher}.", file=sys.stderr)
        return 1
    if words[0] == "read":
        record = read(launcher, seconds)
    elif words[0] == "refresh":
        record = refresh(launcher)
    elif words[0] == "learn":
        record = learn(launcher)
    else:
        record = tick(launcher, seconds)
    record["finishedAt"] = now()
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f"radar-drill-{words[0]}-{record['startedAt'].replace(':', '')}.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    print(f"Recorded in {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
