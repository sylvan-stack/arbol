# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/conformance/scenarios/stops.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from mid.archived.conformance.scenarios.stops import c15 as c15
    from mid.archived.conformance.scenarios.stops import c17 as c17
    from mid.archived.conformance.scenarios.stops import c38 as c38
    from mid.archived.conformance.scenarios.stops import gone as gone
    from mid.archived.conformance.scenarios.stops import input_ as input_
    from mid.archived.conformance.scenarios.stops import method_find as method_find
    from mid.archived.conformance.scenarios.stops import prop as prop
    from mid.archived.conformance.scenarios.stops import some_line as some_line
    from mid.archived.conformance.scenarios.stops import sorted_readdir as sorted_readdir
    from mid.archived.conformance.scenarios.stops import strictly_equal as strictly_equal
    from mid.archived.conformance.scenarios.stops import wait_for as wait_for
else:
    _tier_source = _TierPath(__file__).resolve().parents[2] / 'tests/mid/archived/conformance/scenarios/stops.py'
    exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
