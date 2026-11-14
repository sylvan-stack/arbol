"""Sealed provider command body; packaging prefixes the complete isolated verifier.

A source script is not a qualified provider and cannot fall back to source-path
imports. The sealed prefix supplies its verified descriptor only in globals.
"""

import sys

if "__arbol_sealed_payload__" not in globals():
    sys.stdout.write('{"error":{"code":"builds_failed","message":"Use the verified immutable Driver provider."}}\n')
    raise SystemExit(1)

from arbol_builds.cli import entry  # noqa: E402

entry()
