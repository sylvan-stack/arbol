"""Manage Codex hook trust through the app-server protocol (AGR-D12)."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import time
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .model import object_value, optional_text, text_value
from .settings import HookEdit, JsonHooks, SettingsError, SettingsFile

APP_CLI = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
RPC_TIMEOUT = 15


def login_environment() -> dict[str, str]:
    environment = {key: os.environ[key] for key in ("HOME", "USER", "LOGNAME") if key in os.environ}
    return {**environment, "TERM": "xterm-256color"}


def login_command(*args: str) -> list[str]:
    return ["/bin/zsh", "-l", "-i", "-c", 'exec "$@"', "arbol-agents", *args]


def codex_command(*args: str, home: Path | None = None) -> list[str]:
    return [
        "/bin/zsh", "-l", "-i", "-c",
        'if [[ -n "$1" ]]; then export CODEX_HOME="$1"; fi; '
        'fallback=$2; shift 2; if command -v codex >/dev/null; then exec codex "$@"; fi; exec "$fallback" "$@"',
        "arbol-agents", "" if home is None else str(home), APP_CLI, *args,
    ]


def objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Expected a list of objects.")
    return [object_value(item) for item in value]


@dataclass(frozen=True)
class Hook:
    event: str
    key: str
    hash: str
    command: str | None
    trusted: bool
    enabled: bool


class AppServer:
    def __init__(self, output: IO[bytes], input_stream: IO[bytes], selector: selectors.BaseSelector) -> None:
        self.output = output
        self.input = input_stream
        self.selector = selector
        self.pending = bytearray()
        self.request_id = 0

    def send(self, message: dict[str, object]) -> None:
        self.input.write(json.dumps(message).encode("utf-8") + b"\n")
        self.input.flush()

    def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self.request_id += 1
        self.send({"id": self.request_id, "method": method, "params": params})
        deadline = time.monotonic() + RPC_TIMEOUT
        while time.monotonic() < deadline:
            newline = self.pending.find(b"\n")
            if newline < 0:
                if not self.selector.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(self.output.fileno(), 65536)
                if not chunk:
                    raise SettingsError(f"Codex app-server exited during {method}.")
                self.pending.extend(chunk)
                continue
            line = self.pending[:newline]
            del self.pending[:newline + 1]
            try:
                message = object_value(json.loads(line))
            except ValueError:
                # An interactive login shell can print startup messages.
                continue
            if message.get("id") != self.request_id:
                continue
            if "error" in message:
                raise SettingsError(f"Codex app-server rejected {method}.")
            return object_value(message.get("result"))
        raise SettingsError(f"Codex app-server timed out during {method}.")

    def hooks(self, path: Path) -> list[Hook]:
        result = self.call("hooks/list", {"cwds": [str(Path.home())]})
        listed = objects(result.get("data"))
        if len(listed) != 1:
            raise SettingsError("Codex did not return one hook listing.")
        path = path.resolve()
        listing = listed[0]
        if any(Path(text_value(error, "path")).resolve() == path for error in objects(listing.get("errors", []))):
            raise SettingsError(f"Codex could not load hooks from {path}.")
        rows = [
            row for row in objects(listing.get("hooks"))
            if Path(text_value(row, "sourcePath")).resolve() == path
        ]
        rows.sort(key=lambda row: int(str(row["displayOrder"])))
        return [
            Hook(
                event=text_value(row, "eventName"),
                key=text_value(row, "key"),
                hash=text_value(row, "currentHash"),
                command=optional_text(row, "command"),
                trusted=text_value(row, "trustStatus") == "trusted",
                enabled=row.get("enabled") is True,
            )
            for row in rows
        ]

    def write_trust(
        self, snapshot: SettingsFile, values: dict[str, object], *, merge: str,
    ) -> None:
        if not values:
            return
        response = self.call("config/read", {"includeLayers": True})
        layers = objects(response.get("layers"))
        version = None
        for layer in layers:
            name = object_value(layer.get("name"))
            if name.get("type") == "user" and Path(text_value(name, "file")).resolve() == snapshot.path.resolve():
                version = text_value(layer, "version")
                break
        if version is None and snapshot.contents is not None:
            raise SettingsError(f"Codex could not identify the user config version: {snapshot.path}")
        edits = []
        for key, value in values.items():
            # The protocol splits on dots except inside quotes and unescapes backslash and quote.
            quoted = key.replace("\\", "\\\\").replace('"', '\\"')
            edits.append({"keyPath": f'hooks.state."{quoted}"', "value": value, "mergeStrategy": merge})
        snapshot.backup()
        self.call("config/batchWrite", {
            "edits": edits,
            "filePath": str(snapshot.path),
            "expectedVersion": version,
        })


@contextmanager
def app_server(config: SettingsFile) -> Iterator[AppServer]:
    try:
        with subprocess.Popen(
            codex_command("app-server", home=config.path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=login_environment(),
            cwd=Path.home(),
        ) as process, selectors.DefaultSelector() as selector:
            assert process.stdout is not None and process.stdin is not None
            selector.register(process.stdout, selectors.EVENT_READ)
            server = AppServer(process.stdout, process.stdin, selector)
            try:
                server.call("initialize", {
                    "clientInfo": {"name": "arbol-agents", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                })
                server.send({"method": "initialized"})
                yield server
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
    except SettingsError:
        raise
    except (OSError, ValueError, KeyError) as error:
        raise SettingsError(f"Could not communicate with Codex app-server for {config.path}.") from error


@dataclass(frozen=True)
class CodexTrust:
    config: SettingsFile
    state: dict[str, object]

    @classmethod
    def read(cls, config: SettingsFile) -> CodexTrust:
        try:
            document = tomllib.loads((config.contents or b"").decode("utf-8"))
            hooks = object_value(document.get("hooks", {}))
            return cls(config, object_value(hooks.get("state", {})))
        except (ValueError, RecursionError):
            raise SettingsError(f"Invalid Codex TOML settings: {config.path}") from None

    def installed_hooks(self, server: AppServer, hooks: JsonHooks) -> list[Hook]:
        owned = [hook for hook in server.hooks(hooks.snapshot.path) if hook.command == hooks.command]
        events = {hook.event[:1].upper() + hook.event[1:] for hook in owned}
        if not events.issuperset(hooks.events):
            raise SettingsError(f"Codex did not discover every installed hook in {hooks.snapshot.path}.")
        return owned

    def install(self, hooks: JsonHooks) -> None:
        with app_server(self.config) as server:
            owned = self.installed_hooks(server, hooks)
            server.write_trust(self.config, {
                hook.key: {"trusted_hash": hook.hash} for hook in owned if not hook.trusted
            }, merge="upsert")

    def trusted(self, hooks: JsonHooks) -> bool:
        with app_server(self.config) as server:
            return all(hook.trusted and hook.enabled for hook in self.installed_hooks(server, hooks))

    def uninstall(self, hooks: JsonHooks, edit: HookEdit) -> None:
        if not edit.count or edit.contents is None:
            return
        with app_server(self.config) as server:
            before = server.hooks(hooks.snapshot.path)
        owned = [hook for hook in before if hook.command == hooks.command]
        if len(owned) != edit.count:
            raise SettingsError(f"Codex did not discover the hooks to remove in {hooks.snapshot.path}.")
        foreign = [hook for hook in before if hook.command != hooks.command]
        hooks.snapshot.save(edit.contents)
        try:
            with app_server(self.config) as server:
                after = server.hooks(hooks.snapshot.path)
                changes: dict[str, object] = {hook.key: None for hook in owned if hook.key in self.state}
                moved: dict[str, object] = {}
                if len(foreign) != len(after):
                    raise SettingsError("Codex's other hooks changed during uninstall.")
                for previous, current in zip(foreign, after, strict=True):
                    if (previous.event, previous.hash) != (current.event, current.hash):
                        raise SettingsError("Codex's other hooks changed during uninstall.")
                    if previous.key == current.key:
                        continue
                    if previous.key in self.state:
                        changes[previous.key] = None
                    if previous.key in self.state or current.key in self.state:
                        moved[current.key] = self.state.get(previous.key)
                server.write_trust(self.config, {**changes, **moved}, merge="replace")
        except (SettingsError, OSError):
            # Roll back only while both files still match what this operation observed.
            if SettingsFile.read(self.config.path) == self.config:
                hooks.snapshot.restore(edit.contents)
            raise
