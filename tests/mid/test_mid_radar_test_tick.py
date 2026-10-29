
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheTick.test_a_tick_records_the_newer_reports_and_recalculates_every_subscription
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.tick-records
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_tick_records_the_newer_reports_and_recalculates_every_subscription(self) -> None:
#         """radar.tick-records"""
#         programs = self.programs(listing())
#         done = await tick(programs, self.records, FIRST_PROFILE, MONDAY)
#         self.assertEqual(done.moment, MONDAY)
#         self.assertEqual([report.subscription for report in done.reports], [CLAUDE, CODEX, KIMI])
#         self.assertEqual([result.subscription for result in done.results], [CLAUDE, CODEX, KIMI, ZAI])
#         self.assertEqual(dict(done.failures), {})
#         self.assertEqual(self.commands(), [LIST] * 3)  # `list` and nothing else: no vendor
#         self.assertEqual((await self.count("vigor_reports"), await self.count("vigor_results")), (3, 4))
#         self.assertEqual(await self.records.last_result(ZAI), done.results[3])
#         self.assertEqual((done.results[3].vigor, done.results[3].unknown), (None, "no report yet"))
#         again = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(minutes=3))
#         self.assertEqual(again.reports, ())  # nothing newer arrived: no report recorded again
#         self.assertEqual((await self.count("vigor_reports"), await self.count("vigor_results")), (3, 8))
#         self.assertEqual([result.moment for result in again.results], [MONDAY + timedelta(minutes=3)] * 4)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheTick.test_a_new_report_takes_effect_at_the_next_tick
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.tick-new-report
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_new_report_takes_effect_at_the_next_tick(self) -> None:
#         """radar.tick-new-report"""
#         programs = self.programs(listing())
#         first = await tick(programs, self.records, FIRST_PROFILE, MONDAY)
#         newer = usage(claude(60, 30), fetched=at(hours=1), extra={"isUsingOverage": False})  # a run moved the numbers
#         drivers(self.frame, listing(**{"arbol-claude-driver": {"output": [record(CLAUDE, newer)]}}))
#         second = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(hours=1))
#         self.assertEqual([report.subscription for report in second.reports], [CLAUDE])
#         self.assertNotEqual(second.results[0].report, first.results[0].report)
#         self.assertEqual(second.results[0].report, second.reports[0].id)
#         self.assertEqual([entry.used_percent for entry in second.results[0].windows], [60.0, 30.0])
#         self.assertEqual(await self.count("vigor_reports"), 4)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheTick.test_a_passed_reset_takes_effect_at_the_next_tick_and_never_earlier
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.tick-passed-reset
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_passed_reset_takes_effect_at_the_next_tick_and_never_earlier(self) -> None:
#         """radar.tick-passed-reset"""
#         programs = self.programs(listing())
#         await tick(programs, self.records, FIRST_PROFILE, MONDAY)
#         before = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(hours=3, minutes=19))
#         self.assertFalse(before.results[0].predicted)  # 13:19: the five-hour window has a minute left
#         self.assertEqual(before.results[0].windows[0].used_percent, 35.0)
#         after = await tick(programs, self.records, FIRST_PROFILE, MONDAY + timedelta(hours=3, minutes=21))
#         self.assertTrue(after.results[0].predicted and after.results[0].windows[0].predicted)  # 13:21: reset passed
#         self.assertEqual(after.results[0].windows[0].used_percent, 0.0)
#         self.assertEqual(after.results[0].windows[0].resets_at, MONDAY + timedelta(hours=8, minutes=20))
#         assert after.results[0].vigor is not None
#         self.assertEqual(round(after.results[0].vigor, 2), 0.39)  # the worked example's value at 13:20
#         self.assertEqual(await self.records.last_result(CLAUDE), after.results[0])
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheTick.test_the_ticker_ticks_every_three_minutes_and_no_faster
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.tick-interval
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_the_ticker_ticks_every_three_minutes_and_no_faster(self) -> None:
#         """radar.tick-interval"""
#         programs = self.programs(listing())
#         clock = Clock(MONDAY)
#         ticker = Ticker(programs, self.records, clock=clock)
#         self.assertEqual(ticker.interval, timedelta(minutes=3))  # the profile's value (SGM-D30)
#         self.assertEqual(FIRST_PROFILE.tick_minutes, 3.0)
#         first = await ticker.wake()  # the first wake ticks at once
#         assert first is not None
#         self.assertEqual(first.moment, MONDAY)
#         for seconds in (4, 60, 120, 179):
#             clock.now = MONDAY + timedelta(seconds=seconds)
#             self.assertIsNone(await ticker.wake())  # within the interval: nothing
#         clock.now = MONDAY + timedelta(minutes=3)
#         second = await ticker.wake()
#         assert second is not None
#         self.assertEqual(second.moment, MONDAY + timedelta(minutes=3))
#         clock.now = MONDAY + timedelta(minutes=3, seconds=4)
#         self.assertIsNone(await ticker.wake())
#         self.assertEqual(await self.count("vigor_results"), 8)
#         self.assertEqual(self.commands(), [LIST] * 6)  # two ticks, three Drivers each, nothing else
#         slower = Profile(1, "proposed", "even", Weight(0.1), tick_minutes=5)
#         self.assertEqual(Ticker(programs, self.records, slower).interval, timedelta(minutes=5))
#         for bad in (0, -3, float("inf")):
#             with self.assertRaises(Rejected) as caught:
#                 Profile(1, "proposed", "even", Weight(0.1), tick_minutes=bad)
#             self.assertEqual(caught.exception.field, "tickMinutes")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheTick.test_a_database_without_the_tables_refuses_and_is_tried_again_one_interval_later
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.tick-layout-incomplete
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_database_without_the_tables_refuses_and_is_tried_again_one_interval_later(self) -> None:
#         """radar.tick-layout-incomplete"""
#         programs = self.programs(listing())
#         clock = Clock(MONDAY)
#         ticker = Ticker(programs, self.records, clock=clock)
#         await self.db.execute("DROP TABLE vigor_results")
#         try:
#             with self.assertRaises(Refused) as caught:
#                 await ticker.wake()
#             self.assertEqual(caught.exception.code, "layout_incomplete")
#             self.assertEqual(self.commands(), [])  # no Driver was run
#             clock.now = MONDAY + timedelta(minutes=1)
#             self.assertIsNone(await ticker.wake())  # not tried again sooner
#         finally:
#             await self.db.execute(LAYOUT.read_text(encoding="utf-8"))
#         clock.now = MONDAY + timedelta(minutes=3)
#         done = await ticker.wake()
#         assert done is not None
#         self.assertEqual(len(done.results), 4)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheTick.test_a_failing_driver_or_report_is_named_and_the_others_go_on
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.tick-failure
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_failing_driver_or_report_is_named_and_the_others_go_on(self) -> None:
#         """radar.tick-failure"""
#         bad = {"outcome": "ok", "fetchedAt": at(), "windows": "x"}  # rejected by the Interface
#         replies: dict[str, dict[str, Any]] = {
#             "arbol-codex-driver": {"status": 1},
#             "arbol-claude-driver": {"output": [record(CLAUDE, bad)]},
#         }
#         programs = self.programs(listing(**replies))
#         done = await tick(programs, self.records, FIRST_PROFILE, MONDAY)
#         self.assertEqual(set(done.failures), {"codex", "claude/anthropic"})
#         self.assertTrue(done.failures["claude/anthropic"].startswith("invalid_report: "))
#         self.assertEqual([result.subscription for result in done.results], [CLAUDE, KIMI, ZAI])
#         self.assertEqual((done.results[0].vigor, done.results[0].unknown), (None, "no report yet"))
#         self.assertEqual([report.subscription for report in done.reports], [KIMI])
#         self.assertIsInstance(done, Tick)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheBackend.test_the_running_backend_ticks_at_its_first_wake_and_not_again_within_the_interval
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.backend-ticks
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_the_running_backend_ticks_at_its_first_wake_and_not_again_within_the_interval(self) -> None:
#         """radar.backend-ticks"""
#         drivers(self.frame, listing())
#         child = self.backend()
#         try:
#             for _ in range(60):  # the first wake comes four seconds after start
#                 if await self.count("vigor_results") >= 4:
#                     break
#                 await asyncio.sleep(0.25)
#             self.assertEqual(await self.count("vigor_results"), 4)  # one result per listed Subscription
#             self.assertEqual(await self.count("vigor_reports"), 3)  # the listing's reports, recorded once
#             self.assertEqual(await self.count("vigor_profiles"), 1)
#             await asyncio.sleep(2)
#             self.assertEqual(await self.count("vigor_results"), 4)  # no second tick within the interval
#             # The backend's own account listing at startup asks `list` too (SYL-253): the tick adds `list` and nothing
#             # else, and no `usage`, since a tick contacts no vendor.
#             driver_calls = [call["args"] for call in self.frame.calls() if call["program"].endswith("-driver")]
#             self.assertTrue(all(args == LIST for args in driver_calls))
#             self.assertGreaterEqual(len(driver_calls), 3)
#             self.assertIsNone(child.poll())
#         finally:
#             self.stop(child)
#         self.assertEqual(child.returncode, 0)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_tick.py::TheBackend.test_a_root_without_the_tables_leaves_the_backend_running_without_vigor
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.backend-layout-incomplete
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_tick.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_root_without_the_tables_leaves_the_backend_running_without_vigor(self) -> None:
#         """radar.backend-layout-incomplete"""
#         drivers(self.frame, listing())
#         await self.db.execute("DROP TABLE vigor_results")
#         try:
#             child = self.backend()
#             try:
#                 await asyncio.sleep(6)
#                 self.assertIsNone(child.poll())  # still running after its first wake
#                 self.assertEqual(await self.count("vigor_reports"), 0)  # the tick refused before listing anything
#                 self.assertEqual(await self.count("vigor_profiles"), 0)
#             finally:
#                 self.stop(child)
#             self.assertEqual(child.returncode, 0)
#         finally:
#             await self.db.execute(LAYOUT.read_text(encoding="utf-8"))
# LOW-TIER-SOURCE-END
# LOW-TIER-END
