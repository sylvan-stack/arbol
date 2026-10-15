"""Start arbol-builds from this checkout, for development and the checks: `bin/arbol-builds`."""

# First, as in the installed program: a Ctrl-C ends the tool quietly, also one Python's start-up caught.
import signal
import sys

if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
if isinstance(getattr(sys, "last_exc", None), KeyboardInterrupt):
    signal.raise_signal(signal.SIGINT)

from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from arbol_builds.cli import entry  # noqa: E402

entry()
