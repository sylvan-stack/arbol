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
        env = {"HOME": home, "PATH": "/usr/bin:/bin"}
        os.mkdir(repo)
        Path(repo, "package.json").write_text('{"version":"1.0.0"}\n')
        Path(repo, "program.sh").write_text("#!/bin/sh\necho ready\n")
        Path(repo, "arbol-build.json").write_text(json.dumps({
            "component": "sample", "entry": "program.sh",
            "build": ['cp program.sh "$ARBOL_BUILD_DIR/program.sh"; chmod +x "$ARBOL_BUILD_DIR/program.sh"'],
            "checks": [{"name": "ready", "command": '"$ARBOL_BUILD_DIR/program.sh"'}]}))
        for arguments in (["git", "init", "-q", "-b", "main"], ["git", "add", "."],
                          ["git", "-c", "user.name=Benchmark", "-c", "user.email=builds@example.invalid",
                           "commit", "-qm", "Sample"]):
            subprocess.run(arguments, cwd=repo, env=env, check=True, capture_output=True)
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            for _ in range(2):
                if build_component("sample", Locations(registry, folder, repo), Stop())["status"] != "working":
                    raise RuntimeError("The sample did not build.")
        finally:
            os.environ.clear()
            os.environ.update(saved)
        write_launcher(folder, registry, "sample", options.python)
        variants = {"direct": os.path.join(registry, "sample/2/program.sh"), "python": os.path.join(folder, "sample")}
        if options.node_launcher:
            lines = Path(options.node_launcher).read_text().rstrip("\n").split("\n")
            lines[-1] = f"launch({json.dumps(registry)}, \"sample\", process.argv.slice(2));"
            node = os.path.join(folder, "sample-node")
            Path(node).write_text("\n".join(lines) + "\n")
            os.chmod(node, 0o755)
            variants["node"] = node
            env["PATH"] = f"{os.path.dirname(shutil.which('node') or '/usr/bin/node')}:/usr/bin:/bin"
        names = list(variants)
        for _ in range(5):
            for name in names:
                run([variants[name]], repo, env)
        times: dict[str, list[float]] = {name: [] for name in names}
        for index in range(options.pairs):
            order = names[index % len(names):] + names[:index % len(names)]
            for name in order:
                times[name].append(run([variants[name]], repo, env))
        record: dict[str, object] = {
            "date": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "platform": sys.platform, "arch": platform.machine(), "pairs": options.pairs, "workingBuilds": 2,
            "python": options.python, "launcherBytes": os.path.getsize(variants["python"]),
            "direct": stats(times["direct"]), "launched": stats(times["python"]),
            "added": stats([launched - direct for launched, direct in zip(times["python"], times["direct"], strict=True)]),
        }
        if "node" in times:
            node_version = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True).stdout.strip()
            record["node"] = {"version": node_version, "launcherBytes": os.path.getsize(variants["node"]),
                              "launched": stats(times["node"]),
                              "added": stats([launched - direct for launched, direct
                                              in zip(times["node"], times["direct"], strict=True)])}
        text = json.dumps(record, indent=2) + "\n"
        if options.output:
            Path(options.output).write_text(text)
        sys.stdout.write(text)
        return 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
