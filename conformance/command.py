"""The Driver command given with --driver: command words only, no shell (DRV-5, Interface)."""

from __future__ import annotations

import os

from .js import SPACE, is_absolute, resolve


def command_words(text: str) -> list[str]:
    """Words, quotes and backslashes as a shell reads them, without substitutions, redirects or globbing."""
    words: list[str] = []
    word, quote, started = "", "", False
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and quote != "'":
            index += 1
            if index >= len(text):
                raise ValueError("The Driver command ends in a backslash.")
            word += text[index]
            started = True
        elif quote:
            if character == quote:
                quote = ""
            else:
                word += character
        elif character in ("'", '"'):
            quote = character
            started = True
        elif character in SPACE:
            if started:
                words.append(word)
                word, started = "", False
        else:
            word += character
            started = True
        index += 1
    if quote:
        raise ValueError("The Driver command has an unclosed quote.")
    if started:
        words.append(word)
    if not words or not words[0]:
        raise ValueError("Give --driver a program to start.")
    return words


def _exists(path: str, executable: bool = False) -> bool:
    try:
        if executable and not os.access(path, os.X_OK):
            return False
        status = os.stat(path)
    except (OSError, ValueError):
        return False
    return not executable or (status.st_mode & 0o170000) == 0o100000


def _working_folder() -> str:
    """process.cwd(), with Node's error when the working folder cannot be found."""
    try:
        return os.getcwd()
    except FileNotFoundError:
        raise ValueError("ENOENT: process.cwd failed with error no such file or directory, the current working "
                         "directory was likely removed without changing the working directory, uv_cwd") from None
    except OSError as error:
        from .harness import fs_error
        raise fs_error(error, "uv_cwd") from None


def resolve_command(text: str, cwd: str | None = None, path: str | None = None) -> list[str]:
    """The program found on PATH or relative to the caller, and relative file arguments made absolute."""
    cwd = _working_folder() if cwd is None else cwd
    path = os.environ.get("PATH", "") if path is None else path
    program, *args = command_words(text)
    candidates = [resolve(cwd, program)] if "/" in program else \
        [resolve(cwd, folder or ".", program) for folder in path.split(":")]
    found = next((candidate for candidate in candidates if _exists(candidate, True)), None)
    if found is None:
        raise ValueError(f"Driver program was not found or is not executable: {program}")
    # The Driver works in its temporary home. Keep caller-relative fixed file arguments usable.
    resolved = [resolve(cwd, arg) if not is_absolute(arg) and not arg.startswith("-") and _exists(resolve(cwd, arg))
                else arg for arg in args]
    return [found, *resolved]


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
