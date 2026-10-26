"""How long a launcher adds to a start: on demand, not part of the tests.

    uv run --no-sync python tests/launcher_benchmark.py [--python <interpreter>] [--node-launcher <file>]
        [--pairs <n>] [--output <file.json>]

The method of 7 October 2026 (builds/evidence/launcher-benchmark-2026-10-07.json): a tiny sample
component built twice into a temporary registry, five warm-up rounds, then rounds in rotating
order, each starting the Build's program directly and through the launcher; the added time is the
launcher's start minus the direct start of the same round. `--python` names the interpreter the
launcher is written for (by default the one running this script; use the installed pinned Python
to measure what is installed). `--node-launcher` names a launcher written by the earlier Node.js
tool: it is pointed at the same registry and timed in the same rounds.

The launcher arbol-trunk (SYL-179) is timed in the same rounds: a sample Trunk built twice for
Root Contract version 1, one Root of that version in the temporary home, and two calls, `run`
for the current Root and the Trunk trivial, and the call arbol-root makes, which names the Root,
the Trunk and the Build; each against a direct start of the same Build.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arbol_builds.config import Locations  # noqa: E402
from arbol_builds.service import Stop, build_component, write_launcher  # noqa: E402

SAMPLE = {"entry": "program.sh", "checks": [{"name": "ready", "command": '"$ARBOL_BUILD_DIR/program.sh"'}],
          "build": ['cp program.sh "$ARBOL_BUILD_DIR/program.sh"; chmod +x "$ARBOL_BUILD_DIR/program.sh"']}


def repository(repo: str, env: dict[str, str], description: dict[str, object]) -> None:
    """A sample repository whose program prints "ready", committed."""
    os.mkdir(repo)
    Path(repo, "package.json").write_text('{"version":"1.0.0"}\n')
    Path(repo, "program.sh").write_text("#!/bin/sh\necho ready\n")
    Path(repo, "arbol-build.json").write_text(json.dumps({**SAMPLE, **description}))
    for arguments in (["git", "init", "-q", "-b", "main"], ["git", "add", "."],
                      ["git", "commit", "-qm", "Sample"]):
        # Sample commits use the caller's existing identity and hooks, outside the benchmark's fake home.
        subprocess.run(arguments, cwd=repo, env={**env, "HOME": str(Path.home())}, check=True, capture_output=True)


def run(arguments: list[str], cwd: str, env: dict[str, str]) -> float:
    started = time.perf_counter()
    result = subprocess.run(arguments, cwd=cwd, env=env, capture_output=True, check=False)
    elapsed = (time.perf_counter() - started) * 1000
    if result.returncode != 0 or result.stdout != b"ready\n":
        raise RuntimeError(f"{arguments[0]} failed: {result.stdout!r} {result.stderr!r}")
    return elapsed


def stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {"medianMs": round(statistics.median(ordered), 2),
            "p95Ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--node-launcher")
    parser.add_argument("--pairs", type=int, default=30)
    parser.add_argument("--output")
    options = parser.parse_args()
    home = tempfile.mkdtemp(prefix="arbol-launcher-benchmark-")
    try:
        repo, registry, folder = (os.path.join(home, name) for name in ("repository", "registry", "bin"))
        trunk_repo = os.path.join(home, "trunk repository")
        env = {"HOME": home, "PATH": "/usr/bin:/bin"}
        repository(repo, env, {"component": "sample"})
        repository(trunk_repo, env, {"component": "arbol-trunk/trivial", "rootContracts": [1]})
        root = os.path.join(home, "Library/Application Support/Arbol/roots/sapling")
        os.makedirs(root)
        Path(root, "root.json").write_text(json.dumps({
            "root": "sapling", "name": "First Sapling", "status": "working", "createdAt": "2026-10-16T09:00:00.000Z",
            "database": "arbol_sapling", "app": "1", "rootContract": 1}))
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            for component, source in (("sample", repo), ("sample", repo), ("arbol-trunk/trivial", trunk_repo),
                                      ("arbol-trunk/trivial", trunk_repo)):
                if build_component(component, Locations(registry, folder, source), Stop())["status"] != "working":
                    raise RuntimeError(f"The sample {component} did not build.")
        finally:
            os.environ.clear()
            os.environ.update(saved)
        write_launcher(folder, registry, "sample", options.python)
        write_launcher(folder, registry, "arbol-trunk", options.python)
        trunks = os.path.join(folder, "arbol-trunk")
        variants = {"direct": [os.path.join(registry, "sample/2/program.sh")], "python": [os.path.join(folder, "sample")],
                    "trunk-direct": [os.path.join(registry, "arbol-trunk/trivial/2/program.sh")],
                    "trunk": [trunks, "run"], "trunk-named": [trunks, "--root", "sapling", "trivial", "-v", "2", "run"]}
        if options.node_launcher:
            lines = Path(options.node_launcher).read_text().rstrip("\n").split("\n")
            lines[-1] = f"launch({json.dumps(registry)}, \"sample\", process.argv.slice(2));"
            node = os.path.join(folder, "sample-node")
            Path(node).write_text("\n".join(lines) + "\n")
            os.chmod(node, 0o755)
            variants["node"] = [node]
            env["PATH"] = f"{os.path.dirname(shutil.which('node') or '/usr/bin/node')}:/usr/bin:/bin"
        names = list(variants)
        for _ in range(5):
            for name in names:
                run(variants[name], repo, env)
        times: dict[str, list[float]] = {name: [] for name in names}
        for index in range(options.pairs):
            order = names[index % len(names):] + names[:index % len(names)]
            for name in order:
                times[name].append(run(variants[name], repo, env))

        def added(launched: str, direct: str) -> dict[str, float]:
            return stats([one - other for one, other in zip(times[launched], times[direct], strict=True)])
        record: dict[str, object] = {
            "date": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "platform": sys.platform, "arch": platform.machine(), "pairs": options.pairs, "workingBuilds": 2,
            "python": options.python, "launcherBytes": os.path.getsize(variants["python"][0]),
            "direct": stats(times["direct"]), "launched": stats(times["python"]), "added": added("python", "direct"),
            "trunk": {"launcherBytes": os.path.getsize(trunks), "direct": stats(times["trunk-direct"]),
                      "run": {"launched": stats(times["trunk"]), "added": added("trunk", "trunk-direct")},
                      "named": {"launched": stats(times["trunk-named"]), "added": added("trunk-named", "trunk-direct")}},
        }
        if "node" in times:
            node_version = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True).stdout.strip()
            record["node"] = {"version": node_version, "launcherBytes": os.path.getsize(variants["node"][0]),
                              "launched": stats(times["node"]), "added": added("node", "direct")}
        text = json.dumps(record, indent=2) + "\n"
        if options.output:
            Path(options.output).write_text(text)
        sys.stdout.write(text)
        return 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
