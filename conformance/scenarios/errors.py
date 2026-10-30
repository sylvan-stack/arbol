# Compatibility entry: the mid-tier implementation lives in tests/mid/archived/conformance/scenarios/errors.py.
# Keep the original module/package and __file__ so existing fixtures resolve unchanged.
from pathlib import Path as _TierPath
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from mid.archived.conformance.scenarios.errors import c26 as c26
    from mid.archived.conformance.scenarios.errors import c27 as c27
    from mid.archived.conformance.scenarios.errors import c28 as c28
    from mid.archived.conformance.scenarios.errors import c29 as c29
    from mid.archived.conformance.scenarios.errors import c30 as c30
    from mid.archived.conformance.scenarios.errors import prop as prop
    from mid.archived.conformance.scenarios.errors import same as same
    from mid.archived.conformance.scenarios.errors import to_string as to_string
else:
    _tier_source = _TierPath(__file__).resolve().parents[2] / 'tests/mid/archived/conformance/scenarios/errors.py'
    exec(compile(_tier_source.read_bytes(), str(_tier_source), "exec"), globals())
