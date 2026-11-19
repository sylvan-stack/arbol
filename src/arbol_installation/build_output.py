"""Release completed build and test output and sweep the private queue."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import plistlib
import re
import subprocess
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from unicodedata import normalize
from uuid import uuid4

from .admission import lock

QUEUE = ".arbol-released"
SWEEP_LOCK = ".sweep.lock"
SWEEP_INTERVAL = 25 * 60
RUN_ID = re.compile(r"[0-9a-f]{32}")
LOG = logging.getLogger(__name__)


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


async def remove_run(path: Path) -> None:
    # The filesystem limit is enforced during traversal, even for a late mount.
    process = await asyncio.create_subprocess_exec(
        "/bin/rm", "-rfx", "--", str(path),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if await asyncio.wait_for(process.wait(), timeout=60):
            raise OSError("The released run could not be fully removed.")
    except (TimeoutError, asyncio.CancelledError):
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise


async def sweep(home: Path) -> None:
    queue = home.resolve() / "Builds" / QUEUE
    with ExitStack() as stack:
        try:
            root_fd = stack.enter_context(directory(queue.parent))
            queue_fd = stack.enter_context(directory(QUEUE, root_fd, private=True))
        except FileNotFoundError:
            return
        device = os.fstat(root_fd).st_dev
        if os.fstat(queue_fd).st_dev != device:
            raise ValueError("The build output queue must be on the same filesystem as ~/Builds.")
        runs = [name for name in os.listdir(queue_fd) if RUN_ID.fullmatch(name)]
        if not runs:
            return
        with suppress(FileExistsError):
            os.close(os.open(SWEEP_LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=queue_fd))
        try:
            stack.enter_context(lock(queue_fd, SWEEP_LOCK, fcntl.LOCK_EX))
        except BlockingIOError:
            return  # Another backend is sweeping this installation's queue.
        for name in runs:
            path = queue / name
            try:
                with directory(name, queue_fd) as run_fd:
                    info = os.fstat(run_fd)
                    if info.st_dev != device or contains_path(path, await asyncio.to_thread(attached_paths)):
                        continue
                    if not os.path.samestat(info, path.lstat()):
                        continue
                    await remove_run(path)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as error:
                LOG.warning("Deferred cleanup of %s: %s", path, error)


async def sweep_periodically(home: Path) -> None:
    clock = asyncio.get_running_loop().time
    while True:
        next_sweep = clock() + SWEEP_INTERVAL
        try:
            await sweep(home)
        except (OSError, ValueError) as error:
            LOG.warning("Deferred build output cleanup: %s", error)
        await asyncio.sleep(max(0, next_sweep - clock()))
