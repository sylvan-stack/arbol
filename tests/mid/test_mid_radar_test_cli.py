
# LOW TIER — DO NOT ENABLE OR RECREATE
# Historical examples only. Read before adding related tests; never execute.
# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRollup.test_the_subscriptions_are_sorted_by_vigor_with_unknown_ones_below
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.rollup-order
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_subscriptions_are_sorted_by_vigor_with_unknown_ones_below(self) -> None:
#         """radar.rollup-order"""
#         value = rollup(MONDAY, examples())
#         self.assertEqual(
#             [entry.name for entry in value.entries],
#             [
#                 "pi/kimi-coding",
#                 "claude/anthropic",
#                 "codex/chatgpt",
#                 "pi/zai",
#                 "pi/deepseek",
#             ],
#         )
#         self.assertEqual(
#             [round(entry.vigor, 2) if entry.vigor is not None else None for entry in value.entries],
#             [0.47, 0.37, 0.16, None, None],
#         )
#         self.assertEqual(value.moment, MONDAY)
#         with_reached = rollup(MONDAY, examples(reached=True))  # the exhausted Claude account sorts last of the known
#         self.assertEqual(
#             [entry.name for entry in with_reached.entries][:3], ["pi/kimi-coding", "codex/chatgpt", "claude/anthropic"]
#         )
#         self.assertEqual(with_reached.entries[2].vigor, 0.0)
#         self.assertEqual(rollup(MONDAY, []), Rollup(MONDAY, (), {}))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRollup.test_the_headline_is_the_highest_vigor_named_with_its_subscription
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.rollup-headline
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_headline_is_the_highest_vigor_named_with_its_subscription(self) -> None:
#         """radar.rollup-headline"""
#         headline = rollup(MONDAY, examples()).headline
#         assert headline is not None and headline.vigor is not None
#         self.assertEqual((headline.subscription, headline.label, round(headline.vigor, 2)), (KIMI, "Kimi Code", 0.47))
#         unknown_only = rollup(MONDAY, [entry for entry in examples() if entry.vigor is None])
#         self.assertIsNone(unknown_only.headline)  # unknown is never promoted to a value
#         self.assertEqual(len(unknown_only.entries), 2)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRollup.test_the_text_form_is_the_radars_lines
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.rollup-text
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_the_text_form_is_the_radars_lines(self) -> None:
#         """radar.rollup-text"""
#         text = as_text(rollup(MONDAY, examples(), {"codex": "no_answer: no reply"}), UTC)
#         self.assertEqual(
#             text.splitlines(),
#             [
#                 "Subscriptions Vigor: 0.47, Kimi Code",
#                 "pi/kimi-coding 0.47 · next change 11:00, 0.47 · recorded 10:00",
#                 "claude/anthropic 0.37 · next change 13:20, 0.39 · recorded 10:00",
#                 "codex/chatgpt 0.16 · next change 12:30, 0.17 · recorded 10:00",
#                 "pi/zai · unknown: allowance not supported for zai · recorded 10:00",
#                 "pi/deepseek · no record yet",
#                 "Failed: codex · no_answer: no reply",
#             ],
#         )
#         reached = as_text(rollup(MONDAY, examples(reached=True)), UTC).splitlines()
#         self.assertEqual(reached[3], "claude/anthropic 0 · exhausted, recovers 13:20, 0.39 · recorded 10:00")
#         later = MONDAY + timedelta(hours=5, minutes=10)  # the five-hour window reset without a report: predicted, stale
#         aged = compute(report(CLAUDE, claude(), extra={"isUsingOverage": False}), FIRST_PROFILE, later)
#         lines = as_text(rollup(later, [Entry(CLAUDE, "Anthropic", aged)]), UTC).splitlines()
#         self.assertTrue(lines[1].startswith("claude/anthropic 0."))
#         self.assertIn(" · predicted · stale, report 5 h 15 min old · recorded 15:10", lines[1])
#         self.assertEqual(
#             as_text(rollup(MONDAY, [Entry(DEEPSEEK, "DeepSeek", None)]), UTC).splitlines(),
#             ["Subscriptions Vigor: unknown", "pi/deepseek · no record yet"],
#         )
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheVerb.test_what_the_verb_refuses
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.verb-refusals
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     def test_what_the_verb_refuses(self) -> None:
#         """radar.verb-refusals"""
#         for args in (
#             [],
#             ["vigor", "backend"],
#             ["radar"],
#             ["backend", "--text"],
#             ["backend", "--refresh"],
#             ["vigor", "--text", "--text"],
#             ["vigor", "--refresh", "--refresh"],
#             ["vigor", "--bogus"],
#             ["vigor", "--root-dir", "/tmp/x"],
#             ["vigor", "--root"],
#             ["vigor", "teach"],
#             ["vigor", "learn", "now"],
#             ["vigor", "profiles", "1"],
#             ["vigor", "approve"],
#             ["vigor", "approve", "2", "3"],
#             ["backend", "learn"],
#             ["vigor", "learn", "--refresh"],
#             ["vigor", "--refresh", "claude/anthropic", "profiles"],
#         ):
#             with self.subTest(args=args), self.assertRaises(Refused) as caught:
#                 parse(args)
#             self.assertEqual(caught.exception.code, "invalid_input")
#         for value in ("anthropic", "/anthropic", "claude/", "claude"):
#             with self.subTest(value=value), self.assertRaises(Refused) as caught:
#                 options(parse(["vigor", "--refresh", value]))
#             self.assertEqual(caught.exception.code, "invalid_input")
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRead.test_the_latest_record_of_every_subscription_is_shown_without_recomputing
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.read-latest
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_the_latest_record_of_every_subscription_is_shown_without_recomputing(self) -> None:
#         """radar.read-latest"""
#         await self.seed()
#         drivers(self.frame, {name: {"list": config} for name, config in LISTING.items()})
#         before = await self.count("vigor_results")
#         value = await read(self.selected, Options(), now=MONDAY + timedelta(hours=2))
#         self.assertEqual(value.moment, MONDAY + timedelta(hours=2))
#         self.assertEqual(
#             [entry.name for entry in value.entries], ["pi/kimi-coding", "claude/anthropic", "pi/zai", "codex/chatgpt"]
#         )
#         self.assertEqual([entry.label for entry in value.entries], ["Kimi-Coding", "Anthropic", "Zai", "Chatgpt"])
#         latest = value.entries[1].result
#         assert latest is not None
#         self.assertEqual(latest.moment, MONDAY + timedelta(hours=1))  # the latest record, not a fresh calculation
#         self.assertEqual(latest, await self.records.last_result(CLAUDE))
#         zai = value.entries[2].result
#         assert zai is not None
#         self.assertEqual((zai.vigor, zai.unknown), (None, "no report yet"))  # a Subscription whose Driver has no report
#         self.assertIsNone(value.entries[3].result)  # listed, never calculated: no record yet
#         self.assertEqual(dict(value.failures), {})
#         self.assertEqual(await self.count("vigor_results"), before)  # nothing recomputed (SGM-D30)
#         calls = self.frame.calls()
#         self.assertEqual([call["args"] for call in calls], [["subscriptions", "list"]] * 3)  # no vendor was contacted
#         headline = value.headline
#         assert headline is not None and headline.vigor is not None
#         self.assertEqual((headline.subscription, round(headline.vigor, 2)), (KIMI, 0.47))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRead.test_a_failing_driver_is_shown_beside_the_others
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.read-failure
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_failing_driver_is_shown_beside_the_others(self) -> None:
#         """radar.read-failure"""
#         await self.seed()
#         drivers(
#             self.frame,
#             {
#                 "arbol-claude-driver": {"list": LISTING["arbol-claude-driver"]},
#                 "arbol-codex-driver": {"list": {"status": 1}},
#                 "arbol-pi-driver": {"list": LISTING["arbol-pi-driver"]},
#             },
#         )
#         value = await read(self.selected, Options(), now=MONDAY)
#         self.assertEqual([entry.name for entry in value.entries], ["pi/kimi-coding", "claude/anthropic", "pi/zai"])
#         self.assertEqual(set(value.failures), {"codex"})
#         self.assertTrue(value.failures["codex"].startswith("no_answer: "))
#         self.assertIn("Failed: codex · no_answer: ", as_text(value, UTC))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRead.test_a_root_without_the_tables_refuses_before_any_driver_runs
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.read-layout-incomplete
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_root_without_the_tables_refuses_before_any_driver_runs(self) -> None:
#         """radar.read-layout-incomplete"""
#         drivers(self.frame, {name: {"list": config} for name, config in LISTING.items()})
#         await self.db.execute("DROP TABLE vigor_results")
#         try:
#             with self.assertRaises(Refused) as caught:
#                 await read(self.selected, Options(), now=MONDAY)
#             self.assertEqual(caught.exception.code, "layout_incomplete")
#             self.assertEqual(self.frame.calls(), [])
#         finally:
#             await self.db.execute(LAYOUT.read_text(encoding="utf-8"))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRead.test_the_program_prints_one_json_document_or_the_radars_lines
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.read-program
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_the_program_prints_one_json_document_or_the_radars_lines(self) -> None:
#         """radar.read-program"""
#         await self.seed()
#         drivers(self.frame, {name: {"list": config} for name, config in LISTING.items()})
#         status, out, err = self.answer()
#         self.assertEqual((status, err), (0, ""))
#         document: dict[str, Any] = json.loads(out)
#         self.assertEqual(out.count("\n"), 1)  # one JSON document, one line
#         self.assertEqual(set(document), {"moment", "headline", "subscriptions", "failures"})
#         self.assertEqual(
#             [item["subscription"] for item in document["subscriptions"]], ["kimi-coding", "anthropic", "zai", "chatgpt"]
#         )
#         self.assertEqual(document["headline"]["subscription"], "kimi-coding")
#         self.assertEqual(await self.count("vigor_results"), 4)  # the program recomputed nothing
#         status, out, err = self.answer("--text")
#         self.assertEqual((status, err), (0, ""))
#         lines = out.splitlines()
#         self.assertEqual(lines[0], "Subscriptions Vigor: 0.47, Kimi-Coding")
#         self.assertTrue(lines[1].startswith("pi/kimi-coding 0.47 · next change "))
#         # The latest record as it was computed at Monday 11:00, with its moment: nothing is computed afresh today.
#         self.assertTrue(lines[2].startswith("claude/anthropic 0.40 · next change "))
#         self.assertTrue(lines[2].endswith(" · recorded " + when(MONDAY + timedelta(hours=1), datetime.now(UTC))))
#         self.assertNotIn("predicted", lines[2])
#         self.assertTrue(lines[3].startswith("pi/zai · unknown: no report yet · recorded "))
#         self.assertEqual(lines[4], "codex/chatgpt · no record yet")
#         status, out, err = self.answer("--bogus")
#         self.assertEqual((status, json.loads(out)["error"]["code"]), (1, "invalid_input"))
#         status, out, err = self.answer("--refresh", "nobody")
#         self.assertEqual((status, json.loads(out)["error"]["code"]), (1, "invalid_input"))
#         self.assertEqual(await self.count("vigor_results"), 4)
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRefresh.test_usage_runs_for_every_subscription_and_nothing_else_and_everything_is_recomputed
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.refresh-usage-only
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_usage_runs_for_every_subscription_and_nothing_else_and_everything_is_recomputed(self) -> None:
#         """radar.refresh-usage-only"""
#         drivers(self.frame, refreshed())
#         now = MONDAY + timedelta(hours=2, minutes=1)
#         value = await read(self.selected, Options(refresh=True), now=now)
#         self.assertEqual(
#             self.commands(),
#             [
#                 ["subscriptions", "list"],
#                 ["subscriptions", "list"],
#                 ["subscriptions", "list"],
#                 ["subscriptions", "usage", "anthropic"],
#                 ["subscriptions", "usage", "chatgpt"],
#                 ["subscriptions", "usage", "kimi-coding"],
#                 ["subscriptions", "usage", "zai"],
#             ],
#         )
#         self.assertEqual(await self.count("vigor_reports"), 4)  # every fresh report recorded, the unsupported one too
#         self.assertEqual(await self.count("vigor_results"), 4)  # every Subscription recomputed and recorded
#         self.assertEqual(
#             [entry.name for entry in value.entries], ["pi/kimi-coding", "claude/anthropic", "codex/chatgpt", "pi/zai"]
#         )
#         for entry in value.entries:
#             assert entry.result is not None
#             self.assertEqual(entry.result.moment, now)
#             self.assertEqual(entry.result, await self.records.last_result(entry.subscription))
#         anthropic = value.entries[1].result
#         assert anthropic is not None and anthropic.vigor is not None
#         last = await self.records.last_report(CLAUDE)
#         assert last is not None
#         self.assertEqual(anthropic.report, last.id)
#         self.assertEqual([entry.used_percent for entry in anthropic.windows], [10.0, 22.0])  # the vendor's numbers
#         zai = value.entries[3].result
#         assert zai is not None
#         self.assertEqual((zai.vigor, zai.unknown), (None, "allowance not supported for zai"))
#         self.assertEqual(dict(value.failures), {})
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRefresh.test_a_fresh_report_replaces_every_predicted_window
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.refresh-replaces-prediction
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_fresh_report_replaces_every_predicted_window(self) -> None:
#         """radar.refresh-replaces-prediction"""
#         drivers(self.frame, refreshed())
#         await self.records.record_report(CLAUDE, usage(claude(), extra={"isUsingOverage": False}), now=MONDAY)
#         half_past = MONDAY + timedelta(hours=3, minutes=30)  # the five-hour reset at 13:20 passed without a report
#         await self.records.calculate(CLAUDE, FIRST_PROFILE, half_past)
#         shown = (await read(self.selected, Options(), now=half_past)).entries
#         predicted = next(entry.result for entry in shown if entry.subscription == CLAUDE)
#         assert predicted is not None
#         self.assertTrue(predicted.predicted and predicted.windows[0].predicted)
#         self.assertEqual(self.commands(), [["subscriptions", "list"]] * 3)  # the plain read ran no usage
#         fresh = [
#             window("session", "Five hours", used=2, resets=at(hours=8, minutes=20), minutes=300),
#             window("weekly", "Seven days", used=21, resets=at(days=3), minutes=10080),
#         ]
#         drivers(self.frame, refreshed(anthropic={"output": usage(fresh, fetched=at(hours=3, minutes=25))}))
#         later = half_past + timedelta(minutes=1)
#         value = await read(self.selected, Options(refresh=True, target=("claude", "anthropic")), now=later)
#         result = next(entry.result for entry in value.entries if entry.subscription == CLAUDE)
#         assert result is not None
#         self.assertFalse(result.predicted)
#         self.assertFalse(any(entry.predicted for entry in result.windows))
#         self.assertEqual([entry.used_percent for entry in result.windows], [2.0, 21.0])
#         self.assertEqual(result.windows[0].resets_at, MONDAY + timedelta(hours=8, minutes=20))
#         self.assertEqual(result.moment, later)
#         self.assertEqual(await self.records.results(CLAUDE), [predicted, result])  # the prediction stays on record
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRefresh.test_one_named_subscription_is_refreshed_and_every_one_recomputed
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.refresh-one
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_one_named_subscription_is_refreshed_and_every_one_recomputed(self) -> None:
#         """radar.refresh-one"""
#         drivers(self.frame, refreshed())
#         value = await read(self.selected, Options(refresh=True, target=("pi", "kimi-coding")), now=MONDAY)
#         self.assertEqual(
#             [args for args in self.commands() if args[1] == "usage"], [["subscriptions", "usage", "kimi-coding"]]
#         )
#         self.assertEqual(await self.count("vigor_reports"), 3)  # Kimi's fresh report, the listing's Claude and Codex
#         self.assertEqual(await self.count("vigor_results"), 4)
#         self.assertEqual(
#             [entry.name for entry in value.entries], ["pi/kimi-coding", "claude/anthropic", "codex/chatgpt", "pi/zai"]
#         )
#         kimi_report = await self.records.last_report(KIMI)
#         assert kimi_report is not None
#         self.assertEqual(kimi_report.fetched_at, MONDAY + timedelta(hours=2))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRefresh.test_a_failing_fetch_is_shown_beside_the_others
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.refresh-failure
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_failing_fetch_is_shown_beside_the_others(self) -> None:
#         """radar.refresh-failure"""
#         drivers(
#             self.frame,
#             refreshed(
#                 chatgpt={"status": 1},  # the launcher ends without a reply
#                 anthropic={"output": {"outcome": "ok", "windows": claude()}},  # no fetchedAt: rejected by the Interface
#                 **{"kimi-coding": {"raw": "[1, 2]"}},  # not a usage report
#             ),
#         )
#         value = await read(self.selected, Options(refresh=True), now=MONDAY)
#         self.assertEqual(set(value.failures), {"claude/anthropic", "codex/chatgpt", "pi/kimi-coding"})
#         self.assertTrue(value.failures["codex/chatgpt"].startswith("no_answer: "))
#         self.assertTrue(value.failures["claude/anthropic"].startswith("invalid_report: "))
#         self.assertTrue(value.failures["pi/kimi-coding"].startswith("invalid_reply: "))
#         self.assertEqual(
#             [entry.name for entry in value.entries], ["pi/kimi-coding", "claude/anthropic", "codex/chatgpt", "pi/zai"]
#         )
#         self.assertEqual(await self.count("vigor_reports"), 4)  # the listing's three reports and z.ai's fresh one
#         self.assertEqual(await self.count("vigor_results"), 4)  # every Subscription still recomputed
#         self.assertIn("Failed: claude/anthropic · invalid_report: ", as_text(value, UTC))
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRefresh.test_a_subscription_nobody_lists_is_refused_before_anything_runs
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.refresh-unknown
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_a_subscription_nobody_lists_is_refused_before_anything_runs(self) -> None:
#         """radar.refresh-unknown"""
#         drivers(self.frame, refreshed())
#         with self.assertRaises(Refused) as caught:
#             await read(self.selected, Options(refresh=True, target=("pi", "nobody")), now=MONDAY)
#         self.assertEqual(caught.exception.code, "invalid_input")
#         self.assertEqual(self.commands(), [["subscriptions", "list"]] * 3)
#         self.assertEqual(await self.count("vigor_results"), 0)
#         failing = refreshed()
#         failing["arbol-codex-driver"] = {"list": {"status": 1}}  # the Driver that lists the named one failed
#         drivers(self.frame, failing)
#         value = await read(self.selected, Options(refresh=True, target=("codex", "chatgpt")), now=MONDAY)
#         self.assertEqual(set(value.failures), {"codex"})
# LOW-TIER-SOURCE-END
# LOW-TIER-END

# LOW-TIER-BEGIN: tests/mid/test_mid_radar_test_cli.py::TheRefresh.test_the_program_refreshes
# Reason: Reviewed model/store calculation case: ordinary arithmetic, formatting, defaults or direct branch confirmation; retained approval, secret-persistence and last-gating-window cases cover the consequential non-obvious invariants. Case reviewed: radar.refresh-program
# Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/test_mid_radar_test_cli.py
# Historical fixtures and class context are available at the source revision; no active dependencies restored.
# LOW-TIER-SOURCE-BEGIN
#     async def test_the_program_refreshes(self) -> None:
#         """radar.refresh-program"""
#         drivers(self.frame, refreshed())
#         child = self.frame.start(args=self.vigor("--refresh", "--text"))
#         out, err = child.communicate(timeout=30)
#         self.assertEqual((child.returncode, err), (0, b""))
#         lines = out.decode().splitlines()
#         self.assertTrue(lines[0].startswith("Subscriptions Vigor: 0."))
#         self.assertEqual(len(lines), 5)
#         self.assertEqual(await self.count("vigor_results"), 4)
#         child = self.frame.start(args=self.vigor("--refresh", "pi/zai"))
#         out, err = child.communicate(timeout=30)
#         document = json.loads(out)
#         self.assertEqual(child.returncode, 0)
#         self.assertEqual(document["subscriptions"][-1]["result"]["unknown"], "allowance not supported for zai")
#         self.assertEqual(await self.count("vigor_results"), 8)
# LOW-TIER-SOURCE-END
# LOW-TIER-END
