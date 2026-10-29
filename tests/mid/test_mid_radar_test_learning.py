"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import radar.test_learning as _support
from radar.test_learning import (
    Any,
    CLAUDE,
    CODEX,
    ChatRecords,
    FIRST_PROFILE,
    KIMI,
    LEARNING,
    Learning,
    Listed,
    Listing,
    MONDAY,
    Observation,
    Path,
    ProfileRecords,
    RATIOS,
    ROOT,
    RecordFixture,
    Refused,
    Report,
    Series,
    Subscription,
    TheCommands,
    TheEstimate,
    ThePairs,
    TheProfiles,
    TheRuns,
    Weight,
    at,
    claude_report,
    claude_windows,
    codex,
    datetime,
    estimate,
    json,
    kimi,
    learn,
    observation,
    observations,
    observe,
    one,
    pairs,
    recompute,
    record,
    report,
    runs_between,
    sys,
    timedelta,
    unittest,
    usage,
    uuid,
    window,
)


class TheProfiles(_support.TheProfiles):


# TEST-TIER-BEGIN tests/radar/test_learning.py::TheProfiles.test_a_calculation_uses_the_profile_in_use_and_never_a_proposed_one
    async def test_a_calculation_uses_the_profile_in_use_and_never_a_proposed_one(self) -> None:
        """radar.learn-never-proposed"""
        await self.history(RATIOS)
        now = MONDAY + timedelta(days=11)
        proposed = (await learn(self.records, now)).proposed
        assert proposed is not None
        self.assertEqual(await self.records.in_use(), FIRST_PROFILE)
        tick = await recompute(self.records, self.listing(), FIRST_PROFILE, now)
        self.assertEqual([result.profile for result in tick.results], [1])
        with self.assertRaises(Refused) as caught:
            await self.records.calculate(CLAUDE, proposed, now)
        self.assertEqual(caught.exception.code, "profile_not_approved")
        approved = await self.records.approve(2, now)
        self.assertEqual((approved.version, approved.approval), (2, "approved"))
        self.assertEqual(await self.records.in_use(), approved)
        later = await recompute(self.records, self.listing(), FIRST_PROFILE, now + timedelta(minutes=3))
        (result,) = later.results
        self.assertEqual(result.profile, 2)
        five = next(entry for entry in result.windows if entry.label == "Five hours")
        self.assertAlmostEqual(five.weight or 0, 0.1)
        self.assertEqual(
            [row[0] for row in await self.db.execute("SELECT profile FROM vigor_results ORDER BY moment", [])], [1, 2]
        )
# TEST-TIER-END tests/radar/test_learning.py::TheProfiles.test_a_calculation_uses_the_profile_in_use_and_never_a_proposed_one
