"""Start arbol-builds from this checkout, for development and the checks: `bin/arbol-builds`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from arbol_builds.cli import entry  # noqa: E402

entry()
