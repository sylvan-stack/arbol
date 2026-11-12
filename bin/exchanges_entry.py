"""Development and packaged entry for the installation Exchange commands."""

import os
import sys
from pathlib import Path

package = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(package / "src"))
sys.path.insert(0, str(package / "runtime/site-packages"))
from arbol_backend.exchange_cli import entry  # noqa: E402

for key in tuple(os.environ):
    if key.startswith("PG"):
        del os.environ[key]

entry(package)
