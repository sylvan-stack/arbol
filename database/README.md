# Arbol's database server

Arbol 2 keeps its chats in a PostgreSQL server of its own on this Mac, installed directly and not in a container (ARC-0, "The database server"; ARC-D64). This folder holds the probe that checks it (SYL-156). Both use only Python's standard library and run on the repository's Python:

```bash
uv run --no-sync python database/probe_database_server.py
```

| File | What it does |
|---|---|
| `probe_database_server.py` | Checks the server and prints a JSON report; leaves nothing behind. Exit status 0 when every check passed, 1 when one failed |
| `database_server.py` | The places, names and helpers the scripts share |

The probe's checks:

| Check | What it proves |
|---|---|
| `programs` | A newly opened terminal (a clean login shell) finds `initdb`, `pg_ctl`, `createdb`, `psql` and `pg_dump`, each of PostgreSQL 17 |
| `throwaway-server` | `initdb` makes a server in a temporary folder that listens only on a socket in a short folder under `/tmp`, as the Root Contract's suite does (RCT-4); `createdb`, `psql` and `pg_dump` work on it; it is stopped and both folders are removed |
