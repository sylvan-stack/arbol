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


class LayoutCopy(_support.LayoutCopy):
# TEST-TIER-BEGIN tests/radar/test_records.py::LayoutCopy.test_the_copy_is_the_tail_of_both_root_layouts
    def test_the_copy_is_the_tail_of_both_root_layouts(self) -> None:
        """radar.layout-copy"""
        text = LAYOUT.read_text(encoding="utf-8")
        for table in TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", text)
            self.assertIn(f"COMMENT ON TABLE {table} IS", text)
        self.assertIn("not copied when the Root changes (SGM-D29)", text)
        layouts = {root: MERGED / "roots" / root / "layout.sql" for root in ("sapling", "jensen")}
        if not all(path.is_file() and "vigor_reports" in path.read_text(encoding="utf-8") for path in layouts.values()):
            self.skipTest("the merged Root layouts in readonly/arbol-root do not carry the Vigor tables yet")
        for root, path in layouts.items():
            with self.subTest(root=root):
                layout = path.read_text(encoding="utf-8")
                self.assertTrue(layout.endswith("\n" + text), f"the {root} layout does not end with the copy")
                self.assertLess(layout.index("exchange_notes"), layout.index("vigor_profiles"))
# TEST-TIER-END tests/radar/test_records.py::LayoutCopy.test_the_copy_is_the_tail_of_both_root_layouts



class TheDrivers(_support.TheDrivers):
# TEST-TIER-BEGIN tests/radar/test_records.py::TheDrivers.test_every_driver_among_the_launchers_lists_its_subscriptions_with_their_last_usage
    async def test_every_driver_among_the_launchers_lists_its_subscriptions_with_their_last_usage(self) -> None:
        """radar.drivers-list"""
        programs = self.listing(LISTING)
        self.assertEqual(drivers_of(programs), ("claude", "codex", "pi"))
        listing = await list_subscriptions(programs)
        self.assertEqual(listing.drivers, ("claude", "codex", "pi"))
        self.assertEqual(dict(listing.failures), {})
        self.assertEqual([item.subscription for item in listing.subscriptions], [CLAUDE, CODEX, KIMI, ZAI])
        by_id = {item.subscription.id: item for item in listing.subscriptions}
        self.assertEqual(by_id["anthropic"].last_usage, usage(claude(), extra={"isUsingOverage": False}))
        self.assertEqual(by_id["kimi-coding"].last_usage, usage(kimi()))
        self.assertIsNone(by_id["zai"].last_usage)  # no report yet
        self.assertEqual(by_id["zai"].record["state"], "signed_in")  # the record as delivered
        calls = self.frame.calls()
        self.assertEqual([call["program"] for call in calls], [f"arbol-{d}-driver" for d in ("claude", "codex", "pi")])
        self.assertTrue(all(call["args"] == LIST for call in calls))  # `list` and nothing else was run
        self.assertTrue(all(call["home"] == str(self.frame.home) and call["pgOverrides"] == [] for call in calls))
# TEST-TIER-END tests/radar/test_records.py::TheDrivers.test_every_driver_among_the_launchers_lists_its_subscriptions_with_their_last_usage

# TEST-TIER-BEGIN tests/radar/test_records.py::TheDrivers.test_a_failing_driver_is_reported_beside_the_others
    async def test_a_failing_driver_is_reported_beside_the_others(self) -> None:
        """radar.drivers-failure"""
        behavior = {
            **LISTING,
            "arbol-codex-driver": {"status": 1},  # the launcher ends without a reply
            "arbol-pi-driver": {"raw": "not json"},  # no JSON reply
        }
        listing = await list_subscriptions(self.listing(behavior))
        self.assertEqual([item.subscription for item in listing.subscriptions], [CLAUDE])
        self.assertEqual(set(listing.failures), {"codex", "pi"})
        self.assertTrue(listing.failures["codex"].startswith("no_answer: "))
        self.assertTrue(listing.failures["pi"].startswith("no_answer: "))
        shapes = {
            "arbol-claude-driver": {"output": {"id": "anthropic"}},  # not a list
            "arbol-codex-driver": {"output": [record(CODEX), {"family": "chatgpt"}]},  # a record without id
            "arbol-pi-driver": {"output": [{"id": "zai", "family": ""}]},  # an empty family
        }
        listing = await list_subscriptions(self.listing(shapes))
        self.assertEqual(listing.subscriptions, ())
        self.assertEqual(
            dict(listing.failures),
            dict.fromkeys(
                ("claude", "codex", "pi"),
                "invalid_reply: the Driver did not answer with a list of Subscription records",
            ),
        )
        self.assertEqual(len(self.frame.calls()), 6)
        self.assertIsNone(records_of("claude", "nonsense"))
        self.assertEqual(records_of("claude", []), [])
        self.assertEqual(records_of("pi", [record(ZAI)]), [Listed(ZAI, record(ZAI))])
# TEST-TIER-END tests/radar/test_records.py::TheDrivers.test_a_failing_driver_is_reported_beside_the_others

# TEST-TIER-BEGIN tests/radar/test_records.py::TheDrivers.test_only_drivers_with_a_launcher_are_asked
    async def test_only_drivers_with_a_launcher_are_asked(self) -> None:
        """radar.drivers-launchers"""
        (self.frame.bin / "arbol-pi-driver").unlink()
        (self.frame.bin / "arbol-other-driver.bak").write_text("#!/bin/sh\n")  # not a launcher's name
        programs = self.listing(LISTING)
        self.assertEqual(drivers_of(programs), ("claude", "codex"))
        listing = await list_subscriptions(programs)
        self.assertEqual(listing, Listing(("claude", "codex"), listing.subscriptions, {}))
        self.assertEqual([item.subscription for item in listing.subscriptions], [CLAUDE, CODEX])
        self.assertEqual(
            {call["program"] for call in self.frame.calls()}, {"arbol-claude-driver", "arbol-codex-driver"}
        )
# TEST-TIER-END tests/radar/test_records.py::TheDrivers.test_only_drivers_with_a_launcher_are_asked



class TheRecords(_support.TheRecords):
# TEST-TIER-BEGIN tests/radar/test_records.py::TheRecords.test_a_new_report_is_recorded_once_and_an_unchanged_one_not_again
    async def test_a_new_report_is_recorded_once_and_an_unchanged_one_not_again(self) -> None:
        """radar.record-report-once"""
        delivered = usage(claude(), extra={"isUsingOverage": False})
        first = await self.records.record_report(CLAUDE, delivered, now=MONDAY)
        assert first is not None
        self.assertEqual((first.subscription, first.outcome, first.arrived_at, first.run), (CLAUDE, "ok", MONDAY, None))
        self.assertIsNone(await self.records.record_report(CLAUDE, delivered, now=MONDAY + timedelta(minutes=5)))
        self.assertEqual(await self.count("vigor_reports"), 1)
        rows = await self.rows("vigor_reports")
        self.assertEqual(
            {
                key: rows[0][key]
                for key in ("id", "driver", "subscription", "family", "outcome", "windows", "extra", "run")
            },
            {
                "id": first.id,
                "driver": "claude",
                "subscription": "anthropic",
                "family": "anthropic",
                "outcome": "ok",
                "windows": claude(),
                "extra": {"isUsingOverage": False},
                "run": None,
            },
        )
        self.assertEqual(await self.records.last_report(CLAUDE), first)
        older = usage(claude(), fetched=at(minutes=-10))  # fetched before the recorded one
        self.assertIsNone(await self.records.record_report(CLAUDE, older, now=MONDAY + timedelta(minutes=6)))
        newer = usage(claude(12, 23), fetched=at(hours=2, minutes=30))
        second = await self.records.record_report(CLAUDE, newer, now=MONDAY + timedelta(hours=2, minutes=31))
        assert second is not None
        self.assertEqual(await self.records.last_report(CLAUDE), second)
        self.assertEqual(await self.records.reports(CLAUDE), [first, second])  # oldest first
        self.assertEqual(await self.count("vigor_reports"), 2)
        self.assertIsNone(await self.records.last_report(CODEX))  # another Subscription's reports are its own
        chatgpt = await self.records.record_report(CODEX, usage(codex()), now=MONDAY)
        self.assertEqual(await self.records.last_report(CODEX), chatgpt)
        self.assertEqual(await self.records.last_report(CLAUDE), second)
        with self.assertRaises(Rejected):  # what the Interface rejects writes nothing
            await self.records.record_report(KIMI, {"outcome": "ok", "fetchedAt": FETCHED, "windows": "x"}, now=MONDAY)
        self.assertEqual(await self.count("vigor_reports"), 3)
        unsupported = {"outcome": "unsupported", "fetchedAt": FETCHED, "message": "no reading for zai", "windows": []}
        zai = await self.records.record_report(ZAI, unsupported, now=MONDAY, run="50000000-0000-4000-8000-000000000001")
        assert zai is not None
        self.assertEqual((zai.message, zai.run), ("no reading for zai", "50000000-0000-4000-8000-000000000001"))
        self.assertEqual(await self.records.last_report(ZAI), zai)
# TEST-TIER-END tests/radar/test_records.py::TheRecords.test_a_new_report_is_recorded_once_and_an_unchanged_one_not_again

# TEST-TIER-BEGIN tests/radar/test_records.py::TheRecords.test_profile_1_is_written_when_the_table_has_no_profile
    async def test_profile_1_is_written_when_the_table_has_no_profile(self) -> None:
        """radar.record-profile"""
        self.assertIsNone(await self.records.profile(1))
        self.assertTrue(await self.records.ensure_profile(FIRST_PROFILE, MONDAY))
        self.assertFalse(await self.records.ensure_profile(FIRST_PROFILE, MONDAY + timedelta(hours=1)))
        rows = await self.rows("vigor_profiles")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {key: rows[0][key] for key in ("version", "approval", "pace", "placeholder", "gates", "stale_rule")},
            {
                "version": 1,
                "approval": "proposed",
                "pace": "even",
                "placeholder": 0.1,
                "gates": [],
                "stale_rule": "shortest-window",
            },
        )
        self.assertEqual(await self.records.profile(1), FIRST_PROFILE)
        await self.db.execute("TRUNCATE vigor_results, vigor_profiles")
        learned = Profile(
            1, "proposed", "even", Weight(0.1), gates={("anthropic", "Five hours"): Weight(0.12, "learned")}
        )
        self.assertTrue(await self.records.ensure_profile(learned, MONDAY))
        self.assertEqual(
            (await self.rows("vigor_profiles"))[0]["gates"],
            [
                {
                    "family": "anthropic",
                    "label": "Five hours",
                    "value": 0.12,
                    "source": "learned",
                    "pairs": None,
                    "low": None,
                    "high": None,
                    "estimator": "median",
                    "threshold": 2.0,
                    "needed": 10,
                }
            ],
        )
        self.assertEqual(await self.records.profile(1), learned)
# TEST-TIER-END tests/radar/test_records.py::TheRecords.test_profile_1_is_written_when_the_table_has_no_profile

# TEST-TIER-BEGIN tests/radar/test_records.py::TheRecords.test_a_calculation_is_recorded_with_its_inputs_and_read_back_as_it_was
    async def test_a_calculation_is_recorded_with_its_inputs_and_read_back_as_it_was(self) -> None:
        """radar.record-result"""
        report = await self.records.record_report(CLAUDE, usage(claude(), extra={"isUsingOverage": False}), now=MONDAY)
        assert report is not None
        result = await self.records.calculate(CLAUDE, FIRST_PROFILE, MONDAY)
        assert result.vigor is not None and result.next_value is not None
        self.assertEqual((round(result.vigor, 2), result.report, result.profile), (0.37, report.id, 1))
        self.assertEqual(await self.count("vigor_profiles"), 1)  # profile 1 written with the first calculation
        rows = await self.rows("vigor_results")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            {
                key: row[key]
                for key in ("driver", "subscription", "family", "report", "profile", "exhausted", "predicted")
            },
            {
                "driver": "claude",
                "subscription": "anthropic",
                "family": "anthropic",
                "report": report.id,
                "profile": 1,
                "exhausted": False,
                "predicted": False,
            },
        )
        self.assertEqual((row["vigor"], row["stale"], row["unknown"], row["notes"]), (result.vigor, None, None, []))
        self.assertEqual(row["next_value"], result.next_value)
        self.assertEqual(row["losses"], [loss_row(entry) for entry in result.windows])
        week = row["losses"][1]
        self.assertEqual(
            {key: week[key] for key in ("label", "role", "weight", "predicted", "usedPercent", "windowMinutes")},
            {
                "label": "Seven days",
                "role": "store",
                "weight": 1.0,
                "predicted": False,
                "usedPercent": 20.0,
                "windowMinutes": 10080.0,
            },
        )
        self.assertEqual(round(week["loss"], 2), 0.37)
        self.assertEqual(week["resetsAt"], (MONDAY + timedelta(days=3)).isoformat())
        self.assertEqual(await self.records.last_result(CLAUDE), result)  # read back as it was, field for field
        self.assertEqual(await self.records.results(CLAUDE), [result])
        later = await self.records.calculate(CLAUDE, FIRST_PROFILE, MONDAY + timedelta(hours=5))  # predicted and stale
        self.assertEqual((later.predicted, later.stale), (True, timedelta(hours=5, minutes=5)))
        self.assertEqual(await self.records.last_result(CLAUDE), later)
        self.assertEqual(await self.records.results(CLAUDE), [result, later])
        unknown = await self.records.calculate(ZAI, FIRST_PROFILE, MONDAY)  # no report yet
        self.assertEqual((unknown.vigor, unknown.unknown, unknown.report), (None, "no report yet", None))
        self.assertEqual(await self.records.last_result(ZAI), unknown)
        self.assertIsNone(await self.records.last_result(CODEX))
        reached = await self.records.record_report(
            KIMI, usage(kimi(five_reached=True), fetched=at(minutes=-30)), now=MONDAY
        )
        assert reached is not None
        exhausted = await self.records.calculate(KIMI, FIRST_PROFILE, MONDAY)
        self.assertEqual((exhausted.exhausted, exhausted.vigor), (True, 0.0))
        self.assertEqual(await self.records.last_result(KIMI), exhausted)
        self.assertEqual(await self.count("vigor_results"), 4)
# TEST-TIER-END tests/radar/test_records.py::TheRecords.test_a_calculation_is_recorded_with_its_inputs_and_read_back_as_it_was

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

# TEST-TIER-BEGIN tests/radar/test_records.py::TheRecords.test_a_database_without_the_tables_refuses_with_layout_incomplete
    async def test_a_database_without_the_tables_refuses_with_layout_incomplete(self) -> None:
        """radar.record-layout-incomplete"""
        self.assertTrue(await self.records.layout())
        await self.db.execute("DROP TABLE vigor_results")
        try:
            self.assertFalse(await self.records.layout())
            for call in (
                self.records.record_report(CLAUDE, usage(claude()), now=MONDAY),
                self.records.ensure_profile(FIRST_PROFILE, MONDAY),
                self.records.calculate(CLAUDE, FIRST_PROFILE, MONDAY),
            ):
                with self.assertRaises(Refused) as caught:
                    await call
                self.assertEqual(caught.exception.code, "layout_incomplete")
            self.assertEqual(await self.count("vigor_reports"), 0)
        finally:
            await self.db.execute(LAYOUT.read_text(encoding="utf-8"))  # the check's own layout, never the process's
        self.assertTrue(await self.records.layout())
# TEST-TIER-END tests/radar/test_records.py::TheRecords.test_a_database_without_the_tables_refuses_with_layout_incomplete



class TheReplay(_support.TheReplay):
# TEST-TIER-BEGIN tests/radar/test_records.py::TheReplay.test_profile_1_reproduces_every_recorded_result_row_for_row
    async def test_profile_1_reproduces_every_recorded_result_row_for_row(self) -> None:
        """radar.replay"""
        first = await self.records.record_report(CLAUDE, usage(claude(), extra={"isUsingOverage": False}), now=MONDAY)
        moments = [MONDAY, MONDAY + timedelta(hours=1), MONDAY + timedelta(hours=4), MONDAY + timedelta(hours=5)]
        for moment in moments[:3]:
            await self.records.calculate(CLAUDE, FIRST_PROFILE, moment)
        reached = [
            window("session", "Five hours", used=100, resets=at(hours=9, minutes=50), reached=True),
            window("weekly", "Seven days", used=23, resets=at(days=3), minutes=10080),
        ]
        second = await self.records.record_report(
            CLAUDE, usage(reached, fetched=at(hours=4, minutes=50)), now=moments[3]
        )
        assert first is not None and second is not None
        await self.records.calculate(CLAUDE, FIRST_PROFILE, moments[3])
        await self.records.calculate(ZAI, FIRST_PROFILE, MONDAY)
        recorded = await self.records.results(CLAUDE)
        self.assertEqual([entry.report for entry in recorded], [first.id, first.id, first.id, second.id])
        replays = await self.records.replay(CLAUDE, FIRST_PROFILE)
        self.assertEqual([entry.recorded for entry in replays], recorded)
        self.assertEqual([entry.replayed for entry in replays], recorded)  # row for row
        self.assertTrue(all(entry.same for entry in replays))
        self.assertEqual([entry.replayed.moment for entry in replays], moments)
        self.assertEqual(await self.count("vigor_results"), 5)  # a replay writes nothing
        # A changed formula over the same history: the gate weighs 0.5 instead of the placeholder 0.1.
        heavier = Profile(1, "proposed", "even", Weight(0.5))
        changed = await self.records.replay(CLAUDE, heavier)
        self.assertEqual([entry.recorded for entry in changed], recorded)
        self.assertFalse(changed[2].same)  # at 14:00 the five-hour window, predicted fresh, loses and weighs more
        assert changed[2].replayed.vigor is not None and recorded[2].vigor is not None
        self.assertGreater(changed[2].replayed.vigor, recorded[2].vigor)
        # At 10:00 the gate loses nothing, so the Vigor is the same, though the record shows the other weight; while
        # exhausted the Vigor is 0 whatever the weight.
        self.assertFalse(changed[0].same)
        self.assertEqual(changed[0].replayed.vigor, recorded[0].vigor)
        self.assertEqual([entry.weight for entry in changed[0].replayed.windows], [0.5, 1.0])
        self.assertEqual((changed[3].replayed.vigor, changed[3].replayed.exhausted), (0.0, True))
        self.assertEqual(await self.count("vigor_results"), 5)
        zai = await self.records.replay(ZAI, FIRST_PROFILE)
        self.assertEqual(len(zai), 1)
        self.assertTrue(zai[0].same and zai[0].recorded.unknown == "no report yet")
        self.assertEqual(await self.records.replay(CODEX, FIRST_PROFILE), [])
# TEST-TIER-END tests/radar/test_records.py::TheReplay.test_profile_1_reproduces_every_recorded_result_row_for_row
