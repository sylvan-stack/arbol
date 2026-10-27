"""Check this immutable Arbol image on its own Python and private PostgreSQL."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from backend_package import verify  # noqa: E402


def main() -> int:
    try:
        verify(ROOT)
        child = subprocess.run(
            [str(ROOT / "runtime/python/bin/python3.14"), "-I", "-B", str(ROOT / "tests/test_backend.py"), "-v"],
            cwd=ROOT,
            check=False,
        )
        if child.returncode:
            return 1
        verify(ROOT)
    except (OSError, ValueError, KeyError) as error:
        print("Backend unit check failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
