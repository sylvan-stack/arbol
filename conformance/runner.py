# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/conformance/runner.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from mid.archived.conformance.runner import run_suite as run_suite
    from mid.archived.conformance.runner import scenarios as scenarios
    from mid.archived.conformance.runner import select_scenarios as select_scenarios
else:
    _tier_source = _TierPath(__file__).resolve().parents[1] / 'tests/mid/archived/conformance/runner.py'
    exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
