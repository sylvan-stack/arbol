# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/conformance/scenarios/subscriptions.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from mid.archived.conformance.scenarios.subscriptions import c2 as c2
    from mid.archived.conformance.scenarios.subscriptions import c4 as c4
    from mid.archived.conformance.scenarios.subscriptions import c5 as c5
    from mid.archived.conformance.scenarios.subscriptions import c6 as c6
    from mid.archived.conformance.scenarios.subscriptions import c7 as c7
    from mid.archived.conformance.scenarios.subscriptions import check_resources as check_resources
else:
    _tier_source = _TierPath(__file__).resolve().parents[2] / 'tests/mid/archived/conformance/scenarios/subscriptions.py'
    exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
