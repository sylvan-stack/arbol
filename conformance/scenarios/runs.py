# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/conformance/scenarios/runs.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from mid.archived.conformance.scenarios.runs import c18 as c18
    from mid.archived.conformance.scenarios.runs import c33 as c33
    from mid.archived.conformance.scenarios.runs import events as events
    from mid.archived.conformance.scenarios.runs import signed as signed
    from mid.archived.conformance.scenarios.runs import stream as stream
else:
    _tier_source = _TierPath(__file__).resolve().parents[2] / 'tests/mid/archived/conformance/scenarios/runs.py'
    exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
