# Arbol

Arbol 2: the rewrite of Arbol, the local macOS application for working with several coding agents at once.

The shared Driver conformance runner, all 38 scenarios of DRV-5, is in [`conformance/`](conformance/README.md). It is typed Python since SYL-166 and needs no Node.js. The application itself remains a scaffold.

The [`arbol-builds` tool](builds/README.md) builds components into numbered folders, runs their checks, lists and withdraws Builds, prunes older files on command, and writes standalone component launchers (SYL-76). It is typed Python since SYL-165, with its own pinned Python. Install it with `uv sync --locked --group dev` and `uv run --no-sync python scripts/install_builds.py`. The Drivers' own build descriptions and first Builds are separate tasks.

| | |
|---|---|
| Package | `@sylvan-stack/arbol` 2.0.0 |
| Artifact corpus | `~/Artifacts/arbol` (GitHub `sylvan-stack/arbol-artifacts`) |
| Predecessor | `sylvan-stack/arbol_deprecated_v1`, frozen. This repository starts at 2.0.0 because version 1 is that deprecated code base |

## What the rewrite is built from

- The Product Specification, which states what Arbol does: `~/Artifacts/arbol_deprecated_v1/product-spec/` (start at `01-overview-and-scope.md`).
- The Arbol Design System, which states how Arbol looks and is operated: `sylvan-stack/arbol-design-system`.
- The Glossary: `~/Artifacts/arbol/GLOSSARY.md`.

## Sylvan Stack 2

| Repository | Package | Version | Artifact corpus | Artifact repository |
|---|---|---|---|---|
| `arbol` | `@sylvan-stack/arbol` | 2.0.0 | `~/Artifacts/arbol` | `sylvan-stack/arbol-artifacts` |
| `arbol-root` | `@sylvan-stack/arbol-root` | 1.0.0 | `~/Artifacts/arbol-root` | `sylvan-stack/arbol-root-artifacts` |
| `arbol-trunk` | `@sylvan-stack/arbol-trunk` | 1.0.0 | `~/Artifacts/arbol-trunk` | `sylvan-stack/arbol-trunk-artifacts` |
| `arbol-claude-driver` | `@sylvan-stack/arbol-claude-driver` | 1.0.0 | `~/Artifacts/arbol-claude-driver` | `sylvan-stack/arbol-claude-driver-artifacts` |
| `arbol-codex-driver` | `@sylvan-stack/arbol-codex-driver` | 1.0.0 | `~/Artifacts/arbol-codex-driver` | `sylvan-stack/arbol-codex-driver-artifacts` |
| `mycel` | `@sylvan-stack/mycel` | 2.0.0 | `~/Artifacts/mycel` | `sylvan-stack/mycel-artifacts` |
