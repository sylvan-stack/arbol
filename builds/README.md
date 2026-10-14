# Numbered Builds

`arbol-builds` implements BLD-0 in `~/Artifacts/arbol/builds/00-builds-and-versions.md`. It belongs to this repository and is installed independently of the application or any numbered Build. It is typed Python that uses only the standard library (BLD-D15). Its code is in `src/arbol_builds/`, its checks in `tests/test_builds.py`.

```sh
uv sync --locked --group dev
uv run --no-sync python scripts/install_builds.py
```

The install command puts the tool into `~/.local/bin/.arbol-builds/`, together with the same pinned standalone CPython 3.14.8 that every Build carries (`scripts/python-distribution.json`; the archive is taken from `~/.cache/arbol-driver-build/python` and checked by its SHA-256, or downloaded once). It compiles that Python's standard library and the tool, and writes the program `~/.local/bin/arbol-builds`, which starts the tool with that Python. `--bin-dir /absolute/path` installs into another folder; the path must not contain a space, because the tool and every launcher name their Python in their first line. Installing again replaces the tool and rewrites every launcher already in that folder with the current launcher code, keeping the component and the registry each one serves, launchers written by the earlier Node.js tool included (BLD-D14). Other files there are left as they are. `bin/arbol-builds` starts the tool from this checkout, with the checkout's development Python.

```sh
arbol-builds build arbol-claude-driver
arbol-builds list
arbol-builds show arbol-claude-driver
arbol-builds show arbol-claude-driver@a
arbol-builds withdraw arbol-claude-driver@a --reason 'Fails with the updated vendor tool'
arbol-builds prune arbol-claude-driver --keep 4
```

The default repository is `~/repos/sylvan-stack/<component>`. `build --repo <folder>` selects another checkout. `--registry-dir <folder>` selects another registry; the default is `~/Library/Application Support/Arbol/builds/`. `--bin-dir <folder>` selects where component launchers go; the default is `~/.local/bin`. Options work before or after the command, as `--name value` or `--name=value`.

Each repository describes its own build:

```json
{
  "component": "sample",
  "build": ["cp program.sh \"$ARBOL_BUILD_DIR/program.sh\""],
  "entry": "program.sh",
  "checks": [{"name": "sample-check", "command": "\"$ARBOL_BUILD_DIR/program.sh\" --check"}]
}
```

Build and check commands run with `/bin/sh -c` in the repository, in a session of their own, with every signal at its default. They receive `ARBOL_BUILD_DIR` and `ARBOL_BUILD_NUMBER`. The build commands place a complete runnable program in that folder, including an executable `entry`. Check commands start this program directly, while its record still says `building`. They must check the output they intend to validate. A Driver also declares positive `contract` and `dataFormat` numbers and checks of all three kinds: `unit`, `contract` and `live`. Its live check must send the one real test-account message BLD-0 requires. A nonzero check stops the build, names the failed check, and leaves `build.json` and `build.log` with status `failed`. The package version is read from the repository's `package.json`.

Build numbers are lower-case hexadecimal counts per component. An atomic directory creation reserves a number; failed builds, damaged records and pruned folders still consume theirs. Records are replaced atomically, in the same form as the earlier Node.js tool wrote them. Short process reservations in each component's `.writers/` folder serialize record changes, withdrawal and pruning; dead writers are ignored. The reservation files are those of the earlier tool, so the two tools exclude each other while both exist. Compilation and checks run outside these reservations, and launching or listing does not use them. A build interrupted by SIGINT or SIGTERM stops its commands and is recorded as failed. After an uncatchable kill the incomplete record stays `building` and cannot run.

Each component launcher is one standalone Python file that uses only the standard library: the text of `src/arbol_builds/launcher.py` followed by the call that serves its component and registry. Its first line names the Python of the `arbol-builds` that wrote it. It reads the records each time, chooses the highest working Build that still has its executable, sets SIGPIPE and SIGXFSZ back to their default, which Python changes when it starts, and then uses `os.execve` to replace itself with that executable. `sample -v 1 ...` selects Build 1 only when `-v` is the first argument. Arguments and environment, byte for byte, the working folder, standard streams, PID, signals and the exit status reach the Build directly. In the plain C locale the Build also sees `LC_CTYPE=C.UTF-8`, which Python sets. Withdrawn Builds, and failed Builds that still have their executable (BLD-D13), run only when named and print why on stderr. Refusals print a JSON error and the available build numbers. A hand-over the system refuses prints `launch_failed`.

`list` returns records with a `default` boolean; `show` returns one record, including retained failed or pruned records when named. `prune --keep <n>` requires a positive whole number. It removes files only from older working Builds, preserving the default, withdrawn Builds, failed Builds, records and logs. A retained record marks removed files with `prunedAt`. Components continue to guard the format of their own shared data; this tool records the declared format without modifying that data.

```sh
uv run --no-sync ruff check src tests scripts bin/builds_entry.py
uv run --no-sync mypy
uv run --no-sync python -B -m unittest discover -s tests
```

The 27 tests use local sample components, temporary homes and no vendor tool. The 22 that the TypeScript tool had keep their names (`builds.two-builds` and so on, as BLD-0 cites them). They cover two actual builds, concurrent numbering and record changes, source identity, failed checks, relocated folders, command ordering, the installed tool, data-format delegation, pruning, raw streams and signals. Five more cover what the Python tool adds: the launcher's signals at their default (`builds.launcher-signals`), arguments and environment byte for byte (`builds.launcher-bytes`), a refused hand-over (`builds.launch-failed`), the launchers rewritten on installation (`builds.install-refreshes-launchers`), and an installation folder with a space (`builds.install-refuses-spaces`). The three installation checks need the pinned archive in the cache and are skipped without it.

The on-demand latency check is `uv run --no-sync python tests/launcher_benchmark.py --python <interpreter> [--node-launcher <file>]`. It builds a tiny sample twice, then times rounds that start the Build's program directly and through the launcher. On 15 October 2026, on this arm64 Mac, with the pinned Python of an installation, the Python launcher added a median of 14.46 ms (95th percentile 16.3 ms) over 60 rounds; a launcher of the earlier Node.js tool (Node 24.21.0), timed in the same rounds, added 22.92 ms (24.73 ms). Evidence is in `evidence/launcher-benchmark-2026-10-15.json`. The Node.js launcher's own measurement of 7 October 2026, 21.51 ms added, is in `evidence/launcher-benchmark-2026-10-07.json`.
