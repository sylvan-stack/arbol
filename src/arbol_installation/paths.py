"""Installed paths shared by the Arbol tools and standalone launchers (ARC-5)."""

import os
import stat
from pathlib import Path

INSTALLATION_LAYOUT = 2


def installation_root(home: Path | None = None) -> Path:
    return (Path.home() if home is None else home) / ".arbol"


def build_registry(home: Path | None = None) -> Path:
    return (Path.home() if home is None else home) / "Builds/registries/arbol"


def build_payload_directory(registry: str | Path, component: str, build: str) -> Path:
    root = Path(registry)
    if root.resolve() == build_registry().resolve():
        root = Path.home() / ".local/lib/sylvan-stack/arbol/stable"
    return root / component / build


def postgres_folder(home: Path | None = None) -> Path:
    return installation_root(home) / "postgres"


def database_settings(home: Path | None = None) -> Path:
    return installation_root(home) / "database.json"


def prepare_installation(home: Path | None = None) -> None:
    """Create a private installation root or require the existing root to be private."""
    folder = installation_root(home)
    folder.mkdir(mode=0o700, exist_ok=True)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise OSError(f"Arbol's installation directory must be owner-only: {folder}")
