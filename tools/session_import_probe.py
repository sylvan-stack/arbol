"""SIM-10 native reader probe. Run under the separately verified OS write-denial profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from arbol_import.readers.form import TOOLS, Failed, HomeFile, Reader, Source, Tool, reader_module
from arbol_import.readers.pi import _eligible_path as pi_eligible

MAX_FILES = 150_000
MAX_BYTES = 64 * 1024**3
ROLLOUT = re.compile(r"(?:sessions/[0-9]{4}/[0-9]{2}/[0-9]{2}|archived_sessions)/rollout-[^/]+\.jsonl(?:\.zst)?")
KIMI_ARCHIVE = {"blobs", "tool-results", "file-history", "tasks", "plans", "media", "media-originals"}
KIMI_EXCLUDED = {"logs", "credentials", "oauth", "server.token", "device_id", "server", "search-index",
                 "cache", "image-upload-cache"}
WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
MUTATIONS = {"os.remove": 1, "os.rename": 2, "os.mkdir": 1, "os.rmdir": 1, "os.link": 2,
             "os.symlink": 2, "os.chmod": 1, "os.chown": 1, "os.utime": 1, "os.truncate": 1}
CODEX_SHARED = {"state_5.sqlite", "state_5.sqlite-wal", "state_5.sqlite-shm", "session_index.jsonl"}
MIMO_SHARED = {"mimocode.db", "mimocode.db-wal", "mimocode.db-shm"}
type Stamp = tuple[int, int, int, int, int]
type Fingerprint = tuple[Stamp, str]


def stamp(info: os.stat_result) -> Stamp:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def fingerprint(root: Path, path: Path, budget: int) -> Fingerprint | None:
    # The caller has checked eligibility for the physical path. A later symlink
    # substitution still cannot redirect this read outside the pinned tree.
    parts = path.relative_to(root).parts
    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as close:
        fd = os.open(root, directory)
        close.callback(os.close, fd)
        for part in parts[:-1]:
            fd = os.open(part, directory, dir_fd=fd)
            close.callback(os.close, fd)
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(leaf, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                return None
            if before.st_size > budget:
                raise OverflowError
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = stream.read(min(remaining, 1 << 20))
                if not chunk:
                    raise InterruptedError
                digest.update(chunk)
                remaining -= len(chunk)
            checksum = digest.hexdigest()
            after = os.fstat(stream.fileno())
            named = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if stamp(before) != stamp(after) or stamp(before) != stamp(named):
                raise InterruptedError
            return stamp(before), checksum


def as_path(value: object) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    return Path(os.path.abspath(os.fsdecode(value)))


class Ledger:
    def __init__(self, tool: Tool, home: Path, driver: Path | None) -> None:
        self.tool, self.home, self.driver = tool, home, driver
        self.roots = (home, driver) if driver is not None else (home,)
        self.paths: dict[Path, Path] = {}
        self.saved: dict[Path, Fingerprint] = {}
        self.issues: Counter[str] = Counter()
        self.process_lookups = 0
        self.active = False
        self.busy = False
        self.bytes = 0
        self.scratch: Path | None = None

    def eligible(self, path: Path, *, dynamic: bool) -> bool:
        if self.driver is not None and path.is_relative_to(self.driver):
            parts = path.relative_to(self.driver).parts
            return len(parts) == 4 and parts[0] == 'subscriptions' and parts[2] == 'chats' and path.suffix == '.json'
        if not path.is_relative_to(self.home):
            return False
        relative = path.relative_to(self.home)
        parts = relative.parts
        if not parts:
            return False
        root, leaf = parts[0], parts[-1]
        match self.tool:
            case 'claude-code':
                if root == 'projects':
                    return len(parts) >= 4 or (len(parts) == 3 and path.suffix == '.jsonl')
                return dynamic and root == 'file-history' and len(parts) > 2
            case 'codex':
                return (len(parts) == 1 and leaf in CODEX_SHARED) or bool(ROLLOUT.fullmatch(relative.as_posix()))
            case 'kimi-code':
                if set(parts) & KIMI_EXCLUDED or leaf.startswith('config.toml') or leaf.endswith(('.wal', '.index', '.postings')):
                    return False
                if root == 'files':
                    return dynamic and len(parts) > 1
                if root == 'locks':
                    return len(parts) == 3 and parts[1] == 'sessions'
                return root == 'sessions' and len(parts) >= 4 and parts[2].startswith('session_') and (
                    (len(parts) == 4 and leaf == 'state.json') or
                    (len(parts) == 6 and parts[3] == 'agents' and leaf == 'wire.jsonl') or
                    (len(parts) > 4 and parts[3] in KIMI_ARCHIVE)
                )
            case 'pi':
                return pi_eligible(relative) and (dynamic or (root == 'sessions' and len(parts) == 3
                                                               and path.suffix == '.jsonl'))
            case 'mimo':
                return (len(parts) == 1 and leaf in MIMO_SHARED) or (
                    len(parts) == 3 and parts[:2] == ('storage', 'session_diff') and path.suffix == '.json')

    def inventory(self) -> set[Path]:
        prefixes = {
            'claude-code': ['projects'],
            'codex': ['sessions', 'archived_sessions', *sorted(CODEX_SHARED)],
            'kimi-code': ['sessions', 'locks/sessions'],
            'pi': ['sessions'],
            'mimo': [*sorted(MIMO_SHARED), 'storage/session_diff'],
        }[self.tool]
        starts = [self.home / prefix for prefix in prefixes]
        if self.driver is not None:
            starts.extend((self.driver / 'subscriptions').glob('*/chats'))
        found: set[Path] = set()
        for start in starts:
            if start.is_symlink() or not any(start.resolve().is_relative_to(root) for root in self.roots):
                self.issues['aliased_inventory_root'] += 1
                continue
            if not start.is_dir():
                if self.eligible(start, dynamic=False) and os.path.lexists(start):
                    found.add(start)
                continue
            for base, dirs, names in os.walk(start, onerror=lambda _: self.issues.update(['inventory_unreadable'])):
                if self.tool == 'kimi-code':
                    dirs[:] = [name for name in dirs if name not in KIMI_EXCLUDED]
                found.update(path for name in names if self.eligible(path := Path(base) / name, dynamic=False))
                if len(found) > MAX_FILES:
                    self.issues['scan_limit'] += 1
                    return set()
        return found

    def capture(self, path: Path) -> None:
        if self.busy or path in self.paths or not self.eligible(path, dynamic=True):
            return
        self.busy = True
        try:
            physical = path.resolve(strict=True)
            root = next((r for r in self.roots if path.is_relative_to(r) and physical.is_relative_to(r)), None)
            if root is None or not self.eligible(physical, dynamic=True):
                self.issues['excluded_alias'] += 1
                return
            if physical not in self.saved:
                if len(self.saved) >= MAX_FILES:
                    raise OverflowError
                if not stat.S_ISREG(physical.lstat().st_mode):
                    return
                result = fingerprint(root, physical, MAX_BYTES - self.bytes)
                if result is None:
                    return
                self.saved[physical] = result
                self.bytes += result[0][2]
            self.paths[path] = physical
        except (FileNotFoundError, NotADirectoryError):
            if os.path.lexists(path):
                self.issues['unreadable_input'] += 1
        except InterruptedError:
            self.issues['unstable_read'] += 1
        except OverflowError:
            self.issues['scan_limit'] += 1
        except (OSError, RuntimeError, ValueError):
            self.issues['unreadable_input'] += 1
        finally:
            self.busy = False

    def protected(self, value: object) -> bool:
        path = as_path(value)
        return path is not None and any(path.is_relative_to(root) or path.resolve().is_relative_to(root)
                                        for root in self.roots)

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if not self.active or self.busy:
            return
        if event == 'open':
            value, _, flags = args
            violation = bool(flags & WRITE) and self.protected(value)
            if not violation and (path := as_path(value)):
                self.capture(path)
        elif event in MUTATIONS:
            violation = any(self.protected(value) for value in args[:MUTATIONS[event]])
        elif event == 'sqlite3.connect':
            value = args[0]
            if isinstance(value, str) and value.startswith('file:'):
                value = unquote(urlsplit(value).path)
            database = as_path(value)
            violation = database is None or self.scratch is None or not database.resolve().is_relative_to(self.scratch)
        elif event == 'subprocess.Popen' and self.tool == 'kimi-code' and args[0] == '/bin/ps':
            self.process_lookups += 1
            return
        else:
            return
        if violation:
            self.issues['write_violation'] += 1
            raise PermissionError('Native stores are read-only during qualification.')

    @contextmanager
    def watch(self) -> Iterator[None]:
        real_stat = Path.stat

        def observe(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            self.capture(path.absolute())
            return real_stat(path, follow_symlinks=follow_symlinks)

        sys.addaudithook(self.audit)
        with patch.object(Path, 'stat', observe):
            self.active = True
            try:
                yield
            finally:
                self.active = False

    def compare(self, initial: set[Path]) -> None:
        self.issues['inventory_changes'] += len(initial.symmetric_difference(self.inventory()))
        remaining = MAX_BYTES
        for path, expected in self.saved.items():
            root = next(r for r in self.roots if path.is_relative_to(r))
            try:
                actual = fingerprint(root, path, remaining)
                self.issues['file_changes'] += actual != expected
                if actual is not None:
                    remaining -= actual[0][2]
            except (FileNotFoundError, NotADirectoryError, InterruptedError):
                self.issues['file_changes'] += 1
            except OverflowError:
                self.issues['scan_limit'] += 1
            except (OSError, RuntimeError, ValueError):
                self.issues['unreadable_input'] += 1
        for named, physical in self.paths.items():
            try:
                self.issues['file_changes'] += named.resolve(strict=True) != physical
            except FileNotFoundError:
                self.issues['file_changes'] += 1
            except (OSError, RuntimeError, ValueError):
                self.issues['unreadable_input'] += 1


def run(tool: Tool, home: Path, driver: Path | None, work: Path) -> dict[str, object]:
    ledger = Ledger(tool, home, driver)
    initial = ledger.inventory()
    for path in sorted(initial):
        ledger.capture(path)
    counts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    module = cast(Reader, import_module(reader_module(tool)))
    with tempfile.TemporaryDirectory(dir=work, prefix='reader-') as scratch:
        private = Path(scratch)
        ledger.scratch = private
        try:
            with ledger.watch():
                for result in module.read(Source(home, driver, private, datetime.now(UTC))):
                    if isinstance(result, Failed):
                        failures[result.code] += 1
                        counts['known_failures' if result.native_id is not None else 'anonymous_failures'] += 1
                        if result.native_id is not None and result.kind is None:
                            ledger.issues['known_failure_without_kind'] += 1
                        continue
                    counts['chat_sessions'] += 1
                    kinds[result.kind] += 1
                    counts['turns'] += len(result.turns)
                    counts['subagents'] += sum(len(turn.subagents) for turn in result.turns)
                    counts['live'] += result.live
                    counts['outside_archive_references'] += result.files_not_archived
                    for file in result.archive_files:
                        if isinstance(file, HomeFile) and home / file.path not in ledger.paths:
                            ledger.issues['unobserved_archive_file'] += 1
        except Exception:
            ledger.issues['reader_exception'] += 1
        if any(private.iterdir()):
            ledger.issues['residual_scratch'] += 1
    ledger.compare(initial)
    issues = +ledger.issues
    changes = {'unstable_read', 'file_changes', 'inventory_changes'}
    if issues['write_violation']:
        status = 'write_violation'
    elif issues.keys() - changes - {'excluded_alias'}:
        status = 'inconclusive'
    elif changes & issues.keys():
        status = 'changed'
    else:
        status = 'unchanged'
    if tool == 'kimi-code':
        counts['process_lookups'] = ledger.process_lookups
    return {'tool': tool, 'status': status, 'counts': counts, 'kinds': kinds, 'failure_codes': failures,
            'observed_files': len(ledger.saved), 'issues': issues}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', choices=TOOLS)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--driver-state', type=Path)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    try:
        home = args.home.resolve(strict=True)
        driver = args.driver_state.resolve(strict=True) if args.driver_state else None
        roots = (home, driver) if driver is not None else (home,)
        if not all(root.is_dir() for root in roots):
            raise FileNotFoundError
        work = args.work.resolve(strict=True)
        info = work.stat()
        if (work != args.work.absolute() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
                or any(work.is_relative_to(root) or root.is_relative_to(work) for root in roots)):
            raise ValueError('Use separate owner-only work.')
        report = run(args.tool, home, driver, work)
    except FileNotFoundError:
        report = {'tool': args.tool, 'status': 'unavailable'}
    except Exception:
        report = {'tool': args.tool, 'status': 'inconclusive', 'issues': {'probe_error': 1}}
    print(json.dumps(report, sort_keys=True))
    return int(report['status'] not in ('unchanged', 'changed'))


if __name__ == '__main__':
    raise SystemExit(main())
