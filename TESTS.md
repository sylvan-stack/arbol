# Tests: arbol

Only the top-tier cases below are active. They may be selected when useful during implementation; running tests after every change is not required. Writing, restoring or running mid-tier tests requires a separate testing task explicitly requested by the owner. Do not write or restore low-tier tests.

[Mid-tier descriptions and justifications](MID_TIER.md) · [Complete inventory and tier justifications](docs/test-inventory.md) · [Machine-readable inventory](test-tiers.json)

Reviewed revision: `fb3fba2677f3bbb45aea574d5383778aa9feba2b` (28 October 2026), plus the preceding local pruning changes. No tests were run for this reset.

## Selection and limits

3 active Python definitions and 0 active standalone programs; 509 commented Python definitions. Also disabled: 0 named Node cases, 72 custom scenario functions and 35 standalone check programs. 2 broad entry points explicitly refuse. 12 low-tier cases remain removed from the prior review. These categories overlap in execution and must not be added into a runtime suite size.

Top-tier cases were individually read for the failure they observe. The remaining mid-tier labels are provisional execution decisions, not a claim that thousands of tests have passed a complete semantic review. Reassess value before restoring any of them. A browser program may contain many assertions; it is inventoried as one indivisible program, not as one asserted behavior.

## Active top tier

| Exact selector or program | Why this case earns a place |
| --- | --- |
| [`test_top_backend_test_chat_wire.Windows.test_late_older_write_reply_cannot_publish_stale_settings`](tests/top/test_top_backend_test_chat_wire.py#L15) | Delays one completed database write while another window changes settings. Observes the real Bridge subscription to reject stale publication after the older reply resumes. Requires a disposable PostgreSQL fixture. |
| [`test_top_backend_test_event_file.Files.test_captured_cutoff_excludes_later_blocks_and_partial_line_finishes_on_next_poll`](tests/top/test_top_backend_test_event_file.py#L15) | Appends bytes after a captured file cutoff and splits a later record before its newline. Checks that the first snapshot excludes later events and that a subsequent poll recovers every complete event once. |
| [`test_top_roots.DatabaseAccess.test_roots_creation_retains_a_recovery_receipt_for_uncertain_outcomes_or_failed_rollback`](tests/top/test_top_roots.py#L16) | Injects both an uncertain CREATE result and a refused compensating DROP. Requires the private recovery receipt to survive without publishing a Root or dropping a database whose creation is uncertain. |

## Layout and shared support

Case bodies are separated into [`tests/top/`](tests/top/) and [`tests/mid/`](tests/mid/). The former mixed test modules retain shared fixture classes, helper functions and imports at their established paths, with no inventoried test methods. This preserves existing subprocess paths, patch targets and fixture imports without copying helpers into both tiers. Original check entry points retain their refusals.

## Running a selected top-tier case

Select an exact method when it resolves a concrete uncertainty; no run is required after an edit. The new module names begin with test_top_ so they cannot shadow the shared fixture modules. Do not run whole folders or discovery as a substitute. Original prerequisites, skips and environment limitations still apply. A focused result is not full qualification.

From the repository root, using the prepared repository interpreter:

```sh
PYTHONPATH=src:tests:tests/top python -m unittest test_top_backend_test_chat_wire.Windows.test_late_older_write_reply_cannot_publish_stale_settings
```

## Mid-tier review and restoration

[MID_TIER.md](MID_TIER.md) describes every retained mid-tier entry and its existing reason, identifies provisional classifications and explains restoration. Only a separately requested testing task may restore or run these sources. Keep the source in the mid folder; restore only the selected imports, class headers and bodies, update the inventories, and return the source to comments afterward unless the owner says otherwise. Broad entry points continue to refuse; repairing a qualification workflow requires its own explicit testing task.

Layout revision: `8e991665e2cfce92c9f8757eacf015464d09ee46`. No tests were run for this reorganization. Previous identifiers and source lines are retained in test-tiers.json. Indexed Origin relocation and ingest remain deferred; moving files supplies no new runtime proof.
