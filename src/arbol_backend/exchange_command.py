"""Command input, without opening the request or running a Trunk."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .exchange_context import Refusal
from .model import BUILD_ID

COMMON = {'--runtime-dir', '--bin-dir'}
FORWARD = {'--chat', '--replaces', '--cwd', '--driver', '--subscription', '--model', '--effort'}
START = {'--exchange', '--request', '-v'} | FORWARD
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z', re.ASCII)


@dataclass(frozen=True)
class Command:
    name: str
    code: str | None
    options: dict[str, str]
    forward: list[str]
    exchange: str | None = None


def parse(args: list[str]) -> Command:
    words: list[str] = []
    options: dict[str, str] = {}
    forward: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        if word.startswith('-'):
            key, equals, value = word.partition('=')
            if key == '--force' and words and words[0] == 'stop':
                if equals or key in options:
                    raise Refusal('invalid_input', '--force is a value-free flag, given once.')
                options[key] = 'true'
                index += 1
                continue
            if key not in COMMON and not (words and words[0] == 'start' and key in START):
                raise Refusal('invalid_input', f'Unknown or misplaced option: {key}')
            if key in options:
                raise Refusal('invalid_input', f'Repeated option: {key}')
            tokens = [word]
            if not equals:
                index += 1
                if index >= len(args) or args[index].startswith('-'):
                    raise Refusal('invalid_input', f'{key} needs a value.')
                value = args[index]
                tokens.append(value)
            if not value:
                raise Refusal('invalid_input', f'{key} needs a value.')
            options[key] = value
            if key in FORWARD:
                forward.extend(tokens)
        else:
            words.append(word)
        index += 1
    if not words or words[0] not in {'trunks', 'start', 'list', 'stop', 'settle'}:
        raise Refusal('invalid_input', 'Expected trunks, start, list, stop or settle.')
    name = words[0]
    if len(words) > (1 if name == 'list' else 2):
        raise Refusal('invalid_input', f'Surplus argument for {name}.')
    code = words[1] if len(words) == 2 and name in {'trunks', 'start'} else None
    if code is not None and (not re.fullmatch(r'[a-z][a-z0-9]{0,31}', code) or code in {'run', 'settle', 'list'}):
        raise Refusal('invalid_input', 'Expected a Trunk code name.')
    if name == 'start':
        if not UUID.fullmatch(options.get('--exchange', '')) or '--request' not in options:
            raise Refusal('invalid_input', 'start requires --exchange <UUID> and --request <file>.')
        if '-v' in options and not BUILD_ID.fullmatch(options['-v']):
            raise Refusal('invalid_input', '-v needs a positive lower-case hexadecimal Build number.')
    if name in {'stop', 'settle'}:
        exchange = words[1] if len(words) == 2 else None
        if (name == 'stop' and exchange is None) or (exchange is not None and not UUID.fullmatch(exchange)):
            raise Refusal('invalid_input', f'{name} requires a UUID Exchange identifier.')
        return Command(name, None, options, forward, exchange)
    return Command(name, code or ('trivial' if name == 'start' else None), options, forward)
