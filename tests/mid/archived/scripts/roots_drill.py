"""Repeatable ARC-1.4 drill: a damaged Root isolates itself in the catalogue and actual Trunk launcher.

Run with the checkout's Python, optionally --tool /absolute/path/to/installed/arbol-roots.
Every record, registry, launcher and home belongs to this drill. No database or vendor is called.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_builds.service import write_launcher  # noqa: E402


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def drill(tool: str | None = None) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="Arbol's Root drill ") as temporary:
        home = Path(temporary)
        roots = home / "Library/Application Support/Arbol/roots"
        registry = home / "registry"
        bin_dir = home / "bin"
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
        records = {}
        for name, hour in (("sapling", "09"), ("second", "10")):
            record = {"root": name, "name": name.title(), "status": "working",
                      "createdAt": f"2026-10-26T{hour}:00:00.000Z", "rootContract": 1,
                      "app": "0", "database": "private_" + name}
            folder = roots / name
            folder.mkdir(parents=True)
            (folder / "root.json").write_text(json.dumps(record))
            records[name] = record
        folder = registry / "arbol-trunk/trivial/1"
        folder.mkdir(parents=True)
        (folder / "build.json").write_text(json.dumps({
            "component": "arbol-trunk/trivial", "build": "1", "packageVersion": "1.0.0", "status": "working",
            "startedAt": "2026-10-26T09:00:00.000Z", "finishedAt": "2026-10-26T09:00:01.000Z",
            "source": {"repository": "/private/drill", "branch": "main", "commit": "fixture",
                       "uncommittedChanges": False}, "entry": "program", "rootContracts": [1],
            "checks": [{"name": "private", "passed": True}]}))
        (folder / "program").write_text("#!/bin/sh\nexit 0\n")
        (folder / "program").chmod(0o755)
        write_launcher(str(bin_dir), str(registry), "arbol-trunk", sys.executable)
        prefix = [tool] if tool else [sys.executable, "-I", "-B", str(ROOT / "bin/roots_entry.py")]

        def run(arguments: list[str], code: int = 0) -> Any:
            result = subprocess.run(arguments, env=env, cwd=home, capture_output=True, timeout=20, check=False)
            if result.returncode != code:
                raise RuntimeError(f"Drill command returned {result.returncode}, expected {code}: "
                                   + os.fsdecode(result.stdout + result.stderr))
            return json.loads(result.stdout)

        def catalogue(*args: str, code: int = 0) -> Any:
            return run([*prefix, *args, "--registry-dir", str(registry)], code)

        launcher = str(bin_dir / "arbol-trunk")
        require(catalogue("show")["root"] == "second", "The catalogue did not select the newer working Root.")
        require(run([launcher, "list"])["root"] == "second", "The Trunk launcher disagreed before damage.")
        (roots / "second/root.json").write_text("{")
        listed = catalogue("list")
        require([record["root"] for record in listed] == ["sapling"], "Damage did not isolate only its own Root.")
        require(listed[0]["current"], "The remaining working Root was not marked current.")
        require(catalogue("ready", "second", code=1)["error"]["code"] == "unknown_root",
                "Ready did not refuse the damaged Root.")
        require(catalogue("ready", "sapling")["root"] == "sapling", "Damage prevented another Root's readiness.")
        require(run([launcher, "--root", "second", "list"], 1)["error"]["code"] == "unknown_root",
                "The Trunk launcher did not refuse the damaged Root.")
        require(run([launcher, "list"])["root"] == "sapling", "The Trunk launcher did not fall back to the working Root.")
        (roots / "second/root.json").write_text(json.dumps(records["second"]))
        require(catalogue("ready", "second")["status"] == "working", "Ready did not reread the repaired record.")
        require(catalogue("show")["root"] == "second", "The catalogue did not reread the repaired current Root.")
        require(run([launcher, "list"])["root"] == "second", "The Trunk launcher did not reread the repair.")
    return {"passed": True, "checks": ["catalogue-isolation", "ready-isolation", "trunk-isolation", "repair-reread"],
            "databaseRequests": 0, "vendorRequests": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool")
    options = parser.parse_args()
    try:
        print(json.dumps(drill(options.tool)))
        return 0
    except Exception as error:
        print(json.dumps({"passed": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
