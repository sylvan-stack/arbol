# Python Driver migration checks

Both Drivers moved from TypeScript to Python under SYL-95, and that migration is finished. Its TypeScript baseline was Claude `5ea45f2a04d7d8900547001159696114eeeb8e3f` and Codex `37daaf853ae1f4d5382a316b5c7da683b057dda1`.

The scripts that ran the TypeScript baseline under Node were removed on 15 October 2026, when this repository moved to Python (SYL-166). Commit `ae56d63` is the last one that has them:

- `generate-baseline.mjs` recorded the baseline's histories, Unicode and surrogate cases, decoded-image fingerprints, chat keys, Claude's UTF-16 folder encoding and the Keychain service formula. Its output is each Driver's `tests/fixtures/migration-vectors.json`. The Claude split-surrogate defect is corrected in the published DRV-6 migration amendment; the original result is kept alongside the canonical one.
- `generate-json-vectors.mjs` recorded 13 Node JSON serialization cases. Its output is each Driver's `tests/fixtures/migration-json-vectors.json`, with the original input text and the expected compact output.
- `verify-compatibility.py` ran the baseline and the Python Drivers against each other through their command lines: shared Subscriptions, competing account reservations, native continuation in both directions, peer stopping, cleanup after a killed owner and refusal of a newer data format.

The committed fixtures keep that evidence for the Drivers' own tests.

`probe-vendors.py --claude <packaged-entry> --codex <packaged-entry> --claude-state <existing-test-state> --codex-state <existing-test-state> --output <record>` records fresh no-prompt evidence using the packaged Python programs. It checks disposable version-probe state, the installed tool versions, the designated `test-anthropic`/`test-chatgpt` account/catalog/usage operations and Claude's complete `dev probe`. Account payloads are reduced to shapes. Owner configuration is compared by file metadata without reading credential contents. The script submits no inference input and does not sign in a new account.

The standalone packaging and offline registry rehearsal live in each Driver's `scripts/`. `verify_build.py` uses only disposable fixture repositories and registries; it does not establish a working production Build. Each Driver's `arbol-build.json` runs the packaged unit tests, the complete contract suite and exactly one test-account `dev build-check`.

Evidence belongs to the applicable Artifact Corpus, with source, artifact, runtime and tool provenance. Historical TypeScript records stay available and must not be represented as Python validation. Publication changes use `.claude/linear-publish/edit.py` and `conv.py`; local specifications remain the originals.
