"""Start arbol-roots from this checkout, using the same development Python as arbol-builds."""

import signal
import sys
from pathlib import Path

if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
if isinstance(getattr(sys, "last_exc", None), KeyboardInterrupt):
    signal.raise_signal(signal.SIGINT)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from arbol_roots.cli import entry  # noqa: E402

entry()
