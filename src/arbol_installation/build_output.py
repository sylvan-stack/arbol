"""Release completed build and test output for local cleanup."""

from __future__ import annotations

import os
import plistlib
import subprocess
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from unicodedata import normalize
from uuid import uuid4

QUEUE = ".arbol-released"


@contextmanager
def directory(path: str | Path, parent: int | None = None, *, private: bool = False) -> Iterator[int]:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & (0o077 if private else 0o022):
            raise ValueError(f"Build output directory is not protected from other users: {path}")
        yield fd
    finally:
        os.close(fd)


def attached_paths() -> set[Path]:
    """Read both backing files and mount points from the system attachment inventory."""
    try:
        output = subprocess.check_output(["/usr/bin/hdiutil", "info", "-plist"], stdin=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, timeout=10)
        images = plistlib.loads(output)["images"]
        if not isinstance(images, list):
            raise ValueError("Expected a disk image list.")
        paths: set[Path] = set()
        for image in images:
            paths.add(Path(image["image-path"]).resolve())
            entities = image["system-entities"]
            if not isinstance(entities, list):
                raise ValueError("Expected disk image mount information.")
            for entity in entities:
                if not isinstance(entity, dict):
                    raise ValueError("Expected a disk image device record.")
                if "mount-point" in entity:
                    paths.add(Path(entity["mount-point"]).resolve())
        return paths
    except (KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError("Cannot verify the attached disk images.") from error


def contains_path(directory: Path, paths: set[Path]) -> bool:
    # The same macOS file can be named with a different case or Unicode representation.
    prefix = Path(normalize("NFC", str(directory)).casefold())
    return any(Path(normalize("NFC", str(path)).casefold()).is_relative_to(prefix) for path in paths)


def release_run(home: Path, run: Path, evidence: Path) -> Path:
    """Hand off one run after its runner has stopped using the directory."""
    root = home.resolve() / "Builds"
    run = run.expanduser().absolute()
    parts = run.relative_to(root).parts
    if (len(parts) not in (2, 3) or (parts[0].casefold() == "sylvan-stack" and len(parts) != 3)
            or any(part.startswith(".") for part in parts)):
        raise ValueError("Expected one run under ~/Builds/<repository> or ~/Builds/<org>/<repository>.")
    report = evidence.expanduser().resolve(strict=True)
    if not report.is_file() or contains_path(root, {report}):
        raise ValueError("Save the run's evidence in a regular file outside ~/Builds before release.")
    with ExitStack() as stack:
        root_fd = stack.enter_context(directory(root))
        parent_fd = root_fd
        for part in parts[:-1]:
            parent_fd = stack.enter_context(directory(part, parent_fd))
        run_fd = stack.enter_context(directory(parts[-1], parent_fd))
        run_info = os.fstat(run_fd)
        device = os.fstat(root_fd).st_dev
        if run_info.st_dev != device:
            raise ValueError("The run must be on the same filesystem as ~/Builds.")
        if contains_path(run, attached_paths()):
            raise ValueError("The run has an attached disk image. Release it after the image is detached.")
        with suppress(FileExistsError):
            os.mkdir(QUEUE, mode=0o700, dir_fd=root_fd)
        queue_fd = stack.enter_context(directory(QUEUE, root_fd, private=True))
        if os.fstat(queue_fd).st_dev != device:
            raise ValueError("The build output queue must be on the same filesystem as ~/Builds.")
        current = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (run_info.st_dev, run_info.st_ino):
            raise ValueError("The run directory changed while preparing its release.")
        name = uuid4().hex
        os.rename(parts[-1], name, src_dir_fd=parent_fd, dst_dir_fd=queue_fd)
    return root / QUEUE / name
