"""SIM-17 disposable PostgreSQL, Bridge and Elma qualification for a numbered Backend Build."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ORDINARY, IMPORTED, RACE = (str(UUID(int=value)) for value in (10, 11, 12))
ORDINARY_EXCHANGE, IMPORTED_EXCHANGE, RACE_EXCHANGE = (str(UUID(int=value)) for value in (20, 21, 22))
DRAFT = "Fictional ordinary Draft preserved across archive playback."
PROVENANCE = {"tool": "codex", "kind": "owner"}
SCHEMA = {"revision": 3, "compatibilityVersion": 1}


def require(condition: object, observation: str) -> None:
    if not condition:
        raise RuntimeError(observation)


def checked_package(package: Path) -> tuple[str, str]:
    temporary = (Path.home() / "Builds/sylvan-stack/arbol").resolve(strict=True)
    relative = package.relative_to(temporary)
    require(len(relative.parts) == 4 and relative.parts[0].startswith("forester-")
            and relative.parts[1:3] == ("registry", "arbol"), "Use a private Forester Backend Build.")
    record = json.loads((package / "build.json").read_bytes())
    require(record["status"] == "working" and record["component"] == "arbol"
            and record["build"] == package.name and record["installationLayout"] == 2
            and not record["source"]["uncommittedChanges"]
            and record["checks"] == [{"name": "unit", "passed": True}, {"name": "roots-unit", "passed": True}],
            "The pinned Backend gate is incomplete.")
    require(Path(sys.executable).resolve() == (package / "runtime/python/bin/python3.14").resolve(),
            "Use the packaged Backend interpreter.")
    return str(record["build"]), str(record["source"]["commit"])


def seed(fixture: Any, folder: Path) -> None:
    # All IDs, prompts, outcomes and tool rows are fictional. Fixture SQL is kept
    # inside the private cluster supplied by the packaged qualification support.
    fixture.cluster.sql(f"""
        BEGIN;
        SET LOCAL arbol.importing = 'on';
        INSERT INTO chats (id, title, created_at) VALUES
            ('{ORDINARY}', 'Fictional ordinary chat', '2026-01-01 00:00Z'),
            ('{IMPORTED}', 'Fictional archive example', '2026-01-02 00:00Z'),
            ('{RACE}', 'Fictional race target', '2026-01-03 00:00Z');
        INSERT INTO chat_imports
            (chat_id, tool, native_id, kind, origin, manifest, first_imported, last_imported)
        VALUES ('{IMPORTED}', 'codex', 'fixture-import', 'owner', '{{}}', repeat('1', 64), now(), now()),
            ('{RACE}', 'codex', 'fixture-race', 'owner', '{{}}', repeat('2', 64), now(), now());
        INSERT INTO chat_marks (chat_id, ongoing, archived_at, updated_at) VALUES
            ('{IMPORTED}', false, '2026-01-02 00:00Z', '2026-01-02 00:00Z'),
            ('{RACE}', false, '2026-01-03 00:00Z', '2026-01-03 00:00Z');
        INSERT INTO exchanges
            (id, chat_id, number, state, error, trunk, build, route, working_folder, accepted_at, ended_at)
        VALUES
            ('{ORDINARY_EXCHANGE}', '{ORDINARY}', 1, 'completed', NULL, 'trivial', '1', '{{}}',
             '{folder}', '2026-01-01 00:00Z', '2026-01-01 00:01Z'),
            ('{IMPORTED_EXCHANGE}', '{IMPORTED}', 1, 'failed',
             '{{"code":"imported_failure","message":"Fictional recorded failure."}}', 'imported', '0',
             '{{"driver":"codex","model":"fictional-saved-model","effort":"high"}}',
             '{folder}', '2026-01-02 00:00Z', '2026-01-02 00:01Z'),
            ('{RACE_EXCHANGE}', '{RACE}', 1, 'completed', NULL, 'imported', '0', '{{"driver":"codex"}}',
             '{folder}', '2026-01-03 00:00Z', '2026-01-03 00:01Z');
        INSERT INTO exchange_imports (exchange_id, chat_id, turn_key, trigger) VALUES
            ('{IMPORTED_EXCHANGE}', '{IMPORTED}', 'first', 'typed'),
            ('{RACE_EXCHANGE}', '{RACE}', 'first', 'typed');
        INSERT INTO messages (exchange_id, position, role, text) VALUES
            ('{ORDINARY_EXCHANGE}', 0, 'user', 'Fictional ordinary prompt'),
            ('{IMPORTED_EXCHANGE}', 0, 'user', 'Fictional saved prompt'),
            ('{RACE_EXCHANGE}', 0, 'user', 'Fictional race prompt'),
            ('{IMPORTED_EXCHANGE}', 3, 'assistant', 'Fictional saved response');
        INSERT INTO runs (exchange_id, run_id, outcome, usage, error, ended_at) VALUES
            ('{IMPORTED_EXCHANGE}', '{IMPORTED_EXCHANGE}.import', 'failed', '{{}}',
             '{{"code":"imported_failure","message":"Fictional recorded failure."}}', '2026-01-02 00:01Z');
        INSERT INTO tool_calls (exchange_id, position, run_id, call_id, parent_call_id, name, input, ok, result)
        VALUES ('{IMPORTED_EXCHANGE}', 1, '{IMPORTED_EXCHANGE}.import', 'parent', NULL,
                'fixture-parent', '{{}}', true, '{{"output":"Fictional tool result"}}'),
               ('{IMPORTED_EXCHANGE}', 2, '{IMPORTED_EXCHANGE}.import', 'actor/child', 'parent',
                'fixture-child', '{{}}', true, '{{"output":"Fictional child result"}}');
        COMMIT;
    """.encode())


async def inspect_bridge(bridge: Any, build: str) -> None:
    hello = next(event for event in bridge.events if event["type"] == "hello")
    require(hello["build"] == build and hello["installation"]["schema"] == SCHEMA
            and hello["installation"]["maintenance"] == "normal", "The Bridge opened the wrong installation.")
    first = (await bridge.call("chats.page", {"archived": True, "limit": 1}))["result"]["chats"]
    require(len(first) == 1 and first[0]["chat"] == RACE and first[0]["archived"] is True
            and first[0]["imported"] == PROVENANCE, "The first archive page omitted its provenance.")
    cursor = {key: first[0][key] for key in ("activityAt", "chat")}
    second = (await bridge.call("chats.page", {"archived": True, "before": cursor, "limit": 1}))["result"]["chats"]
    require(len(second) == 1 and second[0]["chat"] == IMPORTED and second[0]["imported"] == PROVENANCE,
            "The archive cursor did not continue in descending activity order.")
    latest = (await bridge.call("chats.page", {}))["result"]["chats"]
    require([row["chat"] for row in latest] == [ORDINARY] and "imported" not in latest[0],
            "The default page did not isolate the ordinary active record.")
    request = {"type": "subscribe", "id": "sim17-chat", "topic": "chat", "params": {"chat": IMPORTED}}
    bridge.writer.write((json.dumps(request) + "\n").encode())
    await bridge.writer.drain()
    snapshot = await bridge.until(lambda: next((row["event"] for row in bridge.events
                                                if row.get("id") == "sim17-chat" and row.get("type") == "event"), None))
    require(snapshot["kind"] == "snapshot" and snapshot["chat"]["imported"] == PROVENANCE,
            "The saved imported Chat Session snapshot has no provenance.")
    items = snapshot["exchanges"][0]["items"]
    calls = [item for item in items if item["kind"] == "tool"]
    require([item["name"] for item in calls] == ["fixture-parent"], "The nested tool escaped the top-level projection.")
    refusals = (
        ("chat.send", {"chat": IMPORTED, "exchange": str(uuid4())}),
        ("draft.save", {"chat": IMPORTED, "text": "Fictional refused draft", "baseRevision": None}),
    )
    for method, params in refusals:
        reply = await bridge.call(method, params)
        require(reply.get("error", {}).get("code") == "imported_chat", f"{method} did not return imported_chat.")
    result = (await bridge.call("draft.save", {"chat": ORDINARY, "text": DRAFT, "baseRevision": None}))["result"]
    require(type(result.get("revision")) is int, "The ordinary Draft could not be saved.")
    ordinary = await bridge.call("draft.get", {"chat": ORDINARY})
    require(ordinary["result"]["text"] == DRAFT, "The ordinary Draft could not be read back.")


def trigger_refusal(fixture: Any, psycopg: Any) -> None:
    with psycopg.connect(fixture.cluster.address, autocommit=True) as connection:
        try:
            connection.execute("""
                INSERT INTO exchanges (id, chat_id, number, state, trunk, build, route,
                                       working_folder, accepted_at, ended_at)
                VALUES (%s, %s, 2, 'completed', 'trivial', '1', '{}', '/', now(), now())
            """, (str(uuid4()), IMPORTED))
        except psycopg.errors.RaiseException as error:
            require((error.sqlstate, error.diag.message_primary) == ("P0001", "imported_chat"),
                    "The direct SQL insert gave an unexpected refusal.")
        else:
            raise RuntimeError("The direct SQL insert bypassed the import trigger.")


async def journey(package: Path, build: str, node: Path | None, playwright: Path | None) -> dict[str, Any]:
    sys.path[:0] = [str(package / entry) for entry in ("runtime/site-packages", "src", "tests", "")]
    import psycopg
    from backend.support import SingleInstallation

    from tools.backend_journeys import Bridge
    from tools.bridge_relay import Relay
    from tools.elma_bundle import verify

    manifest = verify(package / "ui/elma", build)
    fixture = SingleInstallation(package)
    try:
        await asyncio.to_thread(fixture.open_admission)
        require(fixture.schema == SCHEMA and fixture.cluster.base in fixture.cluster.socket.parents
                and fixture.cluster.base in fixture.endpoint.parents, "The private schema is not 3/1.")
        folder = fixture.home / "repos/sylvan-stack"
        folder.mkdir(mode=0o700, parents=True)
        seed(fixture, folder)
        trigger_refusal(fixture, psycopg)
        with (fixture.cluster.base / "backend.log").open("wb") as log:
            backend = subprocess.Popen(
                [str(package / "bin/arbol"), "backend", *fixture.options()],
                env=fixture.env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                async with asyncio.timeout(12):
                    while not fixture.endpoint.is_socket():
                        if backend.poll() is not None:
                            raise RuntimeError("The private Backend exited during startup.")
                        await asyncio.sleep(0.05)
                bridge = await Bridge.connect(fixture.endpoint)
                try:
                    await inspect_bridge(bridge, build)
                    require(fixture.cluster.sql(
                        f"SELECT count(*) FROM drafts WHERE chat_id IN ('{IMPORTED}', '{RACE}')".encode()
                    ).strip() == b"0", "A Draft was written to an imported Chat Session.")
                    if node and playwright:
                        renderer = await browser_journey(package, fixture, bridge, Relay, node, playwright)
                    else:
                        renderer = None
                finally:
                    await bridge.close()
            finally:
                if backend.poll() is None:
                    backend.terminate()
                    try:
                        backend.wait(timeout=7)
                    except subprocess.TimeoutExpired:
                        backend.kill()
                        backend.wait(timeout=5)
        return {"schema": SCHEMA, "rendererBuild": manifest["build"], "bridge": "passed", "browser": renderer}
    finally:
        fixture.close()


async def browser_journey(
    package: Path, fixture: Any, bridge: Any, relay_type: Any, node: Path, playwright: Path
) -> dict[str, Any]:
    relay = relay_type(package / "ui/elma", fixture.endpoint)
    await relay.start()
    script = Path(__file__).resolve().with_suffix(".mjs")
    process = await asyncio.create_subprocess_exec(
        str(node), str(script), str(playwright), f"http://{relay.host}/?token={relay.token}",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None,
        env={**fixture.env, "PLAYWRIGHT_BROWSERS_PATH": str(Path.home() / "Library/Caches/ms-playwright")},
    )
    assert process.stdout and process.stdin
    try:
        async with asyncio.timeout(80):
            action = (await process.stdout.readline()).strip()
            require(action == b"held archive reply", "The browser did not hold the race target's first archive page.")
            mark = await bridge.call("chat.mark", {"chat": RACE, "archived": False})
            require("result" in mark and "archivedAt" not in mark["result"], "The cross-window unarchive failed.")
            process.stdin.write(b"unarchived\n")
            await process.stdin.drain()
            output = await process.stdout.read()
            require(await process.wait() == 0, "The packaged renderer qualification failed.")
            result: object = json.loads(output)
            if not isinstance(result, dict) or result.get("race") != "passed":
                raise RuntimeError("The renderer reported no complete archive-race result.")
            return result
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            await process.wait()
        await relay.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--playwright", type=Path)
    args = parser.parse_args()
    require((args.node is None) == (args.playwright is None), "Specify both browser dependencies or neither.")
    package = args.package.resolve(strict=True)
    build, source = checked_package(package)
    result = asyncio.run(journey(package, build, args.node, args.playwright))
    print(json.dumps({"build": build, "source": source, **result}, sort_keys=True))


if __name__ == "__main__":
    main()
