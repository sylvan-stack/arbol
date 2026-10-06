# Driver conformance

One command tests every Driver through its command line, using that Driver's `dev stand-in` instead of the vendor tool. It imports no Driver code and uses temporary homes, loopback vendor listeners and synthetic Keychain values in isolated test services. It needs no vendor account, external network or quota. Twenty-four scenarios cover Subscription operations, fresh runs, request defaults, event ordering, complete blocks, usage totals, concurrent runs and slow readers, large tool results, conversation continuity and native history rebuilding, active run records, control refusals, and startup or partial-output failures. Reports name the portions deferred to stopping, questions/background tasks and error mapping. C5 still uses a synthetic run owner to check refusal and forced cancellation.

Use Node.js 24 (`nvm use`), run `npm ci` and `npm run build`, and build the Driver being checked. Then:

```sh
npm exec -- arbol-conformance --driver ../arbol-claude-driver/bin/arbol-claude-driver.mjs
npm exec -- arbol-conformance --driver arbol-claude-driver --only C31,C32
```

The second form uses an installed launcher on the search path. A command with fixed arguments is one quoted value, for example `--driver 'node ../arbol-claude-driver/bin/arbol-claude-driver.mjs'`. Quote paths with spaces inside that value too. Words are split without running a shell; substitutions, pipes and redirects are never evaluated. Executables and existing relative file arguments resolve from the caller's working folder. `--only 'C31 C32'` also works; unknown or unimplemented identifiers fail before any Driver starts.

Each scenario gets a new private home, both contract settings filenames naming `<home>/tool/vendor-tool`, a shell launcher calling the selected Driver's `dev stand-in`, and `<home>/tool/scenario`. Driver invocations work in that home with a minimal environment and `ARBOL_TEST_TIME_SCALE=100`; authentication scenarios use 10 where replacement must allow real subprocess startup, then 100 for the expiry check. `received.jsonl` is parsed and checked alongside stdout and exit status. Subprocesses have a 15 second deadline and 4 MiB output limit; their process groups are ended before the home is removed, including on failure or cancellation. Keychain items created by a scenario are removed in its cleanup.

The report names each scenario and its scope. A failed assertion prints its expected and received values. Exit status is 0 when every selected scenario passes, 1 when any scenario fails, and 2 for invalid input or an interrupted suite. `npm test` checks the runner's own failure reporting, isolation, selection and process cleanup using a synthetic Driver with a different version protocol.

To add a scenario:

1. Add a module under `scenarios/` exporting a `Scenario` with `id`, `title`, `scope`, `covers` and `run(home)`; register it in `scenarios/index.ts`.
2. Use `home.part('part')`, `home.call(...)` / `home.json(...)`, `home.start(...)` for streaming sign-in, `home.settings(...)`, `home.received()` and the helpers in `check.ts`. Judge only the contract and recorded tool activity. Keep vendor protocol knowledge in each Driver's stand-in, whose scripts cite raw probe evidence.
3. Add the corresponding scenario parts to each Driver's stand-in, run the scenario, and name the check in the specification's requirement table. State partial coverage in `scope`; do not claim the remaining checks pass.
