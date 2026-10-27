# Elma renderer

This is the first Arbol 2 conversation window, using Svelte 5 and a committed,
SHA256-verified snapshot of maintained `arbol-design-system` source. Production
Bridge/app adapters live in `src/`; fictional browser services live in
`tests/ui/` at the repository root. The controlled composer, versioned Drafts, route/repository controls and
receipt-owned send/stop/question/failure actions are implemented. Chat actions,
latest-chat selection and queued external open notices remain SYL-256.

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

The complete renderer suite has22 contract/browser scripts, including actual
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
