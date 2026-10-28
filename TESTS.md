# Tests: arbol

Only the top-tier cases below are active. They may be selected when useful during implementation; running tests after every change is not required. Writing, restoring or running mid-tier tests requires a separate testing task explicitly requested by the owner. Do not write or restore low-tier tests.

[Complete inventory and tier justifications](docs/test-inventory.md) · [Machine-readable inventory](test-tiers.json)

Reviewed revision: `fb3fba2677f3bbb45aea574d5383778aa9feba2b` (28 October 2026), plus the preceding local pruning changes. No tests were run for this reset.

## Selection and limits

3 active Python definitions and 0 active standalone programs; 509 commented Python definitions. Also disabled: 0 named Node cases, 72 custom scenario functions and 35 standalone check programs. 2 broad entry points explicitly refuse. 12 low-tier cases remain removed from the prior review. These categories overlap in execution and must not be added into a runtime suite size.

Top-tier cases were individually read for the failure they observe. The remaining mid-tier labels are provisional execution decisions, not a claim that thousands of tests have passed a complete semantic review. Reassess value before restoring any of them. A browser program may contain many assertions; it is inventoried as one indivisible program, not as one asserted behavior.

## Active top tier

| Exact test selector | Why this case earns a place |
| --- | --- |
| [`test_chat_wire.Windows.test_late_older_write_reply_cannot_publish_stale_settings`](tests/backend/test_chat_wire.py#L218) | Delays one completed database write while another window changes settings. Observes the real Bridge subscription to reject stale publication after the older reply resumes. Requires a disposable PostgreSQL fixture. |
| [`test_event_file.Files.test_captured_cutoff_excludes_later_blocks_and_partial_line_finishes_on_next_poll`](tests/backend/test_event_file.py#L58) | Appends bytes after a captured file cutoff and splits a later record before its newline. Checks that the first snapshot excludes later events and that a subsequent poll recovers every complete event once. |
| [`test_roots.DatabaseAccess.test_roots_creation_retains_a_recovery_receipt_for_uncertain_outcomes_or_failed_rollback`](tests/test_roots.py#L645) | Injects both an uncertain CREATE result and a refused compensating DROP. Requires the private recovery receipt to survive without publishing a Root or dropping a database whose creation is uncertain. |

## Running a selected top-tier case

Select the exact method, never a whole module as a substitute. Retain the original fixture prerequisites. A missing dependency, skipped case or unavailable database is not a pass. No live-provider check was promoted.

Use the repository interpreter and source/test import paths; for example, from the repository root:

```sh
PYTHONPATH=src:tests:tests/backend python -m unittest test_chat_wire.Windows.test_late_older_write_reply_cannot_publish_stale_settings
```

For a method under `tests/backend`, use its `backend.test_…` module name. The chat-wire case starts the existing disposable PostgreSQL fixture. Other active Arbol cases use private files/process stand-ins.

## Restoring a mid-tier selection in an explicit testing task

1. Read the case and its helpers, reassess its information value, and identify the exact requested scope. Delete low-value cases instead of restoring them.
2. Uncomment only the selected `TEST-TIER-DISABLED-BEGIN` / `END` block by removing one leading `# ` (Python) or `// ` (JavaScript) from each original source line. Remove the marker lines. A bare `#` or `//` line inside a block represents an empty original line. Restore needed names from the complete `TEST-TIER-IMPORTS` statements at the file tail into their original scope and normal import section, rather than uncommenting them at the tail. Do not discard other local changes.
3. For standalone programs or custom scenario functions, remove only their adjacent `TEST-TIER-REFUSAL` stub or terminal refusal after restoring the actual implementation. Restore required shared helpers. The empty-suite `pass` is harmless and can be removed once a class has a real body.
4. Update both inventories to reflect the selection. Run only the requested scope, record actual results, then return mid-tier code to comments when the task finishes unless the owner asked to retain it active. Promotion to top tier needs a concrete, individually reviewed reason.

Broad build/qualification checks refuse while their implementation is commented. Preserve that refusal until the requested qualification has its necessary tests restored. A top-only run does not satisfy an old full-suite gate. Metadata verification, production validation, fixture helpers, Storybook examples and historical result records are not test passes and remain separate.
