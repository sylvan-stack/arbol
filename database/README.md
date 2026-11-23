# Arbol's database server

Arbol 2 keeps its chats in a PostgreSQL server of its own on this Mac, installed directly and not in a container (ARC-0, "The database server"; ARC-D64). This folder holds its installation and the probe that checks it (SYL-156). Both use only Python's standard library and run on the repository's Python:

```bash
uv run --no-sync python database/install_database_server.py
```

```bash
uv run --no-sync python database/probe_database_server.py [--restart]
```

| File | What it does |
|---|---|
| `install_database_server.py` | Installs the server, or brings it back to what it should be; can be run again. Prints a JSON report, never the password. Exit status 0, or 1 with `{"error": {"code", "message"}}` when it refused |
| `probe_database_server.py` | Checks the server and prints a JSON report; leaves nothing behind. Exit status 0 when every check passed, 1 when one failed |
| `database_server.py` | The places, names and helpers the scripts share |

What the installation makes, on PostgreSQL 17 of Homebrew (`/opt/homebrew/opt/postgresql@17/bin`):

| What | Where |
|---|---|
| The data folder, made by `initdb` (UTF-8, builtin locale `C.UTF-8`, data checksums), with the server's log in `log/`, one file per weekday | `~/.arbol/postgres/data` |
| The socket, for the installation alone, as the owner's account | `~/.arbol/postgres/socket` (mode 0700) |
| Copies of every file a run replaced | `~/.arbol/postgres/backups` |
| The launch agent `com.sylvan-stack.arbol.database`: `postgres` on the data folder, at login and again whenever it ends; its own output goes to `launchd.log` beside the data folder | `~/Library/LaunchAgents/com.sylvan-stack.arbol.database.plist` |
| The server's address, 127.0.0.1 at port 5433 for the role `arbol`, and the configured database name when present | `~/.arbol/database.json` |
| The password of the role `arbol`, made up by the installation and never shown | the Keychain item `com.sylvan-stack.arbol.database`, account `arbol` |

The role `arbol` may log in and create databases, and so remove the ones it made, and nothing more. Over 127.0.0.1 every role needs its password. Port 5432 is left to the container `arbol-postgres`, and Homebrew's own data folder `/opt/homebrew/var/postgresql@17` is not used. The layout-2 installer expects working state under the private `~/.arbol/` directory. Move an existing layout-1 installation under ARC-5 before running it. To stop the server, run `launchctl bootout gui/$(id -u)/com.sylvan-stack.arbol.database`. To start it again, run the installation.

The probe's checks:

| Check | What it proves |
|---|---|
| `programs` | A newly opened terminal (a clean login shell) finds `initdb`, `pg_ctl`, `createdb`, `psql` and `pg_dump`, each of PostgreSQL 17 |
| `throwaway-server` | `initdb` makes a server in a temporary folder that listens only on a socket in a short folder under `/tmp`, as the Root Contract's suite does (RCT-4); `createdb`, `psql` and `pg_dump` work on it; it is stopped and both folders are removed |
| `settings` | `~/.arbol/database.json` holds the role, host and port in the address and accepts the configured database name |
| `listening` | The `postgres` of the data folder, from `/opt/homebrew/opt/postgresql@17/bin`, is the only program on the port, listens on `127.0.0.1` at that port and on nothing else, answers there, and answers on no other address of the Mac's interfaces, IPv4 or IPv6 |
| `role` | The address with the password of the Keychain item connects as `arbol` to PostgreSQL 17; without a password it is refused; the role may log in and create databases, is not a superuser, may not create roles, replicate or bypass row security, and is a member of no role; it makes a database `arbol_probe_<random>` and removes it |
| `data-folder` | The data folder lies on the Mac's internal disk, not on removable media or a container's virtual disk; its size and number of files are read by walking it, as Arbol reads any folder, and the free space of its volume is reported |
| `launch-agent` | The launch agent runs `postgres` on the data folder, at login (`RunAtLoad`) and again whenever it ends (`KeepAlive`), is not disabled, and is the process launchd runs. With `--restart` the probe ends the server's process with PostgreSQL's fast shutdown and waits until launchd has started it again and it answers on 127.0.0.1, which stands in for a restart of the Mac |

## Database recovery before reopening

For every schema change, including an additive one, first stage the upgrade
release and identify the exact previous release and database. Verify the
Mercury archive before changing admission.

```bash
uv run --no-sync python database/archive_volume.py
```

Continue on `ready`. An `archive_unavailable` result means the required volume
or its Arbol root could not be verified. After preflight, stop admission,
drain and settle accepted Exchanges, pause listeners and pruning, and acquire
the exclusive maintenance handoff after all writers have stopped. Keep
admission closed through capture, isolated restore, migration, verification
and any recovery. The operator lock may end when a command exits; durable
exclusive admission must survive that exit.

Create a new recovery directory under `/Volumes/Mercury/Arbol/backups/`. Put
both release records, the snapshot and the restore receipt in that directory.
Use an explicit inventory of
the Builds actually selected by the release: Arbol, the applicable Root
manager, App, Trunks and Drivers. Reconfirm the inventory and effective
configuration against the installation or staged release before recording it.
Save the input JSON inventory in an owner-only operator directory outside Git.

```json
{
  "kind": "legacy",
  "builds": [
    {"directory": "/private/builds/arbol/BUILD"},
    {"directory": "/private/builds/arbol-root/BUILD"},
    {"directory": "/private/builds/arbol-app/BUILD"},
    {"directory": "/private/builds/arbol-trunk/trivial/BUILD"}
  ],
  "configuration": {
    "installation": "/private/effective-installation.json",
    "root": "/private/selected-root/root.json",
    "root-settings": "/private/effective-root-settings.json"
  },
  "inputs": {"workspace-preferences": "/private/workspace-preferences.json"},
  "rendererCheckout": "/path/to/arbol",
  "designCheckout": "/path/to/arbol-design-system"
}
```

Use `current` for a single-database release and omit the legacy Root record.
Add the selected Drivers, Browser, classifier and every applicable Trunk.
Supply `checkout` on a Build entry if the Git commit is available in a
relocated checkout. For a Trunk, point that field to its component directory,
such as `trunks/steady`, within the checkout. A layout-2 Mimo entry needs
`nativeCandidate` with the absolute path of the exact pinned native gate input.
Use the actual `root.json` for
`root`; it must identify the named database and the Root selected by the saved
Arbol and Root Builds. Record the effective settings, launch and renderer
references, and required private files. Save credential references and retain
the credentials in their existing stores. Do not put passwords, Keychain
exports, Driver tokens or runtime logs in the inventory.

```bash
uv run --no-sync python database/recovery_release.py \
  --inventory "$inventory" --output "$recovery/prior-release"
```

From a packaged Backend Build, use its `runtime/python/bin/python3.14 -B`
and its `database/recovery_release.py` with the same arguments.

Repeat for the staged release in a separate directory. Save the returned
`releaseSha256` values. The recorder verifies source and package evidence and
preserves the source archives, locked inputs, Build configuration and referenced
recovery files. It checks every committed gate result in the selected Build
record. For sealed packages it verifies the physical payload, its descriptor
and the exact Git tree. Pi and Mimo package metadata bind the interpreter to
its source pin. Browser capture verifies the signed host, its launcher and the
published source admission, then retains the pinned stock Electron and Native
qualification inputs. Node must be available for Browser capture. Unresolved
required inputs refuse publication. Legacy release
records retain the exact packaged Root Contract SQL as `root-contract.sql`
after checking it against `contractLayoutSha256`. Use the recorded signed App
bundle and its Build record for exact App recovery.

To reproduce another selected Build, use its `savedAt` directory and the
`sourceCommit`, `componentPath` and `evidence.gitSource` values from the verified
release record. Clone the retained bare Git repository into a private workspace,
check out the recorded commit, and compare its tree and archive before using
the recorded component directory with the ordinary Build command.

```bash
git clone --no-local --no-tags "$saved/source.git" "$checkout"
git -C "$checkout" switch --detach "$source_commit"
git -C "$checkout" rev-parse HEAD 'HEAD^{tree}'
git -C "$checkout" archive --format=tar --output="$comparison_tar" "$source_commit"
cmp "$comparison_tar" "$saved/source.tar"
```

Use the saved inputs and the recorded SDK, compiler and signer for Browser.
Restore its pinned prerequisite bytes to the physical paths named in the
committed recipe and its input manifests in the controlled recovery workspace.
Use normal independent source admission when the published Forester admission
has advanced. For Mimo, supply the retained pinned native input through
`ARBOL_MIMO_TEST_CANDIDATE` and qualify with the existing real account for its
live gate. Keep provider credentials in their original stores.

For a current installation, with the authoritative maintenance session still
held by the runtime, capture one named database:

```bash
PYTHONPATH=src uv run --no-sync python database/recovery.py \
  --database "$database" snapshot --session "$session" \
  --release "$recovery/prior-release" --output "$recovery/snapshot"
```

The installed connection uses the configured loopback address and the
Keychain credential. Qualification uses the same explicit alternate
connection as `migrate_schema.py`: `--socket`, `--port`, and `--user` before
the subcommand, with peer or trust authentication on the owner-only socket.
An isolated source role must be able to read its cluster identity.
Qualification supplies the isolated exclusive context to `recovery.main`;
the production current path takes it from the runtime. A session string on
its own does not establish a fence.

At the initial transition, positively fence **both** legacy writer sets,
settle pending files against their own databases and resolve live legacy
bookings. A new admission flag cannot fence a legacy writer. The installed
transition adapter calls the same `snapshot` entry point for each explicit
source, with `--legacy-release` set to that source's verified release digest,
the same legacy maintenance session, and separate release and snapshot
directories. It injects the context that confirms the legacy fence is still
held. The standalone command refuses legacy capture without that adapter.

Restore each archive in a freshly initialized, socket-only PostgreSQL cluster
outside the installation. The role for this command must be the isolated
cluster administrator. The database name matches the archive and must not
exist in that cluster:

```bash
uv run --no-sync python database/recovery.py \
  --database "$database" --socket "$restore_socket" --port "$restore_port" --user "$restore_admin" \
  restore --snapshot "$recovery/snapshot" --output "$recovery/restore-attempt"
```

Keep `snapshot.json`, `database.dump`, the exact release directory, and
`restore-attempt/restore.json` together on Mercury. The snapshot
records the release directory's path; retain that path while using the proof.
The restore provisions missing role names without passwords, preserves
database ownership and grants, and verifies the recovered ledger, table
shape, and representative chat and Vigor rows where present. A failed or
interrupted restore leaves an incomplete receipt once it has started to
write. Use a fresh isolated database and attempt directory for a retry.

For a schema upgrade, pass the original proof, both release digests and the
same exclusive session to the migration tool:

```bash
PYTHONPATH=src uv run --no-sync python database/migrate_schema.py \
  --database "$database" upgrade --target-revision "$revision" \
  --maintenance-session "$session" --prior-release "$prior_sha256" --upgrade-release "$staged_sha256" \
  --snapshot-dir "$recovery/snapshot" --restore-receipt "$recovery/restore-attempt/restore.json"
```

For the initial reset, verify both independent receipts against the two confirmed sources, their separate
release digests, and the same legacy session. Confirm the retained target
again before clearing it. One receipt cannot serve both sources. Keep both
archives and their original recovery inputs.

If a migration fails before reopening, keep all writers fenced. Retry from
the verified committed ledger prefix using the same original receipt,
session, releases, and target revision; or restore the previous release:

1. Run `python database/archive_volume.py` and require `ready` before invoking
   a live restore, including direct `pg_restore`. Verify the original archive, release inputs and isolated restore evidence
   again. If the isolated restore must be repeated, use fresh isolated state.
   Record which verified archive and installation target are being recovered.
2. With the durable fence held, stop the remaining clients of the affected
   database. Use the installed PostgreSQL tools and the explicit, verified
   maintenance connection to `postgres` on the intended installation to
   replace only the affected database with the complete archive.
   The restore command shape is
   `pg_restore --clean --if-exists --create --exit-on-error --no-password --dbname <maintenance-connection> <archive>`.
   Use the same credential boundary as capture; the connection argument
   contains no password. `--create` uses the name in the verified archive,
   and replacement assigns a new database OID. Keep the fence closed and
   explicitly verify the recovered identity before rebinding admission. If
   the replacement fails, the target is incomplete; keep it closed.
3. Restore the saved configuration and signed App. Select the remaining
   preserved Builds or rebuild them from the recorded Git commits, Build
   commands, locks, toolchain and external inputs. For legacy recovery, restore the
   matching settings and Builds for each affected source and keep new writers
   fenced.
4. Verify the recovered schema, representative data, configured target,
   compatible Builds, runtime protocols, and absence of outstanding work and
   stale clients. Use read-only checks on the installation and exercise writes
   on disposable state. Reopen explicitly to the verified release and record
   the admission boundary.

## Recovery after reopening

Repair forward by default. To use an older archive, verify Mercury with
`archive_volume.py` before entering maintenance again,
drain and settle accepted work, and establish exclusive admission. Preserve
the current database and affected persistent files first. Verify that every
write accepted since the older snapshot is captured and can be reapplied
consistently, including writes outside PostgreSQL that affect the recovered
release. Rehearse the replay on isolated state and compare the result with
the preserved current state before changing the installation. If any write
cannot be accounted for or replayed without loss, repair forward. Record the
write boundary, the evidence of replay and the release that reopens.

## Backend and session import compatibility

The backend can run on schema revision 4 with compatibility version 1.
Session import requires revision 5 for its fingerprint table. The import
command verifies that revision before reading or writing fingerprints.
