# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/conformance/scenarios/c14.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from mid.archived.conformance.scenarios.c14 import c14 as c14
else:
    _tier_source = _TierPath(__file__).resolve().parents[2] / 'tests/mid/archived/conformance/scenarios/c14.py'
    exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
