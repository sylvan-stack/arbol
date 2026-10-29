# Test implementations moved to tests/mid/archived/scripts/check_backend.py.
"""Check this immutable Arbol image on its own Python and private PostgreSQL."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')  # TEST-TIER-REFUSAL


if __name__ == "__main__":
    raise SystemExit(main())

# Archived complete imports; restore needed names in their original scope, not at this file tail.
