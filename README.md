# Arbol

Arbol 2: the rewrite of Arbol, the local macOS application for working with several coding agents at once.

The shared Driver conformance runner, all 38 scenarios of DRV-5, is in [`conformance/`](conformance/README.md). It is typed Python since SYL-166 and needs no Node.js. The Root-scoped Backend process foundation is in `src/arbol_backend/`; its Bridge and Elma Chat remain later work.

The [`arbol-builds` tool](builds/README.md) builds components into numbered folders, runs their checks, lists and withdraws Builds, prunes older files on command, and writes standalone component launchers (SYL-76). It is typed Python since SYL-165, with its own pinned Python. Install it with `uv sync --locked --group dev` and `uv run --no-sync python scripts/install_builds.py`. The Drivers' own build descriptions and first Builds are separate tasks.

The global `arbol-roots` catalogue is installed beside `arbol-builds` on that same pinned Python (SYL-160). It creates Roots with empty databases, copies per-Root settings once when growing from another Root, lists/selects the current Root, checks compatible Trivial Trunk readiness, records failures and App minimums, and removes only an explicitly named noncurrent Root. Its source is `src/arbol_roots/`; unit checks are in `tests/test_roots.py`, the isolated damaged-record drill is `scripts/roots_drill.py`, and `python tests/test_roots.py --real-server` runs the disposable-database acceptance example. See [the tool guide](builds/README.md) for commands, isolation options and failure recovery. `migrate` recreates only a preparing Root’s database and applies its chosen Build’s copied SQL; `layout` applies additive layouts to a working/failed Root. `migrate <root> --check` compares source progress and changes only stale marks; `--chat <target-copy-uuid>` replaces an uncontinued copy or brings the original beside a continued copy. These mutually exclusive modes require a working/failed Root with lineage and verified advertised support, never recreate a database, and never apply layouts implicitly. Inspect the actual copy after an uncertain result before retrying. All SQL commands preflight the manifest and database identities, protect the files from pruning, and keep Root metadata unchanged. `scripts/roots_sql_drill.py` qualifies runtime SQL on uniquely named disposable databases of the installed server. The per-Root manager remains a separate component.

The directly installed PostgreSQL server and its repeatable probe are documented in [database/](database/README.md) (SYL-156). It uses its own data folder and launch agent on loopback port 5433, leaving the container on 5432 unchanged. The database scripts and the global catalogue are included in the repository's strict static checks.

| | |
|---|---|
| Package | `@sylvan-stack/arbol` 2.0.0 |
| Artifact corpus | `~/Artifacts/arbol` (GitHub `sylvan-stack/arbol-artifacts`) |
| Predecessor | `sylvan-stack/arbol_deprecated_v1`, frozen. This repository starts at 2.0.0 because version 1 is that deprecated code base |

## What the rewrite is built from

`arbol --root <root> backend` starts one Backend for that Root. A private lock/socket and one ready JSON line identify it; SIGTERM, SIGINT or pipe EOF close its clients and release the socket without stopping an Exchange or an unresolved Root command. Root commands use their launchers, independent process groups and bounded waits. Database calls use pinned psycopg binary 3.3.6, independent autocommit connections, five-second deadlines and explicit read-only repeatable snapshots. Optional defaults come from `~/.arbol/roots/<root>/arbol.json`. The process clears inherited PG* overrides and reads only its configured Root database/password; no schema is changed here. The wire protocol, chat operations, attention/recovery and renderer are subsequent Backend Beats.

`arbol vigor [--refresh [<driver>/<subscription>]] [--text]` prints Subscriptions Vigor (SGM-1) for every Subscription of every Driver among the launchers, from the latest records in the current Root's database: one JSON document, or the Radar's lines with `--text`. It needs no running backend and contacts no vendor; `--refresh` fetches fresh reports through the Drivers' `subscriptions usage` first. `arbol vigor learn` learns the gate weights from the recorded report pairs and writes a proposed profile, `arbol vigor profiles` lists the profiles and the one in use, and `arbol vigor approve <version>` is the owner's approval (SYL-299). The Radar layer is `src/arbol_radar/`, with its checks in `tests/radar/` (SYL-295 to SYL-299).

For development use `bin/arbol --root <root> backend`. Private checks supply all of `--root-dir`, `--bin-dir`, `--settings-dir` and `--database`; `--root-dir` requires the bin and database options. Run them with `uv run --no-sync python -B -m unittest discover -s tests -p test_backend.py`. They require PostgreSQL 17 tools and start a socket-only temporary cluster using the last merged Root Contract layout; no retained Root, owner Keychain or vendor is reached. `arbol-builds build arbol --root <root>` packages its own pinned Python and hash-locked binary dependencies and runs the private Backend checks. The package carries the exact contract test input and a payload hash manifest. Installed changes come only from merged sources.

- The Product Specification, which states what Arbol does: `~/Artifacts/arbol_deprecated_v1/product-spec/` (start at `01-overview-and-scope.md`).
- The Arbol Design System, which states how Arbol looks and is operated: `sylvan-stack/arbol-design-system`.
- The Glossary: `~/Artifacts/arbol/GLOSSARY.md`.

## Sylvan Stack 2

| Repository | Package | Version | Artifact corpus | Artifact repository |
|---|---|---|---|---|
| `arbol` | `@sylvan-stack/arbol` | 2.0.0 | `~/Artifacts/arbol` | `sylvan-stack/arbol-artifacts` |
| `arbol-root` | `@sylvan-stack/arbol-root` | 1.0.0 | `~/Artifacts/arbol-root` | `sylvan-stack/arbol-root-artifacts` |
| `arbol-trunk` | `@sylvan-stack/arbol-trunk` | 1.0.0 | `~/Artifacts/arbol-trunk` | `sylvan-stack/arbol-trunk-artifacts` |
| `arbol-claude-driver` | `@sylvan-stack/arbol-claude-driver` | 1.0.0 | `~/Artifacts/arbol-claude-driver` | `sylvan-stack/arbol-claude-driver-artifacts` |
| `arbol-codex-driver` | `@sylvan-stack/arbol-codex-driver` | 1.0.0 | `~/Artifacts/arbol-codex-driver` | `sylvan-stack/arbol-codex-driver-artifacts` |
| `mycel` | `@sylvan-stack/mycel` | 2.0.0 | `~/Artifacts/mycel` | `sylvan-stack/mycel-artifacts` |
| `arbol-pi-driver` | `@sylvan-stack/arbol-pi-driver` | 1.0.0 | `~/Artifacts/arbol-pi-driver` | `sylvan-stack/arbol-pi-driver-artifacts` |
| `workspace-ledger` | `workspace-ledger` (planned) | 1.0.0 | `~/Artifacts/sylvan-stack/repos/workspace-ledger` | `sylvan-stack/workspace-ledger-artifacts` |
