# Numbered Builds

`arbol-builds` implements BLD-0 in `~/Artifacts/arbol/builds/00-builds-and-versions.md`. It belongs to this repository and is installed independently of the application or any numbered Build. It requires Node.js 24 or later on macOS or another POSIX system, with no runtime npm dependencies.

```sh
nvm use
npm ci
npm run install:builds
```

The install command compiles the tool and copies its runtime to `~/.local/bin/.arbol-builds/`, with an executable `~/.local/bin/arbol-builds`. Use `npm run install:builds -- --bin-dir /absolute/path` for another destination. The destination must be on PATH, with Node.js 24 or later available as `node`. Reinstalling replaces this copy.

```sh
arbol-builds build arbol-claude-driver
arbol-builds list
arbol-builds show arbol-claude-driver
arbol-builds show arbol-claude-driver@a
arbol-builds withdraw arbol-claude-driver@a --reason 'Fails with the updated vendor tool'
arbol-builds prune arbol-claude-driver --keep 4
```

These are interface examples. Neither Driver's `arbol-build.json` nor its first numbered Build is part of SYL-76; those belong to SYL-93 and SYL-94. A build refuses a repository that has no description.

The default repository is `~/repos/sylvan-stack/<component>`. `build --repo <folder>` selects another checkout. `--registry-dir <folder>` selects another registry; the default is `~/Library/Application Support/Arbol/builds/`. `--bin-dir <folder>` selects where component launchers go; the default is `~/.local/bin`. Options work before or after the command, as `--name value` or `--name=value`.

Each repository describes its own build:

```json
{
  "component": "sample",
  "build": ["node build.mjs"],
  "entry": "program.mjs",
  "checks": [{"name": "sample-check", "command": "node check.mjs"}]
}
```

Build and check commands run with `/bin/sh -c` in the repository. They receive `ARBOL_BUILD_DIR` and `ARBOL_BUILD_NUMBER`. The build commands place a complete runnable program in that folder, including an executable `entry`. Check commands start this program directly, while its record still says `building`. They must check the output they intend to validate. A Driver also declares positive `contract` and `dataFormat` numbers and checks of all three kinds: `unit`, `contract` and `live`. Its live check must send the one real test-account message BLD-0 requires. A nonzero check stops the build, names the failed check, and leaves `build.json` and `build.log` with status `failed`.

Build numbers are lower-case hexadecimal counts per component. An atomic directory creation reserves a number; failed builds, damaged records and pruned folders still consume theirs. Records are replaced atomically. Short process reservations in each component's `.writers/` folder serialize record changes, withdrawal and pruning; dead writers are ignored. Compilation and checks run outside these reservations, and launching or listing does not use them. Build commands interrupted by SIGINT or SIGTERM are stopped and recorded as failed. After an uncatchable kill the incomplete record stays `building` and cannot run.

Each component launcher is one standalone Node.js file, containing only built-in imports. It reads the records each time, chooses the highest working Build that still has its executable, then uses `process.execve` to replace itself with that executable. `sample -v 1 ...` selects Build 1 only when `-v` is the first argument. Arguments, environment, working folder, standard streams, PID, signals and exit status reach the Build directly. Withdrawn Builds run only when named and print their reason to stderr. Refusals print a JSON error and the available build numbers.

`list` returns records with a `default` boolean; `show` returns one record, including retained failed or pruned records when named. `prune --keep <n>` requires a positive whole number. It removes files only from older working Builds, preserving the default, withdrawn Builds, failed Builds, records and logs. A retained record marks removed files with `prunedAt`. Components continue to guard the format of their own shared data; this tool records the declared format without modifying that data.

`npm test` includes 22 build-tool tests and the existing runner tests. They use local sample repositories, temporary homes and no vendor tool. They cover two actual builds, concurrent numbering and record changes, source identity, failed checks, relocated folders, command ordering, installed launchers, data-format delegation, pruning, raw streams and signals. Real Driver build checks are covered by their own first-build tasks.

The on-demand latency check is `node builds/test/launcher-benchmark.mjs <record-path>`. It builds a tiny local component twice, then measures 30 alternating direct/launcher pairs after warmup. On 7 October 2026, Node 24.21.0 on this arm64 Mac added a median 21.51 ms (95th percentile 24.36 ms). The launcher was 5,884 bytes; total launched startup was a median 43.56 ms. Evidence is in `test/launcher-benchmark-2026-10-07.json`.
