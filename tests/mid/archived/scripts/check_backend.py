# Mid-tier source from scripts/check_backend.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

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

# TEST-TIER-IMPORTS-BEGIN scripts/check_backend.py:3
# import subprocess
# TEST-TIER-IMPORTS-END scripts/check_backend.py:3

# TEST-TIER-IMPORTS-BEGIN scripts/check_backend.py:9
# from backend_package import verify  # noqa: E402
# TEST-TIER-IMPORTS-END scripts/check_backend.py:9

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
