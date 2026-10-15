"""arbol-conformance: the shared Driver conformance suite (DRV-5). Started with Python 3.14 as
`python3.14 -I conformance/bin/arbol-conformance.py --driver <command> [--only <scenario ids>]`."""

# First: a Ctrl-C while Python starts ends the suite quietly, also one Python's start-up caught.
import signal
import sys

if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
if isinstance(getattr(sys, "last_exc", None), KeyboardInterrupt):
    signal.raise_signal(signal.SIGINT)

from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conformance.cli import entry  # noqa: E402

entry()
