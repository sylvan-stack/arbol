# Private Browser rollback qualification source

This directory owns the additive AFM-9 5.1.6 source distribution. It is not a
production Build-tool upgrade, a published historical branch, a signature, or
qualification evidence. BRW-1.16, BRW-1.17 and BRW-1.18 require the actual
historical retirement, common rollback refusal/compatibility and forward-C
journey. Existing production CLI paths keep their defaults.

The normative route and typed interface are retained under
`/Users/msix/Builds/afm9-rollback-plan.49cXVsFk/`: `route-plan.md` SHA256
`b1d4c2a7548d1931d85f84245f5cabac9e84541e6192306ab63e565f43016012`
and `interface.md` SHA256
`507967794c31297b508450b00a341ef4633c6fe397baf32001457a8b8254c0b0`.
The accepted distribution amendment is
`/Users/msix/Builds/afm9-overlay-source.1EJ9WWC1/distribution-amendment.md`,
SHA256 `5879bfdce209cfc5afd3c6dd58f960782d52998d18fa42e3a69599976b6f7afc`.
Those private artifacts supply design authority; they are not runtime inputs.

## Single source of truth

`baseline.json` declares expected original bytes. `prepare.py` independently
reads the two Mercury captures, historical Git object, five recorded Exchange
overlays, migration Git inputs, exact e321 selector patch and all 37 received
source/installed modules. It reconstructs all historical source without
executing it. The historical commit is real local provenance, not claimed
published ancestry of current Arbol. No historical refs are changed.

`common.patch` is the only canonical delta to the historical common modules.
It adds explicit context plumbing to service, promotion, rollback,
browser_rollback, stable_catalog and cli. It retains common eligibility,
failure publication, journal2 recovery, archive publication and catalog merge.
The additive `browser_qualification.py` owns the fixed authority boundary and
custody, not another implementation of those algorithms. `prepare.py` records
complete before/after file maps and refuses any difference outside those six
modules and the one additive module. Production code is not imported during
preparation. Tar file modes are normalized to Git's executable semantics:
0644/0755 files and 0700 directories; no group-writable tar permissions survive.
The exact historical tree has no symlinks; any archive link is refused.

## Source preparation and review

From the authentic canonical checkout, after the genuine Forester booking and
Step Intention, run:

```
python3 tools/browser_rollback_qualification/prepare.py --out /Users/msix/Builds/afm9-rollback-overlay-<new-attempt>
```

Replace the angle-bracket name with a fresh alphanumeric/hyphen name. There is
no source/root/patch override or overwrite option. Preparation creates only
that fresh source tree and observed `source-manifest.json`. Failure retains
any incomplete attempt. Before publication the manifest says `unpublished`.
After managed publication, prepare a new attempt; never relabel old evidence.

Independent implementation review must read these six files, the rendered
common modules, full maps, accepted interface and genuine baseline receipts.
Use test-free static syntax checks in implementation. Tests, fixtures, software
Build qualification, signing and the actual native journey remain separately
authorized work. Source parsing does not establish runtime success.

## Published delivery declarations

The runtime route is closed until the coordinator genuinely publishes both
new exact delivery declarations in canonical AFM-9 through Forester. This
source never writes approvals, edits old Browser grants, or treats a mutable
manifest as acceptance. The grammar below is an implementation handoff for
independent review and coordinator integration, not an existing approval.

`AFM-9-QUALIFICATION-SOURCE-DELIVERY` is one BEGIN/END HTML marker block whose
JSON has exactly: `schema:1`, `status:"accepted"`,
`scope:"isolated-tool-source"`, `sourceGit`, `sourceFiles` (the exact six names
mapped to SHA256), `sourceCheckpoint`, `sourceVerdict` (actual private FileRefs),
`producerManifestSha256`, and `bootstrap:{python:FileRef,uv:FileRef}`. FileRef
uses the accepted interface's path/identity/size/sha256 shape. The accepted
source commit must be an ancestor of canonical Arbol origin/main and every
source blob must match. Checkpoint and verdict bytes must be the genuine
independent exact implementation review, not this executor's assertion.
Bootstrap Python must report 3.14.8 and uv 0.12.23. Published review locators
are resolved from the actual local origin/main Forester object; no network
fetch or caller-supplied review/root is performed by these commands.

The producer manifest is fixed at `D/delivery/producer-manifest.json`, mode0600,
<=16MiB. Exact keys are `schema:1`, `kind:"afm9-browser-producer"`, `sourceGit`,
`files`, `compileRecord`, `productSources`, `productOutputs`, `compilerInputs`,
`roleReviews`, `executables`, `osVersion` (exact macOS version, kernel release
and machine strings under keys `macOS`, `kernel`, `machine`). It includes the complete tree (<=65536 entries)
and the reviewed Browser source/compiler/output/admission maps, plus exact
FileRefs for node, codesign, hdiutil, diskutil, plutil and git. Tree entries
are `{kind:"file",mode,sha256}`, `{kind:"directory",mode}`, or
`{kind:"link",target}`; links must resolve within their sealed tree. Complete
maps include loaded dependencies, schemas and lockfiles; extra files refuse.
The coordinator's independent review must establish transitive import closure.
Neither this manifest nor its compile maps bypass the real Browser verifier.

After isolated installation, the observed tool manifest adds actual interpreter
and launcher FileRefs and full installed tree. Its exact keys are `schema:1`,
`kind:"afm9-browser-private-tool"`, `sourceGit`, `sourceFiles`, `files`,
`executables:{python,launcher}`, `pythonArchiveSha256`. The coordinator's
`AFM-9-QUALIFICATION-RUNTIME-DELIVERY` declaration has exactly `schema:1`,
`status:"accepted"`, `scope:"isolated-tool-runtime"`, `sourceReview`,
`toolManifestSha256`, `producerManifestSha256`. This separate real review binds
observed installed bytes. It does not authorize or claim a native journey.
No placeholder declaration is included or emitted here.

## Supported private installation

Once exact source review/publication, the actual producer pin package and the
coordinated no-open-Arbol-booking window exist:

```
python3 tools/browser_rollback_qualification/install.py --prepared /Users/msix/Builds/afm9-rollback-overlay-<published-attempt>
```

The wrapper reconstructs all source again, checks actual bytes and publication,
then calls the unchanged historical `scripts/install_builds.py --bin-dir`
with the fixed new `D/delivery/bin`. Python archive, installer, build support,
project and lockfile pins are checked. Downloads/cache remain in the new
attempt. The old private e321 tool and live tool are never targets. It records
38 installed modules, actual interpreter version and full tree as
`installed-unqualified`. It never runs qualification or changes a live route.
A failed installation retains its new bin and log and cannot overwrite-retry.
A manifest from a failed or unpublished source attempt is not installable.

## Fixed runtime handshake

Here D is `/Users/msix/Builds/afm9-rollback-plan.49cXVsFk`; F is exactly
`D/qualification/fixture`, preallocated and genuinely signed by the Browser
owner. No alternative path can be requested. The only new CLI is:

```
D/delivery/bin/arbol-builds browser-release qualification --request D/requests/<request>
```

The request is mode0600, <=16384 bytes, and uses the exact accepted union.
Authority is the fixed four-role `D/qualification/authority.json`. All genuine
Build1/A/B/C signatures, source admissions, review identities, complete
inventories and signed F identities must pass the direct pinned Browser
`isolated-release.mjs qualification-verify-v1` child. Its exact accepted wire
schema is in `interface.md`. Stored producer responses are never accepted.
The orchestration Node is exactly 24.22.1 at the fixed path/hash; it is not the
signed host Node24.22.2. Missing executable or import pins refuse before state
creation. Runtime is admitted only from the exact isolated installed launcher.

Forward C needs the Browser-owned fixed
`install-release.mjs qualification-forward-v1` entry, using stdin
`{schema:1,action:"forward",authoritySha256}` and output
`{schema:1,authoritySha256,selected}` after genuine `installIsolatedRelease`
success. The child opens fixed authority, reauthenticates C and all predecessors,
and cannot accept caller code, native results or mutable completion receipts.
This precise command addition requires the Browser owner's independent review;
it is a cross-repository dependency, not implemented by this directory.

The component stable lock precedes selection EX, lexical Build EX guards, then
catalog EX; all are nonblocking. Common refresh consumes existing custody.
Forward retains component EX but releases all lower locks for the real installer.
The private catalog and ledger are under `F/support/build-tool/registries`,
separate from signed `F/arbol-browser`. Only the actual selected Browser enters
catalog history. Missing active historical archive refuses before failure or
journal publication; no historical rows or release receipts are backfilled.

The historical initializer and persistent terminal observer belong to Browser.
They must bind the real original inode/inventory and pre-native journal3 FD,
then observe A/B/rollback-A/C after journal3 is gone and a distinct active archive
exists. An observer JSON receipt is never native admission. Loss of retained FD
continuity requires a genuinely new fixture journey. This overlay does not
weaken installer proof admission or recreate the retired namespace.

<!-- sources:
arbol:@code/tools/browser_rollback_qualification/prepare.py
arbol:@code/tools/browser_rollback_qualification/install.py
arbol:@code/tools/browser_rollback_qualification/browser_qualification.py
arbol:@code/tools/browser_rollback_qualification/common.patch
-->
