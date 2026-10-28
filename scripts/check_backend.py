"""Check this immutable Arbol image on its own Python and private PostgreSQL."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# TEST-TIER-DISABLED-BEGIN scripts/check_backend.py::main
# def main() -> int:
#     try:
#         verify(ROOT)
#         child = subprocess.run(
#             [str(ROOT / "runtime/python/bin/python3.14"), "-I", "-B", "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-p", "test*.py", "-v"],
#             cwd=ROOT,
#             check=False,
#         )
#         if child.returncode:
#             return 1
#         verify(ROOT)
#     except (OSError, ValueError, KeyError) as error:
#         print("Backend unit check failed: " + str(error), file=sys.stderr)
#         return 1
#     return 0
# TEST-TIER-DISABLED-END scripts/check_backend.py::main
def main() -> int:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


if __name__ == "__main__":
    raise SystemExit(main())

# Archived complete imports; restore needed names in their original scope, not at this file tail.
# TEST-TIER-IMPORTS-BEGIN scripts/check_backend.py:3
# import subprocess
# TEST-TIER-IMPORTS-END scripts/check_backend.py:3
# TEST-TIER-IMPORTS-BEGIN scripts/check_backend.py:9
# from backend_package import verify  # noqa: E402
# TEST-TIER-IMPORTS-END scripts/check_backend.py:9
