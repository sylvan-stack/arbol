# Elma renderer

This is the first Arbol 2 conversation window, using Svelte 5 and a committed,
SHA256-verified snapshot of maintained `arbol-design-system` source. Production
Bridge/app adapters live in `src/`; fictional browser services live in
`tests/ui/` at the repository root. The controlled composer, versioned Drafts, route/repository controls and
receipt-owned send/stop/question/failure actions are implemented, together with
chat rename/ongoing/archive, quick actions, bounded latest chats, serialized
external opening, public sign-in refresh, attention/reconnect recovery and
explicit stale-copy bring-over. Native Swift host delivery remains SYL-192.

Install the exact dependency lock with `npm ci --ignore-scripts`, then use
`npm run check`, `npm run build` and `npm test`. The browser checks use the pinned
Playwright Chromium test runtime. Build the source bundle without a numbered
`ARBOL_BUILD_NUMBER` before source tests; their stand-in announces `development`.
The complete repository and design-system suites are also required before merge.

From the repository root, `python3 tools/sync_elma_design.py --check` checks the
snapshot without reading a sibling checkout. Updating it is explicit:
`python3 tools/sync_elma_design.py --source ../arbol-design-system`; commit the
paired maintained design change first. The source commit and hashes stay in
`design-system/manifest.json`.

The Arbol packager installs the lock, checks/builds this package with the allocated
Build number, and copies only compiled assets, local fonts, license notices and
provenance into the Build's `ui/elma/`. Daily rendering and the packaged standard
library development relay need no Node or sibling source checkout. The relay
serves the newest working, unpruned matching Root Build and starts no backend.
Its printed per-start loopback URL exchanges its token for a port-specific
HttpOnly/SameSite cookie. Backend traffic and the local browser app adapter stay
separate; raw HTML never runs, and external links use only the app channel.

`bundle.json` records the exact Build, dependency lock, maintained design commit,
source hashes and payload hashes. The package checks validate CSP, local assets,
fonts, paths and immutable hashes, plus the real HTTP/WebSocket relay. Browser
qualification additionally runs the compiled window through a private Unix
backend stand-in; it does not establish Swift host, installed Root/Trunk or vendor
behavior. Those journeys retain their own later Beats.

<!-- sources:
arbol:ui/elma/src/bridge.ts
arbol:ui/elma/src/app-channel.ts
arbol:tools/elma_bundle.py
arbol:tools/sync_elma_design.py
arbol:tools/bridge_relay.py
arbol:scripts/package_backend.py#package
arbol:tests/ui/test_bundle.py#Bundle
arbol:tests/ui/relay_browser.mjs
-->

Composer controllers preserve exact numeric revisions, revision-fenced Drafts,
unsaved-only recovery and one cached unconfirmed send request per composition.
Normal sends consume their selected canonical Draft; failure Continue sends
proceed without a selector and leaves independent composed text intact. Retry
replaces only the last saved failed turn in its original folder. Control replies
do not invent recorded question answers or saved terminal outcomes. The Build
reload barrier waits for Drafts and unconfirmed send receipts/reconciliation.

The complete renderer suite has30 contract/browser scripts, including actual
private separately compiled Builds for pending-send reloads. These use explicit
stand-in backends/accounts and never call a vendor or the owner’s installation.
Mycel coverage and Source Refs are prepared; ingest/index/embedding/retrieval
remain deferred until the owner’s first ingest.

<!-- sources:
arbol:ui/elma/src/wire-json.ts
arbol:ui/elma/src/drafts.svelte.ts
arbol:ui/elma/src/pastes.svelte.ts
arbol:ui/elma/src/routes.svelte.ts
arbol:ui/elma/src/sending.svelte.ts
arbol:ui/elma/src/window.svelte.ts
arbol:ui/elma/src/live.ts
arbol:tests/ui/run.mjs
arbol:tests/ui/drafts.mjs
arbol:tests/ui/draft_browser.mjs
arbol:tests/ui/draft_recovery.mjs
arbol:tests/ui/pastes.mjs
arbol:tests/ui/paste_browser.mjs
arbol:tests/ui/routes.mjs
arbol:tests/ui/route_browser.mjs
arbol:tests/ui/repository_browser.mjs
arbol:tests/ui/sending.mjs
arbol:tests/ui/send_browser.mjs
arbol:tests/ui/send_reload_browser.mjs
arbol:tests/ui/stop_browser.mjs
arbol:tests/ui/question_browser.mjs
arbol:tests/ui/failure_browser.mjs
-->

Chat actions use canonical publications and definitive receipts. Rename/mark
retain exact parameters across reconnect; archive saves the current Draft, waits
for pending send acceptance, requests a stop if needed, and waits for saved
terminal data. Known archived UUIDs are removed from every observing window’s
last/repository/recent conveniences, including after a later preference save.
The same chat can be reread without invalidating actions waiting in that context.
Workspace inventory updates independently of guarded default-view restoration.

Latest chats retain at most100 canonical active summaries in memory, exclude
the current chat, and order Root-local recently shown UUIDs before activity.
The native app-only channel is gated by Draft readiness/saving and pending
receipts before app.takeOpen. Returned routing targets survive failed reads and
reloads until actual opening; failed selection keeps the existing subscription.
Only UUID/folder routing conveniences are cached for this purpose.

Sign-in controls refresh only public account/catalog data and show the exact
Claude/Codex/Pi command without executing it or taking a credential. Attention
keeps every stable ID, severity and literal unknown-kind message. Reconnect
retains editable Draft text and the transcript, then replaces projections from
fresh subscriptions and immediately saves a non-conflicting dirty Draft. A
healthy attention snapshot also restarts database-ended subscriptions when the
individual return event was missed.

Stale copies use Bridge migration metadata and public catalogue display names.
Bring over again saves the visible Draft and issues chat.reimport once, then
opens the validated returned UUID. A failed result read retries opening only;
a copied result preserves the continued copy. Lost/no_answer mutation receipts
show the specified uncertainty and refresh the list without automatic replay.
Actual Root migration, Swift/Willo integration, installed/vendor and Mac sleep
journeys retain their own qualification; browser fixtures state their boundary.

<!-- sources:
arbol:ui/elma/src/mutations.svelte.ts
arbol:ui/elma/src/chats.svelte.ts
arbol:ui/elma/src/opening.svelte.ts
arbol:ui/elma/src/attention.svelte.ts
arbol:ui/elma/src/window.svelte.ts
arbol:ui/elma/src/App.svelte
arbol:tests/ui/mutations.mjs
arbol:tests/ui/actions_browser.mjs
arbol:tests/ui/quick_archive_browser.mjs
arbol:tests/ui/latest_browser.mjs
arbol:tests/ui/opening_browser.mjs
arbol:tests/ui/accounts_browser.mjs
arbol:tests/ui/recovery_browser.mjs
arbol:tests/ui/reimport_browser.mjs
-->

### Deliberate installed First Sapling qualification

`tools/backend_journeys.py` supplies private immutable receipts, a five-reservation ceiling, test-state forwarding to the real installed CLIs and a correlated installed Unix Bridge client. `tests/backend/test_journeys.py` checks replay/ceiling/journal/locking and forwarding safeguards without contacting a vendor. The `installed_first_path.mjs` browser journey is deliberately absent from `tests/ui/run.mjs`: it requires `ARBOL_INSTALLED_JOURNEY=1`, a private exact-prompt reservation and exclusive per-attempt receipts. It sends one message through the actual installed renderer/relay/Backend/Root/Trunk/test Driver, closes and reopens during streamed text, checks saved completion/answer clipboard and reopens from latest chats. Keep its input, wire frames, outcomes, costs and screenshots outside Git. Inspect a failed or ambiguous existing attempt before deciding any further action; never rerun a script to obtain a fresh submission automatically. Swift delivery remains a separate qualification.

SYL-257's explicit `installed_metadata.mjs` and `installed_paste.mjs` exercise
only newly owned retained chats, preserve immutable proof and never send a
message. The paste journey verifies the real private Root file and an
acknowledged Draft across reload, then restores the original Draft.
`installed_native_stop.mjs` requires the same exact-prompt reservation and
exclusive-start guard as the first path. `tools/backend_retained_drills.py`
requires `ARBOL_INSTALLED_FAULT_PROOF=1`, refuses pre-existing active work and
existing evidence, and uses only the separately named no-vendor fixture.
It verifies exact owned process/start identities before signals and restores
paused processes in cleanup. Fault-input checks are not vendor SDK coverage.
These programs are deliberately excluded from automatic checks.
