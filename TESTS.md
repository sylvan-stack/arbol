# Tests: arbol

Both tiers have uncommented source. Only the top-tier cases below may be selected during implementation. They may be selected when useful during implementation; running tests after every change is not required. Writing or running mid-tier tests requires a separate testing task explicitly requested by the owner. Do not write or restore low-tier tests.

[Mid-tier descriptions and justifications](MID_TIER.md) · [Complete inventory and tier justifications](docs/test-inventory.md) · [Machine-readable inventory](test-tiers.json)

Reviewed revision: `f66335c7e203794dc84e40fe3106e85f8cae2dd6` under SYL-327 (29 October 2026). No tests were run.

## Selection and limits

3 top-tier inventory entries and 151 mid-tier entries are available after the higher-bar review. 505 low-tier entries were removed under SYL-327. Definitions, scenarios, programs and entry points overlap; this is not a runtime suite count. Top-tier bodies are unchanged. Retained mid-tier sources remain uncommented.

## Active top tier

| Exact selector or program | Why this case earns a place |
| --- | --- |
| [`test_top_backend_test_chat_wire.Windows.test_late_older_write_reply_cannot_publish_stale_settings`](tests/top/test_top_backend_test_chat_wire.py#L15) | Delays one completed database write while another window changes settings. Observes the real Bridge subscription to reject stale publication after the older reply resumes. Requires a disposable PostgreSQL fixture. |
| [`test_top_backend_test_event_file.Files.test_captured_cutoff_excludes_later_blocks_and_partial_line_finishes_on_next_poll`](tests/top/test_top_backend_test_event_file.py#L15) | Appends bytes after a captured file cutoff and splits a later record before its newline. Checks that the first snapshot excludes later events and that a subsequent poll recovers every complete event once. |
| [`test_top_roots.DatabaseAccess.test_roots_creation_retains_a_recovery_receipt_for_uncertain_outcomes_or_failed_rollback`](tests/top/test_top_roots.py#L16) | Injects both an uncertain CREATE result and a refused compensating DROP. Requires the private recovery receipt to survive without publishing a Root or dropping a database whose creation is uncertain. |

## Layout and shared support

Case bodies are separated into [`tests/top/`](tests/top/) and [`tests/mid/`](tests/mid/). The former mixed test modules retain shared fixture classes, helper functions and imports at their established paths, with no inventoried test methods. This preserves existing subprocess paths, patch targets and fixture imports without copying helpers into both tiers. Compatibility entries preserve original package and resource paths while loading the mid-tier implementation. Product-side test APIs load it only when invoked and refuse if the test source is absent.

## Running a selected top-tier case

Select an exact method when it resolves a concrete uncertainty; no run is required after an edit. The new module names begin with test_top_ so they cannot shadow the shared fixture modules. Do not run whole folders or discovery as a substitute. Original prerequisites, skips and environment limitations still apply. A focused result is not full qualification.

From the repository root, using the prepared repository interpreter:

```sh
PYTHONPATH=src:tests:tests/top python -m unittest test_top_backend_test_chat_wire.Windows.test_late_older_write_reply_cannot_publish_stale_settings
```

## Mid-tier execution

[MID_TIER.md](MID_TIER.md) lists the descriptions, tier reasons and review status. The source is now uncommented and stays that way. Writing or running it still requires a separately requested testing task. Do not run tests automatically after edits or merges. Inspect prerequisites and indirect calls before invoking a program or qualification entry point. A focused result is not full qualification.

For a Python method, use the same fixture setup as the top tier, put the mid folder on PYTHONPATH, and select `test_mid_<module>.Class.test_method`. Mycel's fixture-aware runner accepts `--tests tests/mid --select test_mid_<module>.Class.test_method`; store cases require explicit disposable-store settings. Archived scenarios and programs retain their original compatibility entry paths.

Restoration under SYL-326 used static checks only. No tests, Builds, provider calls, Origin migrations or corpus ingest were performed. Original prerequisites and environment limits still apply.

The shared conformance runner requires explicit `--only` selections. Removed scenario IDs are unavailable; native-only retained IDs refuse generic-driver execution. Historical qualification commands that require deleted scenarios remain unsatisfied. The UI runner contains only retained programs and reports a reduced selection. MiMo’s vendored copy retains twelve commented scenarios, accounted separately in its inventory.

## Builds

Since SYL-329 (29 October 2026) a Build runs the top tier only. The backend Build's `unit` check runs every case under `tests/top/`, with its own interpreter and private PostgreSQL. The mid tier runs only when the owner asks for a mid-tier run.
