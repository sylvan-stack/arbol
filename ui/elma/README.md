# Elma renderer

This is the first Arbol 2 conversation window, using Svelte 5 and a committed,
SHA256-verified snapshot of maintained `arbol-design-system` source. Production
Bridge/app adapters live in `src/`; fictional browser services live in
`tests/ui/` at the repository root. The composer, Draft/send controls and chat
actions are the subsequent implementation Beats.

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
