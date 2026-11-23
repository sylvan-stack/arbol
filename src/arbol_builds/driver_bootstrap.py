"""Source generation for the isolated, sealed Driver provider entry (DRV-6.21).

Generation/compilation are static operations. No packaged interpreter, Driver,
registry, state or qualification command is run to produce this prefix.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .driver_admission import COMPONENTS, Refusal

_INITIAL = '''import sys
import _frozen_importlib
if _frozen_importlib.FrozenImporter.find_spec("os") is None:
    sys.stdout.write('{"error":{"code":"launch_failed","message":"Isolated provider bootstrap unavailable."}}\\n')
    raise SystemExit(1)
import os

def __arbol_initial(root):
    def stop():
        sys.stdout.write('{"error":{"code":"launch_failed","message":"Isolated provider bootstrap refused."}}\\n')
        raise SystemExit(1)
    if (getattr(os.__spec__, "origin", None) != "frozen"
            or getattr(os.path.__spec__, "origin", None) != "frozen"
            or not sys.flags.isolated or not sys.flags.no_site
            or not sys.flags.no_user_site or not sys.dont_write_bytecode
            or not sys.flags.safe_path):
        stop()
    root = os.path.abspath(root)
    if os.path.realpath(root, strict=True) != root:
        stop()
    def inside(value):
        if not isinstance(value, str) or not value or not os.path.isabs(value):
            return False
        resolved = os.path.realpath(value)
        return resolved == root or resolved.startswith(root + os.sep)
    if (not inside(sys.executable) or not inside(sys.prefix) or not inside(sys.base_prefix)
            or not inside(sys.exec_prefix) or not inside(sys.base_exec_prefix)
            or not sys.path or not all(inside(item) for item in sys.path)):
        stop()
    expected = root + "/runtime/python/bin/python3.14"
    if os.path.realpath(sys.executable, strict=True) != os.path.realpath(expected, strict=True):
        stop()
    info = os.lstat(root)
    if info.st_uid != os.getuid() or info.st_mode & 0o7777 != 0o700:
        stop()
    # Check every potential import file/link using only frozen os before the
    # bundled standard library is imported to hash/parse M/D. An external nested
    # stdlib symlink must not execute even once before the later M refusal.
    count = 0
    def walk_error(error):
        stop()
    for folder, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in directories + files:
            count += 1
            if count > 100002:
                stop()
            path = os.path.join(folder, name)
            item = os.lstat(path)
            if item.st_uid != os.getuid():
                stop()
            kind = item.st_mode & 0o170000
            if kind == 0o120000:
                if os.path.isabs(os.readlink(path)) or not inside(os.path.realpath(path, strict=True)):
                    stop()
            elif kind not in (0o100000, 0o040000):
                stop()
    return root
'''


def _standalone(path: Path) -> str:
    """Embed the verifier without importing application code before M verifies."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    for node in reversed(ast.parse(source).body):
        if isinstance(node, ast.ImportFrom) and (
            node.level or node.module in ("__future__", "arbol_installation.paths")
        ):
            assert node.end_lineno is not None
            del lines[node.lineno - 1:node.end_lineno]
    return "".join(lines)


def render_prefix(*, component: str, root: Path | None = None, build: str | None = None) -> str:
    """A fixed launcher root or the physical sealed script's own immutable root.

    The inherited initial path may contain CPython's conventional nonexistent
    zip path, but every initial location must still resolve inside the payload.
    D.importRoots subsequently contains only existing inventoried locations.
    """
    if component not in (*COMPONENTS, "arbol"):
        raise Refusal("Unknown provider bootstrap component.")
    package = Path(__file__).resolve().parent
    expression = (repr(str(root)) if root is not None else
                  'os.path.dirname(os.path.dirname(os.path.realpath(__file__, strict=True)))')
    expected_build = repr(build) if build is not None else 'os.path.basename(os.path.dirname(__arbol_root))'
    # Only confined bundled standard-library imports occur in these embedded
    # definitions. No relative application import is executed while verifying M.
    body = "\n".join(_standalone(package / name) for name in ("driver_admission.py", "driver_payload.py"))
    ending = f'''
__arbol_payload = load(Path(__arbol_root), {component!r}, {expected_build})
if os.path.realpath(sys.executable, strict=True) != str(
        contained(__arbol_payload.root, __arbol_payload.descriptor["interpreter"], regular=True)):
    refuse()
sys.path[:] = [str(contained(__arbol_payload.root, item))
               for item in __arbol_payload.descriptor["importRoots"]]
__arbol_sealed_payload__ = __arbol_payload.descriptor
'''
    work = f'__arbol_root = __arbol_initial({expression})\n' + body + ending
    protected = "\n".join("    " + line if line else "" for line in work.splitlines())
    return ('from __future__ import annotations\n' + _INITIAL + "\ntry:\n" + protected +
            "\nexcept Exception:\n"
            "    sys.stdout.write('{\"error\":{\"code\":\"launch_failed\","
            "\"message\":\"Isolated provider bootstrap refused.\"}}\\n')\n"
            "    raise SystemExit(1)\n")


def render_provider_entry() -> bytes:
    """Seal the tracked entry body only after all provider source is available."""
    entry = Path(__file__).resolve().parents[2] / "bin" / "driver_state_entry.py"
    return (render_prefix(component="arbol") + "\n" + entry.read_text(encoding="utf-8")).encode("utf-8")
