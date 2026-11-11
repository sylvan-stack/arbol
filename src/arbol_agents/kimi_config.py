"""Edit Kimi Code's root hooks array without rewriting the rest of its TOML."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable

from .model import object_value
from .settings import HookEdit, SettingsError, SettingsFile

TABLE_LINE = re.compile(r"^[ \t]*\[[^\r\n]*", re.MULTILINE)
INLINE_HOOKS = re.compile(r"""^[ \t]*(?:hooks|"hooks"|'hooks')[ \t]*=[ \t]*(?=\[)""", re.MULTILINE)


def hook_rows(document: dict[str, object]) -> list[dict[str, object]]:
    rows = document.get("hooks", [])
    if not isinstance(rows, list):
        raise ValueError("Expected an array of hook tables.")
    return [object_value(row) for row in rows]


def table_spans(text: str) -> list[tuple[int, int]]:
    headers: list[tuple[int, bool]] = []
    for match in TABLE_LINE.finditer(text):
        try:
            header = tomllib.loads(match[0])
            tomllib.loads(text[:match.start()])
        except tomllib.TOMLDecodeError:
            # A header-shaped line inside a multiline value is part of that value.
            continue
        headers.append((match.start(), header == {"hooks": [{}]}))
    headers.append((len(text), False))
    return [
        (start, end)
        for (start, is_hook), (end, _) in zip(headers, headers[1:], strict=False)
        if is_hook
    ]


def inline_span(text: str, hooks: list[dict[str, object]]) -> tuple[int, int]:
    for match in INLINE_HOOKS.finditer(text):
        for end in re.finditer(r"\]", text[match.end():]):
            stop = match.end() + end.end()
            try:
                parsed = tomllib.loads(text[:stop])
            except tomllib.TOMLDecodeError:
                continue
            if parsed.get("hooks") == hooks:
                return match.end(), stop
    raise ValueError("Could not locate the root hooks array.")


def toml_fields(row: dict[str, object]) -> list[tuple[str, str]]:
    fields = []
    for key, value in row.items():
        if isinstance(value, str):
            literal = json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
        elif type(value) is int:
            literal = str(value)
        else:
            raise ValueError("Expected text or an integer in a Kimi hook.")
        fields.append((json.dumps(key, ensure_ascii=False), literal))
    return fields


class KimiHooks:
    def __init__(self, snapshot: SettingsFile, command: str, events: Iterable[str]) -> None:
        self.snapshot = snapshot
        self.command = command
        self.events = sorted(events)
        try:
            self.text = (snapshot.contents or b"").decode("utf-8")
            self.document = tomllib.loads(self.text)
            self.rows = hook_rows(self.document)
        except (ValueError, RecursionError):
            raise SettingsError(f"Invalid TOML hook settings: {snapshot.path}") from None

    def installed(self) -> bool:
        return all(
            any(
                row.get("command") == self.command
                and row.get("event") == event
                and row.get("timeout") == 5
                and row.get("matcher") in (None, "")
                for row in self.rows
            )
            for event in self.events
        )

    def install(self) -> HookEdit:
        present = {
            event for row in self.rows
            if row.get("command") == self.command and isinstance(event := row.get("event"), str)
        }
        additions: list[dict[str, object]] = [
            {"event": event, "command": self.command, "timeout": 5} for event in self.events if event not in present
        ]
        return self.edit([*self.rows, *additions], additions, [])

    def uninstall(self) -> HookEdit:
        remove = [index for index, row in enumerate(self.rows) if row.get("command") == self.command]
        rows = [row for row in self.rows if row.get("command") != self.command]
        return self.edit(rows, [], remove)

    def edit(self, rows: list[dict[str, object]], additions: list[dict[str, object]], remove: list[int]) -> HookEdit:
        count = len(additions) + len(remove)
        if not count:
            return HookEdit(self.snapshot.contents, 0)
        try:
            text = self.text
            spans = table_spans(text)
            if "hooks" in self.document and not spans:
                start, end = inline_span(text, self.rows)
                items = [", ".join(f"{key} = {value}" for key, value in toml_fields(row)) for row in rows]
                text = text[:start] + "[" + ", ".join("{" + item + "}" for item in items) + "]" + text[end:]
            else:
                for index in reversed(remove):
                    start, end = spans[index]
                    lines = text[start:end].splitlines(keepends=True)
                    # Preserve comments and spacing between tables.
                    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith("#")):
                        end -= len(lines.pop())
                    text = text[:start] + text[end:]
                for row in additions:
                    fields = "\n".join(f"{key} = {value}" for key, value in toml_fields(row))
                    separator = "" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
                    text += f"{separator}[[hooks]]\n{fields}\n"
            if hook_rows(tomllib.loads(text)) != rows:
                raise ValueError("The rewritten hooks differ from the requested edit.")
        except (ValueError, IndexError, RecursionError):
            raise SettingsError(f"Could not safely edit TOML hooks: {self.snapshot.path}") from None
        return HookEdit(text.encode("utf-8"), count)
