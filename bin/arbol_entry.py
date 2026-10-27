"""Development and packaged entry for arbol backend."""

import sys
from pathlib import Path

package = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(package / "src"))
sys.path.insert(0, str(package / "runtime/site-packages"))
from arbol_backend.cli import entry  # noqa: E402

entry(package)
