"""Install, remove and report the agent-record hooks in the user's settings."""

from __future__ import annotations

import fcntl
import json
import os
import plistlib
import shlex
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from xml.parsers.expat import ExpatError

from .codex import CodexTrust, codex_command, login_command, login_environment
from .hooks import EVENTS
from .kimi_config import KimiHooks
from .settings import JsonHooks, SettingsError, SettingsFile

PROVIDERS = {
    "claude-code": ("claude", "CLAUDE_CONFIG_DIR", ".claude", "settings.json"),
    "codex": ("codex", "CODEX_HOME", ".codex", "hooks.json"),
    "kimi-code": ("kimi", "KIMI_CODE_HOME", ".kimi-code", "config.toml"),
}
KIMI_PLIST = Path("/Applications/Kimi Code.app/Contents/Info.plist")


def paths() -> dict[str, Path]:
    return {
        tool: Path(os.environ.get(variable) or Path.home() / default).expanduser().absolute() / filename
        for tool, (_, variable, default, filename) in PROVIDERS.items()
    }


def editor(tool: str, snapshot: SettingsFile) -> JsonHooks | KimiHooks:
    launcher = shlex.quote(str(Path.home() / ".local" / "bin" / "arbol-agents"))
    command = f"{launcher} hook {tool}"
    if tool == "kimi-code":
        return KimiHooks(snapshot, command, EVENTS[tool])
    return JsonHooks(snapshot, tool, command, EVENTS[tool])


@contextmanager
def settings_lock(*, exclusive: bool) -> Iterator[None]:
    # The same lock covers alternate settings homes without creating a settings file.
    descriptor = os.open(Path.home(), os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        os.close(descriptor)


def configure(*, remove: bool) -> dict[str, int]:
    with settings_lock(exclusive=True):
        locations = paths()
        editors = {tool: editor(tool, SettingsFile.read(path)) for tool, path in locations.items()}
        changes = {tool: existing.uninstall() if remove else existing.install() for tool, existing in editors.items()}
        config = SettingsFile.read(locations["codex"].with_name("config.toml"))
        trust = CodexTrust.read(config)

        if not remove:
            for tool, existing in editors.items():
                proposed = replace(existing.snapshot, contents=changes[tool].contents)
                if not editor(tool, proposed).installed():
                    raise SettingsError(f"An existing arbol-agents hook differs from its definition: {proposed.path}")

        codex_hooks = editors["codex"]
        assert isinstance(codex_hooks, JsonHooks)
        codex_change = changes["codex"]
        if remove:
            trust.uninstall(codex_hooks, codex_change)
        else:
            if codex_change.contents is not None:
                codex_hooks.snapshot.save(codex_change.contents)
            # If trust fails, a subsequent install can retry the existing hook entries.
            trust.install(codex_hooks)

        for tool in ("claude-code", "kimi-code"):
            change = changes[tool]
            if change.contents is not None:
                editors[tool].snapshot.save(change.contents)
        return {tool: change.count for tool, change in changes.items()}


def tool_version(tool: str) -> str | None:
    executable = PROVIDERS[tool][0]
    command = codex_command("--version") if tool == "codex" else login_command(executable, "--version")
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=True, timeout=5, env=login_environment(), cwd=Path.home(),
        )
        lines = result.stdout.strip().splitlines()
        if lines:
            return lines[-1]
    except (OSError, UnicodeError, subprocess.SubprocessError):
        pass
    if tool == "kimi-code":
        try:
            with KIMI_PLIST.open("rb") as source:
                version = plistlib.load(source).get("CFBundleShortVersionString")
            if isinstance(version, str):
                return f"{version} (desktop)"
        except (OSError, ValueError, ExpatError):
            pass
    return None


def status(*, as_json: bool) -> int:
    report: dict[str, dict[str, str | bool | None]] = {}
    errors: list[str] = []
    versions = {tool: tool_version(tool) for tool in PROVIDERS}
    with settings_lock(exclusive=False):
        for tool, path in paths().items():
            info: dict[str, str | bool | None] = {"installed": False, "version": versions[tool]}
            if tool == "codex":
                info["trusted"] = None
            try:
                existing = editor(tool, SettingsFile.read(path))
                info["installed"] = existing.installed()
                if isinstance(existing, JsonHooks) and tool == "codex":
                    codex_trust = CodexTrust.read(SettingsFile.read(path.with_name("config.toml")))
                    info["trusted"] = existing.installed() and codex_trust.trusted(existing)
            except (SettingsError, OSError) as error:
                errors.append(str(error))
            report[tool] = info

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for tool, info in report.items():
            installation = "installed" if info["installed"] else "incomplete"
            trust = ""
            if tool == "codex":
                trusted = info["trusted"]
                trust = ", trust unknown" if trusted is None else ", trusted" if trusted else ", untrusted"
            print(f"{tool}: {installation}{trust}, version {info['version'] or 'unknown'}")
    for diagnostic in errors:
        print(f"arbol-agents: {diagnostic}", file=sys.stderr)
    return int(bool(errors))
