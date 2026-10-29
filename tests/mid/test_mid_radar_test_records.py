"""Mid-tier selections. Write or run only in an explicitly requested testing task."""
from __future__ import annotations

import radar.test_records as _support
from radar.test_records import (
    Any,
    CLAUDE,
    CODEX,
    FETCHED,
    FIRST_PROFILE,
    KIMI,
    LAYOUT,
    LIST,
    LISTING,
    LayoutCopy,
    Listed,
    Listing,
    MERGED,
    MONDAY,
    Path,
    Profile,
    Programs,
    ROOT,
    RecordFixture,
    Refused,
    Rejected,
    TABLES,
    TheDrivers,
    TheRecords,
    TheReplay,
    Weight,
    ZAI,
    at,
    claude,
    codex,
    drivers_of,
    json,
    kimi,
    list_subscriptions,
    loss_row,
    record,
    records_of,
    sys,
    timedelta,
    unittest,
    usage,
    window,
)


class TheRecords(_support.TheRecords):


# TEST-TIER-BEGIN tests/radar/test_records.py::TheRecords.test_no_secret_reaches_a_row
    async def test_no_secret_reaches_a_row(self) -> None:
        """radar.record-no-secret"""
        listed = record(
            CLAUDE,
            usage(claude(), extra={"isUsingOverage": False}),
            account={"email": "owner@example.test", "plan": "max"},
            settings={"apiKeyItem": "SECRET-keychain-item"},
            problem={"code": "token", "message": "SECRET-token-text"},
        )
        self.frame.behavior = {"arbol-claude-driver": {"output": [listed]}}
        self.frame.configure()
        listing = await list_subscriptions(Programs(self.selected))
        item = listing.subscriptions[0]
        assert item.last_usage is not None
        await self.records.record_report(item.subscription, item.last_usage, now=MONDAY)
        await self.records.calculate(item.subscription, FIRST_PROFILE, MONDAY)
        dump = json.dumps([await self.rows(table) for table in TABLES], default=str)
        for word in ("SECRET", "apiKeyItem", "owner@example.test", "problem", "account"):
            self.assertNotIn(word, dump)
# TEST-TIER-END tests/radar/test_records.py::TheRecords.test_no_secret_reaches_a_row
