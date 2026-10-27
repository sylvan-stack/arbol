#!/usr/bin/env python3
"""Explicit source-only design snapshot, or offline provenance verification (BKD-D35)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = [
    "src/sections/ElmaFrame.svelte",
    "src/sections/Response.svelte",
    "src/sections/ResponseReader.svelte",
    "src/sections/PinnedMessage.svelte",
    "src/sections/HistoryTree.svelte",
    "src/sections/Composer.svelte",
    "src/patterns/Modal.svelte",
    "src/sections/elma-types.ts",
    "src/styles/tokens.css",
    "src/styles/system.css",
    "docs/licenses/Hanken-Grotesk-OFL.txt",
    "docs/licenses/Spline-Sans-Mono-OFL.txt",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(source: Path) -> list[str]:
    found: set[str] = set()

    def visit(relative: str) -> None:
        path = source / relative
        if relative in found:
            return
        if not relative.startswith(("src/", "docs/licenses/")) or not path.is_file():
            raise ValueError("Only maintained source and font notices can be copied.")
        found.add(relative)
        if path.suffix not in (".svelte", ".ts", ".css"):
            return
        for name in re.findall(r"(?:from\s*|import\s*|@import\s*)['\"]([^'\"]+)['\"]", path.read_text()):
            if not name.startswith("."):
                continue
            target = path.parent / name
            choices = [target, target.with_suffix(".ts"), target.with_suffix(".svelte")]
            selected = next((p for p in choices if p.is_file()), None)
            if selected is None or source not in selected.resolve().parents:
                raise ValueError("A maintained source import cannot be resolved.")
            visit(str(selected.resolve().relative_to(source)))

    for relative in ENTRIES:
        visit(relative)
    return sorted(found)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "ui/elma/design-system"
    manifest = target / "manifest.json"
    if args.check:
        data = json.loads(manifest.read_text())
        actual = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file() and p != manifest)
        if actual != sorted(data["files"]) or any(
            digest(target / p) != expected for p, expected in data["files"].items()
        ):
            raise ValueError("The renderer design snapshot differs from its recorded source.")
        if args.source:
            source = args.source.resolve(strict=True)
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
            ancestor = (
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", data["commit"], head], cwd=source, check=False
                ).returncode
                == 0
            )
            if (
                not ancestor
                or files(source) != sorted(data["files"])
                or any(digest(source / p) != expected for p, expected in data["files"].items())
            ):
                raise ValueError("The maintained design source needs an explicit synchronized snapshot.")
        print("Elma design snapshot verified:", len(actual), "source/notice files at", data["commit"])
        return
    if args.source is None:
        raise ValueError("--source must name the maintained design-system checkout.")
    source = args.source.resolve(strict=True)
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source, text=True):
        raise ValueError("Commit maintained design changes before synchronizing their source.")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    selected = files(source)
    if target.exists():
        shutil.rmtree(target)
    for relative in selected:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, path)
    manifest.write_text(
        json.dumps(
            {
                "repository": "https://github.com/sylvan-stack/arbol-design-system",
                "commit": head,
                "files": {p: digest(source / p) for p in selected},
            },
            indent=2,
        )
        + "\n"
    )
    print("Synchronized", len(selected), "maintained source/notice files from", head)


if __name__ == "__main__":
    main()
