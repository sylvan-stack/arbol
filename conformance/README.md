# Driver conformance

One command tests every Driver through its command line, using that Driver's `dev stand-in` instead of the vendor tool. It imports no Driver code and uses temporary homes, loopback vendor listeners and synthetic Keychain values in isolated test services. It needs no vendor account, external network or quota. Thirty-eight scenarios cover Subscription operations, fresh runs, request defaults, event ordering, complete blocks, usage totals, concurrent runs and slow readers, large tool results, conversation continuity and native history rebuilding, active run records, cancellation, shell-group cleanup, recovery after killing a Driver, control refusals, questions and their answers, unexpected permission requests, owner skills and MCP servers, background completion, and startup or partial-output failures. C26–C30 also cover error mapping, vendor wait hints, early credential rejection, start/idle/total limits, paused idle clocks and cached run-derived usage. C5 checks refusal and forced cancellation of an actual Driver run, including shell cleanup. C7 checks credential redaction in events, errors, state and text output. C32 checks every command and option, file/stdin requests, exit codes, development probes, a one-message build check and live-account refusals. Development commands use the scenario's stand-in and isolated test Subscription, never a real vendor.

The suite is typed Python that uses only the standard library. It runs on Python 3.14, the checkout's `.venv/bin/python` or a Build's own runtime, with nothing to install or compile. Build the Driver being checked. Then, from this repository:

```sh
python3.14 -I -B conformance/bin/arbol-conformance.py --driver ../arbol-claude-driver/bin/arbol-claude-driver
python3.14 -I -B conformance/bin/arbol-conformance.py --driver arbol-claude-driver --only C31,C32
```

The second form uses an installed launcher on the search path. A command with fixed arguments is one quoted value, for example `--driver 'arbol-claude-driver -v 1'`. Quote paths with spaces inside that value too. Words are split without running a shell; substitutions, pipes and redirects are never evaluated. Executables and existing relative file arguments resolve from the caller's working folder. `--only 'C31 C32'` also works; unknown or unimplemented identifiers fail before any Driver starts.

For the Subscription scenarios alone, run with `--only C1,C2,C4,C5,C6,C7,C8,C39,C40,C41`. They keep their inference checks, including C5's active-run refusal and cancellation. C2 discovers the vendor-login family and handles either a caller-entered code or a device code shown with an `open_url` step. C7 and C8 discover families as well; C41 tests the offered families' usage and catalog behavior. Codex's stand-in records each app-server request in addition to process launches, so pagination, account renewal and absence of inference requests can be checked without a vendor account.

For history and continuity, run with `--only C14`. It runs the full shared C14 scenario, including saved conversation checks, all rebuild reasons, native tool/image history, visible text fallback, competing resumes and map invalidation after failure. C14 checks Codex app-server injection and ephemeral threads through recorded RPCs and Codex rollouts under `sessions`; it checks Claude through its native session files and CLI arguments. Both Drivers use the same caller history and assertions.

Each scenario gets a new private home, both contract settings filenames naming `<home>/tool/vendor-tool`, a shell launcher calling the selected Driver's `dev stand-in`, and `<home>/tool/scenario`. Driver invocations work in that home with a minimal environment and `ARBOL_TEST_TIME_SCALE=100`; authentication scenarios use 10 where replacement must allow real subprocess startup, then 100 for the expiry check. C29 uses 10 for every part except the one that tests the start limit, so that starting the stand-in on a busy machine cannot reach that limit. `received.jsonl` is parsed and checked alongside stdout and exit status. Subprocesses have a 15 second deadline and 4 MiB output limit; their process groups are ended before the home is removed, including on failure or cancellation. Keychain items created by a scenario are removed in its cleanup.

The report names each scenario and its scope. A failed assertion prints its expected and received values. Exit status is 0 when every selected scenario passes, 1 when any scenario fails, and 2 for invalid input or an interrupted suite. `uv run --no-sync python -B -m unittest discover -s conformance/tests -t .` checks the runner's own failure reporting, isolation, selection and process cleanup using a synthetic Driver with a different version protocol; Ruff and strict mypy check the suite with the rest of this repository.

Scenarios judge JSON with JavaScript's strict meaning, as the TypeScript suite did until 15 October 2026: `true` is not `1`, an absent field is not `null`, numbers are doubles, and JSON text is parsed, measured and printed as JavaScript does (`js.py`; the Expected and Received values print as Node's `util.inspect` did, `inspect.py`). Drivers start as Node started them: in a session of their own, every signal at its default and none blocked, standard input from `/dev/null`. Where the TypeScript suite failed with a message of the JavaScript engine, such as reading a field of a missing value, the report carries the same V8 text.

On 15 October 2026 both suites gave identical reports for all 38 scenarios on both Drivers, and in several hundred cases of faulty Driver output and bad input. The known differences arise only from Driver output that breaks the contract or from extreme inputs:

- A refused JSON text carries Python's wording, not V8's.
- Timestamps are read only in ISO 8601 form; V8 also took older free forms such as `Oct 15 2026`.
- File names that are not valid UTF-8 are sorted and printed slightly differently.
- Nesting thousands of levels deep: printing a value as JSON or as text works at any depth, where V8 ran out of stack at about 6,000 and 2,800 levels. Deep comparison stops at about 1,000 levels in both.
- The first folder on the Driver's search path is Python's, where it was Node's, so a Driver launched with `node` from the search path fails to start.
- The C41 stand-in for the Z.AI gateway accepts some malformed HTTP requests that Node refused, so a Driver that sends them sees a different list of received paths.
- Timing only: output over 4 MiB is cut a few tens of milliseconds later, and a paused reader holds exactly 64 KiB.

To add a scenario:

1. Add a module under `scenarios/` with a `Scenario(id, title, scope, covers, run)`, where `run` is `async def run(home)`; add the module to `scenarios/__init__.py`.
2. Use `await home.part('part')`, `await home.call(...)` / `await home.json(...)`, `home.start(...)` for streaming sign-in, `await home.settings(...)`, `await home.received()`, the helpers in `check.py`, and the JavaScript value helpers of `js.py` and `scenarios/support.py`. Judge only the contract and recorded tool activity. Keep vendor protocol knowledge in each Driver's stand-in, whose scripts cite raw probe evidence.
3. Add the corresponding scenario parts to each Driver's stand-in, run the scenario, and name the check in the specification's requirement table. State partial coverage in `scope`; do not claim the remaining checks pass.
