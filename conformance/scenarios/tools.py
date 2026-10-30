# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/conformance/scenarios/tools.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from mid.archived.conformance.scenarios.tools import c36 as c36
    from mid.archived.conformance.scenarios.tools import c37 as c37
else:
    _tier_source = _TierPath(__file__).resolve().parents[2] / 'tests/mid/archived/conformance/scenarios/tools.py'
    exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
