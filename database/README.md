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
| The data folder, made by `initdb` (UTF-8, builtin locale `C.UTF-8`, data checksums), with the server's log in `log/`, one file per weekday | `~/Library/Application Support/Arbol/database/data` |
| The socket, for the installation alone, as the owner's account | `~/Library/Application Support/Arbol/database/socket` (mode 0700) |
| Copies of every file a run replaced | `~/Library/Application Support/Arbol/database/backups` |
| The launch agent `com.sylvan-stack.arbol.database`: `postgres` on the data folder, at login and again whenever it ends; its own output goes to `launchd.log` beside the data folder | `~/Library/LaunchAgents/com.sylvan-stack.arbol.database.plist` |
| The server's address, 127.0.0.1 at port 5433 for the role `arbol`, and nothing else | `~/.arbol/database.json` |
| The password of the role `arbol`, made up by the installation and never shown | the Keychain item `com.sylvan-stack.arbol.database`, account `arbol` |

The role `arbol` may log in and create databases, and so remove the ones it made, and nothing more. Over 127.0.0.1 every role needs its password. Port 5432 is left to the container `arbol-postgres`, and Homebrew's own data folder `/opt/homebrew/var/postgresql@17` is not used. To stop the server: `launchctl bootout gui/$(id -u)/com.sylvan-stack.arbol.database`; to start it again, run the installation.

The probe's checks:

| Check | What it proves |
|---|---|
| `programs` | A newly opened terminal (a clean login shell) finds `initdb`, `pg_ctl`, `createdb`, `psql` and `pg_dump`, each of PostgreSQL 17 |
| `throwaway-server` | `initdb` makes a server in a temporary folder that listens only on a socket in a short folder under `/tmp`, as the Root Contract's suite does (RCT-4); `createdb`, `psql` and `pg_dump` work on it; it is stopped and both folders are removed |
| `settings` | `~/.arbol/database.json` holds the address and nothing else: a role, a host and a port, no password and no database |
| `listening` | The `postgres` of the data folder, from `/opt/homebrew/opt/postgresql@17/bin`, is the only program on the port, listens on `127.0.0.1` at that port and on nothing else, answers there, and answers on no other address of the Mac's interfaces, IPv4 or IPv6 |
| `role` | The address with the password of the Keychain item connects as `arbol` to PostgreSQL 17; without a password it is refused; the role may log in and create databases, is not a superuser, may not create roles, replicate or bypass row security, and is a member of no role; it makes a database `arbol_probe_<random>` and removes it |
| `data-folder` | The data folder lies on the Mac's internal disk, not on removable media or a container's virtual disk; its size and number of files are read by walking it, as Arbol reads any folder, and the free space of its volume is reported |
| `launch-agent` | The launch agent runs `postgres` on the data folder, at login (`RunAtLoad`) and again whenever it ends (`KeepAlive`), is not disabled, and is the process launchd runs. With `--restart` the probe ends the server's process with PostgreSQL's fast shutdown and waits until launchd has started it again and it answers on 127.0.0.1, which stands in for a restart of the Mac |
