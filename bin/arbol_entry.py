"""Development and packaged entry for arbol backend."""

import os
import sys
from pathlib import Path

package = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(package / "src"))
sys.path.insert(0, str(package / "runtime/site-packages"))
from arbol_installation.paths import EXCHANGE_RUNTIME_COMMAND  # noqa: E402

if sys.argv[1:2] == [EXCHANGE_RUNTIME_COMMAND]:
    from arbol_backend.exchange_cli import main

    for key in tuple(os.environ):
        if key.startswith("PG"):
            del os.environ[key]
    reply = main(sys.argv[2:], package)
    sys.stdout.buffer.write(reply.raw)
    raise SystemExit(reply.status)

from arbol_backend.cli import entry  # noqa: E402

entry(package)
