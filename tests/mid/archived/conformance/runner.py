# Mid-tier source from conformance/runner.py; see MID_TIER.md.
# Shared helpers and refusal entry points remain at the original path.

# TEST-TIER-DISABLED-BEGIN: conformance/runner.py::run_suite
# async def run_suite(
#     command: list[str],
#     selected: list[Scenario],
#     *,
#     timeout_ms: float | None = None,
#     signal_: Abort | None = None,
#     write: Callable[[str], None] | None = None,
# ) -> int:
#     write = write or _stdout
#     passed = 0
#     if signal_ is not None:
#         await _signals()
#     native_pi = False
#     native_mimo = False
#     discovery = await ScenarioHome.create("identity", command, min(timeout_ms or 15000, 1500), signal_)
#     try:
#         await discovery.part("missing", missing=True)
#         identity = await discovery.json(["info"])
#         native_pi = identity.result.get("driver") == "pi"
#         native_mimo = identity.result.get("driver") == "mimo"
#     except Exception:
#         # The selected scenarios report malformed/unavailable Drivers themselves.
#         pass
#     finally:
#         await discovery.dispose()
#     for scenario in selected:
#         fixture: ScenarioHome | None = None
#         scope = scenario.scope
#         try:
#             if signal_ is not None:
#                 signal_.throw_if_aborted()
#             fixture = await ScenarioHome.create(scenario.id, command, timeout_ms, signal_)
#             if native_mimo:
#                 from .scenarios.mimo import SCOPES, prepare, run
#
#                 scope = SCOPES[scenario.id]
#                 await prepare(fixture)
#                 await run(fixture)
#             elif native_pi:
#                 from .scenarios.pi import SCOPES, prepare, run
#
#                 scope = SCOPES.get(scenario.id, "unimplemented Pi variant")
#                 await prepare(fixture)
#                 await run(fixture)
#             else:
#                 await scenario.run(fixture)
#             await fixture.dispose()
#             fixture = None
#             write(f"PASS {scenario.id} — {scenario.title} ({scope})")
#             passed += 1
#         except Exception as error:
#             write(f"FAIL {scenario.id} — {scenario.title} ({scope})")
#             write(f"  {message_of(error)}")
#             if isinstance(error, Mismatch):
#                 write(f"  Expected: {inspect(error.expected)}")
#                 write(f"  Received: {inspect(error.actual, 2048)}")
#         finally:
#             if fixture is not None:
#                 await fixture.dispose()
#         if signal_ is not None:
#             await _signals()
#             if signal_.aborted:
#                 break
#     write(f"{passed}/{len(selected)} scenarios passed.")
#     if signal_ is not None and signal_.aborted:
#         return 2
#     return 0 if passed == len(selected) else 1
# TEST-TIER-DISABLED-END

# TEST-TIER-IMPORTS: original scope column 0
# from collections.abc import Callable

# TEST-TIER-IMPORTS: original scope column 0
# from .check import Mismatch, message_of

# TEST-TIER-IMPORTS: original scope column 0
# from .harness import Scenario, ScenarioHome

# TEST-TIER-IMPORTS: original scope column 0
# from .inspect import inspect

# TEST-TIER-IMPORTS: original scope column 0
# from .process import Abort

raise RuntimeError("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.")
