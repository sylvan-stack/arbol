"""Build and verify the self-contained renderer; serving it needs no Node runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload(folder: Path) -> dict[str, str]:
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValueError("The renderer payload cannot contain symlinks.")
        if path.is_file() and path != folder / "bundle.json":
            result[str(path.relative_to(folder))] = digest(path)
    return result


class Index(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csp = ""
        self.assets: list[str] = []
        self.inline = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta" and (values.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = values.get("content") or ""
        if tag == "script":
            self.inline |= not bool(values.get("src"))
            self.assets.append(values.get("src") or "")
        if tag == "link" and values.get("rel") in {"stylesheet", "modulepreload"}:
            self.assets.append(values.get("href") or "")


def verify(folder: Path, build: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / "bundle.json").read_text())
    if (data.get("format") != 1 or data.get("build") != build or data.get("files") != payload(folder)
            or not re.fullmatch(r"[0-9a-f]{40}", data.get("designSystem", {}).get("commit", ""))):
        raise ValueError("The renderer must match its Build, design provenance and every asset hash.")
    index = Index()
    index.feed((folder / "index.html").read_text())
    if index.csp != CSP or index.inline or not index.assets:
        raise ValueError("The renderer needs its exact local-only CSP and external bundle scripts.")
    for asset in index.assets:
        if not re.fullmatch(r"\./assets/[A-Za-z0-9_.-]+", asset) or not (folder / asset).is_file():
            raise ValueError("Every renderer script and stylesheet must be a local bundle asset.")
    fonts = [p for p in (folder / "assets").iterdir() if p.suffix in {".woff", ".woff2"}]
    if len(fonts) < 2 or not (folder / "LICENSES.json").is_file():
        raise ValueError("The renderer must carry its fonts and license notices.")
    for style in (folder / "assets").glob("*.css"):
        for url in re.findall(r"url\(([^)]+)\)", style.read_text()):
            name = url.strip("\"' ")
            if not re.fullmatch(r"(?:\./)?[A-Za-z0-9_.-]+\.(?:woff2?|ttf)", name) or not (style.parent / name).is_file():
                raise ValueError("Every CSS font must be bundled locally.")
    return data


def licenses(source: Path, folder: Path) -> None:
    lock = json.loads((source / "package-lock.json").read_text())
    records = []
    for relative, entry in sorted(lock["packages"].items()):
        if not relative.startswith("node_modules/"):
            continue
        package = source / relative
        if not package.is_dir():
            continue  # Platform-specific optional build dependencies are not installed or bundled.
        name = relative.removeprefix("node_modules/")
        notices = []
        for path in sorted(package.iterdir()):
            if path.is_file() and re.match(r"^(?:license|licence|copying|notice)(?:\.|$)", path.name, re.I):
                destination = folder / "licenses" / name / path.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                notices.append(str(destination.relative_to(folder)))
        records.append({"package": name, "version": entry["version"], "license": entry.get("license"), "notices": notices})
    (folder / "LICENSES.json").write_text(json.dumps(records, indent=2) + "\n")


def package(root: Path, destination: Path, build: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-z]+", build):
        raise ValueError("A numbered Build is required for the renderer.")
    source = root / "ui/elma"
    subprocess.run([sys.executable, "-I", "-B", str(root / "tools/sync_elma_design.py"), "--check"], check=True, cwd=root)
    subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], check=True, cwd=source, timeout=180)
    subprocess.run(["npm", "run", "check"], check=True, cwd=source, timeout=60)
    subprocess.run(["npm", "run", "build"], check=True, cwd=source, timeout=120,
                   env={**os.environ, "ARBOL_BUILD_NUMBER": build})
    shutil.copytree(source / "dist", destination)
    licenses(source, destination)
    snapshot = json.loads((source / "design-system/manifest.json").read_text())
    source_files = ["package.json", "package-lock.json", "index.html", "vite.config.ts", "svelte.config.js", "tsconfig.json"]
    source_files += [str(p.relative_to(source)) for base in ("src", "design-system") for p in (source / base).rglob("*") if p.is_file()]
    data = {"format": 1, "build": build, "designSystem": {"repository": snapshot["repository"], "commit": snapshot["commit"],
            "manifestSha256": digest(source / "design-system/manifest.json")},
            "lockSha256": digest(source / "package-lock.json"), "sources": {name: digest(source / name) for name in sorted(source_files)},
            "files": payload(destination)}
    (destination / "bundle.json").write_text(json.dumps(data, indent=2) + "\n")
    return verify(destination, build)
