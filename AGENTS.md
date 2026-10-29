# Arbol repository instructions

## Arbol design-system synchronization

The shared design reference is the private repository
https://github.com/sylvan-stack/arbol-design-system.

Every user-requested UI/UX design change must also update that repository as
part of the same task. Do not change only this application's design and leave
the shared reference stale. This includes styling, tokens, components, layouts,
navigation, responsive behavior, forms, dialogs, states and accessibility.
Backend-only changes with no observable UI/UX effect are exempt.

Before implementing a design change, locate the design-system checkout or use
`gh repo clone sylvan-stack/arbol-design-system`, then read its root AGENTS.md
and relevant design contracts. Follow its synchronization workflow: reuse or
generalize shared components, update executable stories and affected sections
and pages, document the resulting contract, and validate both implementations.
Keep production integrations in this application and fictional fixtures in the
design system. Preserve unrelated work in both repositories.

When delivering, identify the changes and validation in both repositories and
link their commits or PRs when available. Follow repository delivery rules and
the user's publishing instructions. If access or another dependency blocks
the shared update, explicitly report the unfinished work; do not claim the
design task is complete or remotely synchronized. Explicit user instructions
limiting scope or requesting a temporary experiment take precedence; disclose
any resulting divergence.

## Test execution policy

Follow [TESTS.md](TESTS.md), [MID_TIER.md](MID_TIER.md), the linked inventory and
the owner's [Test Strategy](/Users/msix/Artifacts/mycel/operations/test-strategy.md).
**All test work belongs to a separate task explicitly requested by the owner.**
There is no top-tier exception during implementation. Write and polish code
first; only the owner decides when it is ready for tests and requests that work.
Do not add, edit, fix, refactor, classify, retire, restore or run tests, fixtures,
snapshots, runners or inventories as part of implementation. Existing tests may
be read as source reference. Report relevant test impact; do not start testing,
create a testing task yourself or relabel an implementation step as a testing task.

Keep runnable suites small. A new function, branch or option does not need a
matching test automatically. Each retained case must add distinct consequential
information. Routine permutations, copied defaults, mocked success/forwarding
and redundant CRUD are low tier; use the strategy's examples and admission bar.
Before adding a test in an authorized task, read the nearby retained cases and
low-tier comments so the rejected idea is not recreated.

Keep existing rejected cases as literal comments at the end of their test files,
marked `LOW TIER — DO NOT ENABLE OR RECREATE`, with original ID, reason, retained
evidence when applicable and source revision. An entirely low-tier file is
comment-only. Record low/commented status and footer location in the inventory.
Never use skipped tests, disabled suites or executable wrappers as archives.
New evidence and the owner's testing request are required for re-admission.

Keep retained top/mid source in the repository's documented layout and state.
A separately requested testing/Build task runs the whole top tier through the
Build gate; no test-running Build or hook runs during implementation. Mid-tier
execution additionally requires the owner's request for that scope. Do not
bypass a gate or call a reduced selection full qualification. Test-free static
syntax, type and compilation checks remain available. Report checks not run.
This policy supersedes older automatic testing and top-tier exceptions.
