# TEST-TIER-DISABLED-BEGIN scripts/roots_sql_drill.py
# """Explicit RTM-1 runtime drill on disposable databases of the installed server.
#
# All Root records, settings, fixture Build records and copied SQL are private.
# Only the exact randomly named databases proved absent here may be recreated or
# dropped. No owner Root or vendor request is used. --tool selects an installation.
# The fixture SQL is read as data from merged readonly/arbol-root, never imported.
# """
#
# import argparse
# import copy
# import hashlib
# import json
# import os
# import shutil
# import subprocess
# import sys
# import tempfile
# import uuid
# from dataclasses import replace
# from pathlib import Path
# from typing import Any
# from urllib.parse import quote, urlsplit
#
# ROOT = Path(__file__).resolve().parents[1]
# sys.path.insert(0, str(ROOT / "src"))
# from arbol_roots.database import Database, environment  # noqa: E402
# from arbol_roots.model import places  # noqa: E402
#
# TABLES = ["chats", "exchanges", "messages", "tool_calls", "runs"]
# CHAT = "10000000-0000-4000-8000-000000000001"
# ENDED = "20000000-0000-4000-8000-000000000001"
# OPEN = "20000000-0000-4000-8000-000000000002"
# SPECIAL = "Fictional 🌲 �\r\n\tC:\\fixture\\path  "
#
#
# def require(condition: object, message: str) -> None:
#     if not condition:
#         raise RuntimeError(message)
#
#
# def text(value: str) -> str:
#     return "convert_from(decode('" + value.encode().hex() + "','hex'),'UTF8')"
#
#
# def fixture(registry: Path, number: str, root: str, chat: bytes, own: bytes, migration: bytes | None) -> None:
#     folder = registry / "arbol-root" / number
#     folder.mkdir(parents=True)
#     (folder / "program").write_text("#!/bin/sh\nexit 0\n")
#     (folder / "program").chmod(0o755)
#     (folder / "build.json").write_text(json.dumps({
#         "component":"arbol-root", "build":number, "root":root, "packageVersion":"1.0.0", "status":"working",
#         "startedAt":"2026-10-26T09:00:00.000Z", "finishedAt":"2026-10-26T09:00:01.000Z", "entry":"program",
#         "source":{"repository":"/fictional/sql-drill","branch":"main","commit":"fixture","uncommittedChanges":False},
#         "checks":[{"name":"fixture","passed":True}]}))
#     layout = folder / "layout"
#     layout.mkdir()
#     content = {"chat-tables.sql":chat,"root-tables.sql":own}
#     if migration is not None:
#         content["migrate.sql"] = migration
#     for name, data in content.items():
#         (layout / name).write_bytes(data)
#     (folder / "package-manifest.json").write_text(json.dumps({
#         "component":"arbol-root", "build":number, "root":root,
#         "layout":{"root":root,"rootContract":1,"grewFrom":"sapling" if migration is not None else None},
#         "files":{"layout/"+name:hashlib.sha256(data).hexdigest() for name,data in content.items()}}))
#
#
# def drill(source: Path, tool: str | None = None) -> dict[str, Any]:
#     owner = Path.home()
#     keychain = owner / "Library/Keychains/login.keychain-db"
#     psql = shutil.which("psql")
#     require(psql is not None and keychain.is_file(), "The drill needs installed psql and the existing login Keychain.")
#     assert psql is not None
#     branch = subprocess.check_output(["git","branch","--show-current"],cwd=source,text=True).strip()
#     require(branch == "main" and not subprocess.check_output(["git","status","--porcelain"],cwd=source),
#             "The SQL source must be clean merged main.")
#     chat = (source / "contract/1/layout.sql").read_bytes()
#     own = (source / "roots/jensen/layout.sql").read_bytes()
#     migration = (source / "roots/jensen/migrate.sql").read_bytes()
#     source_commit = subprocess.check_output(["git","rev-parse","HEAD"],cwd=source,text=True).strip()
#     with tempfile.TemporaryDirectory(prefix="Arbol runtime SQL drill ") as temporary:
#         home = Path(temporary).resolve()
#         security = home / "security"
#         security.write_text(f"#!{sys.executable} -I\nimport os,sys\nos.execv('/usr/bin/security',"
#                             f"['security',*sys.argv[1:],{str(keychain)!r}])\n")
#         security.chmod(0o755)
#         spy = home / "psql"
#         spy.write_text(f"""#!{sys.executable} -I
# import json,os,sys
# from pathlib import Path
# # Remove only the startup additions of this Python test wrapper.
# for key in ('LC_CTYPE','__CF_USER_TEXT_ENCODING'):
#     os.environ.pop(key,None)
# keys = sorted(os.environ)
# assert set(keys) <= {{'HOME','PATH','LANG','PGPASSWORD'}}
# row = {{'keys':keys,'args':sys.argv[1:],'cwd':os.getcwd(),'mode':os.stat('.').st_mode & 511}}
# if '--file' in sys.argv and sys.argv[sys.argv.index('--file')+1].endswith('migrate.sql'):
#     row['initialFiles'] = os.listdir('.')
# with (Path(os.environ['HOME'])/'psql-calls.jsonl').open('a') as stream:
#     stream.write(json.dumps(row)+'\\n')
# os.execv({psql!r},[{psql!r},*sys.argv[1:]])
# """)
#         spy.chmod(0o755)
#         paths = replace(places({"--roots-dir":str(home / "roots"),"--settings-dir":str(home / "settings"),
#                                 "--registry-dir":str(home / "registry"),
#                                 "--database-config":str(owner / ".arbol/database.json"),
#                                 "--psql":psql,"--security":str(security)}),home=home)
#         client = Database(paths)
#         token = uuid.uuid4().hex[:20]
#         names = {"sapling":"arbol_sql_"+token+"_a '🌲", "second":"arbol_sql_"+token+"_b"}
#         attempted: list[str] = []
#
#         def exists(name: str) -> bool:
#             return client.run("SELECT count(*) FROM pg_database WHERE datname = "+text(name)) == "1"
#
#         def query(name: str, sql: str) -> Any:
#             address = urlsplit(client.address)._replace(path="/"+quote(name,safe="")).geturl()
#             result = subprocess.run([psql,"--no-psqlrc","--no-password","--set","ON_ERROR_STOP=1",
#                                      "--no-align","--tuples-only","--dbname",address,"--command",sql],
#                                     env=environment(paths,client.password),cwd=home,capture_output=True,text=True,
#                                     timeout=30,check=False)
#             require(result.returncode == 0, "Inspection of a disposable database failed.")
#             return json.loads(result.stdout) if result.stdout.strip().startswith(("[","{")) else result.stdout.strip()
#
#         def rows(name: str, extra: bool = False) -> dict[str, Any]:
#             return {table:query(name,"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') "
#                                "FROM "+table+" t") for table in [*TABLES, *(["migrated_chats"] if extra else [])]}
#
#         def normalized(values: dict[str, Any]) -> dict[str, Any]:
#             result = copy.deepcopy(values)
#             for row in result.get("migrated_chats",[]):
#                 row["migrated_at"] = "<snapshot>"
#             for row in result["exchanges"]:
#                 if row["id"] == OPEN:
#                     row["ended_at"] = "<snapshot>"
#             return result
#
#         prefix = [tool] if tool else [sys.executable,"-I","-B",str(ROOT / "bin/roots_entry.py")]
#
#         def command(*args: str, code: int = 0) -> Any:
#             result = subprocess.run([*prefix,*args,"--roots-dir",str(paths.roots),"--settings-dir",str(paths.settings),
#                                      "--registry-dir",str(paths.registry),"--database-config",str(paths.database_config),
#                                      "--psql",str(spy),"--security",str(security)],
#                                     env={**environment(paths),"PGHOST":"outside.invalid","PGSERVICE":"outside",
#                                          "UNRELATED":"must not reach psql"},cwd=home,capture_output=True,timeout=180)
#             require(result.returncode == code, "Private Root command failed: "+os.fsdecode(result.stdout))
#             return json.loads(result.stdout)
#
#         for name in names.values():
#             require(not exists(name), "A randomly named disposable database already exists; refusing to touch it.")
#         fixture(paths.registry,"1","sapling",chat,(source / "roots/sapling/layout.sql").read_bytes(),None)
#         fixture(paths.registry,"2","second",chat,own,migration)
#         # Readiness only checks this private executable/contract record; no Trunk is run.
#         trivial = paths.registry / "arbol-trunk/trivial/1"
#         trivial.mkdir(parents=True)
#         record = json.loads((paths.registry / "arbol-root/1/build.json").read_text())
#         record.update(component="arbol-trunk/trivial",rootContracts=[1])
#         record.pop("root")
#         (trivial / "build.json").write_text(json.dumps(record))
#         shutil.copy2(paths.registry / "arbol-root/1/program",trivial / "program")
#         try:
#             for root in ["sapling","second"]:
#                 attempted.append(names[root])
#                 args = ["create",root,"--name","Fictional "+root,"--database-name",names[root]]
#                 if root == "second":
#                     args += ["--from","sapling"]
#                 command(*args)
#                 if root == "sapling":
#                     command("migrate",root)
#                     require(all(not value for value in rows(names[root]).values()), "The new chat tables are not empty.")
#                     sql = f"""
# INSERT INTO chats VALUES ('{CHAT}',{text(SPECIAL)},'2026-10-15T09:00:00Z');
# INSERT INTO exchanges (id,chat_id,number,state,trunk,build,route,working_folder,accepted_at,ended_at) VALUES
# ('{ENDED}','{CHAT}',1,'completed','trivial','3','{{}}','/fictional','2026-10-15T09:00:00Z','2026-10-15T09:01:00Z'),
# ('{OPEN}','{CHAT}',2,'open','trivial','3','{{}}','/fictional','2026-10-15T09:02:00Z',NULL);
# INSERT INTO messages VALUES ('{ENDED}',0,'user',{text(SPECIAL)}),('{ENDED}',1,'assistant',{text(SPECIAL)}),
# ('{OPEN}',0,'user',{text(SPECIAL)});
# INSERT INTO tool_calls (exchange_id,position,run_id,call_id,name,input,ok,result)
# VALUES ('{ENDED}',2,'fictional','call1','Read','{{"nested":[1,true,null]}}',true,'{{"kept":true}}');
# INSERT INTO runs (exchange_id,run_id,outcome,usage,ended_at)
# VALUES ('{ENDED}','fictional','completed','{{"inputTokens":12}}','2026-10-15T09:01:00Z');
# """
#                     query(names[root],sql)
#                     command("ready",root)
#             original = rows(names["sapling"])
#             source_header = (paths.roots / "sapling/root.json").read_bytes()
#             before_calls = (home / "psql-calls.jsonl").read_bytes()
#             require(command("migrate","sapling",code=1)["error"]["code"] == "invalid_input",
#                     "Working Root migration was not refused.")
#             require((home / "psql-calls.jsonl").read_bytes() == before_calls, "A refused migration ran psql.")
#             command("migrate","second")
#             first = rows(names["second"],True)
#             expected = copy.deepcopy(original)
#             for row in expected["exchanges"]:
#                 if row["id"] == OPEN:
#                     row.update(state="interrupted",ended_at=first["migrated_chats"][0]["migrated_at"])
#             require(all(first[table] == expected[table] for table in TABLES), "Migration changed exact rows/text/JSON.")
#             provenance = first["migrated_chats"]
#             require(len(provenance) == 1 and provenance[0]["from_root"] == "sapling"
#                     and provenance[0]["from_chat"] == CHAT and provenance[0]["ended_through"] == 1,
#                     "Migration provenance differs.")
#             query(names["second"],"CREATE TABLE must_disappear(note text); INSERT INTO must_disappear VALUES ('old');")
#             command("migrate","second")
#             require(normalized(rows(names["second"],True)) == normalized(first), "Fresh repeated migration differs.")
#             require(query(names["second"],"SELECT coalesce(to_json(to_regclass('must_disappear')),'null'::json)") == "null",
#                     "Migration did not recreate an empty database.")
#             start, commit, end = migration.rpartition(b"COMMIT;")
#             require(bool(commit), "The prescribed migration lacks its final destination COMMIT.")
#             fixture(paths.registry,"3","second",chat,own,start+b"\nSELECT * FROM planted_missing_table;\n"+commit+end)
#             failed = command("migrate","second",code=1)
#             require("migrate.sql:" in failed["error"]["message"] and "planted_missing_table" in failed["error"]["message"],
#                     "SQL failure did not identify its file/line/error.")
#             require(command("show","second")["status"] == "preparing", "Failed migration changed Root status.")
#             require(all(not value for value in rows(names["second"],True).values()), "Failed migration did not roll back rows.")
#             fixture(paths.registry,"4","second",chat,own,migration)
#             command("migrate","second")
#             command("ready","second")
#             before_layout = rows(names["second"],True)
#             target_header = (paths.roots / "second/root.json").read_bytes()
#             extra = (b"\nCREATE TABLE IF NOT EXISTS fixture_notes(id integer PRIMARY KEY);\n"
#                      b"COMMENT ON TABLE fixture_notes IS 'Private additive drill';\n"
#                      b"COMMENT ON COLUMN fixture_notes.id IS 'Private identity';\n")
#             fixture(paths.registry,"5","second",chat,own+extra,migration)
#             require(command("layout","second")["rootBuild"] == "5", "Layout did not use the newer Root Build.")
#             command("layout","second")
#             require(rows(names["second"],True) == before_layout
#                     and query(names["second"],"SELECT to_json(count(*)) FROM fixture_notes") == "0",
#                     "Additive/repeated layout changed earlier rows or failed to add its table.")
#             require(rows(names["sapling"]) == original and (paths.roots / "sapling/root.json").read_bytes() == source_header
#                     and (paths.roots / "second/root.json").read_bytes() == target_header, "Source or Root metadata changed.")
#             calls = [json.loads(line) for line in (home / "psql-calls.jsonl").read_text().splitlines()]
#             migrations = [row for row in calls if "initialFiles" in row]
#             require(migrations and all(row["mode"] == 0o700 and not row["initialFiles"]
#                                        and not Path(row["cwd"]).exists() for row in migrations),
#                     "Migration copy directories were not private, initially empty and removed.")
#             require(all(set(row["keys"]) <= {"HOME","PATH","LANG","PGPASSWORD"} for row in calls),
#                     "An inherited environment variable reached psql.")
#         finally:
#             failures = []
#             for name in reversed(attempted):
#                 try:
#                     client.drop(name)
#                     require(not exists(name), "Disposable database remains: "+name)
#                 except Exception:
#                     failures.append(name)
#             require(not failures, "Disposable database cleanup needs retry for these exact names: "+repr(failures))
#     return {"check":"roots.runtime-sql", "passed":True, "tool":tool or "source", "sqlSourceCommit":source_commit,
#             "fixtureBuilds":True, "exactRows":True, "sourceUnchanged":True, "repeatable":True,
#             "workingRefused":True, "additiveLayout":True, "failureRollsBack":True,
#             "privateCopiesRemoved":True, "minimalEnvironment":True, "quotedUnicodeDatabase":True,
#             "databasesRemoved":2, "ownerRootsChanged":False, "vendorRequests":0}
#
#
# def main() -> int:
#     parser = argparse.ArgumentParser(description=__doc__)
#     parser.add_argument("--tool")
#     parser.add_argument("--root-source",type=Path,default=Path.home() / "repos/sylvan-stack/readonly/arbol-root")
#     args = parser.parse_args()
#     try:
#         print(json.dumps(drill(args.root_source,args.tool)))
#         return 0
#     except Exception as error:
#         print(json.dumps({"passed":False,"error":str(error)}))
#         return 1
#
#
# if __name__ == "__main__":
#     sys.exit(main())
# TEST-TIER-DISABLED-END scripts/roots_sql_drill.py
raise RuntimeError('Tests are commented under the tier policy; see TESTS.md. Restore only in an explicitly requested testing task.')
