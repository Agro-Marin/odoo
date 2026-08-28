# ADR-0074: A shipped static source reaches a bundle

- **Status:** Accepted
- **Date:** 2026-08-28

## Context

`TestAssetPathsExist` asks one direction of the asset question: does every path a
manifest declares match a file on disk. It exists because a `remove` directive
whose target is gone raises `AssetDirectiveError` while assembling the bundle,
which aborts every database that installs the module — a loud failure, and one
worth catching early.

Nothing asked the other direction: does every file a module ships under
`static/src` reach a bundle at all. That direction fails silently, and silence is
the whole problem.

`purchase_mrp` declared

```python
"assets": {"web.assets_backend": ["mrp/static/src/**/*.js"]}
```

— **another module's** paths, and a narrower duplicate of the
`mrp/static/src/**/*` that `mrp` already declares for itself. Its own
`static/src/components/bom_overview_line/mrp_bom_overview_line.js` was declared
by nobody. That file patches `BomOverviewLine.goToRoute` so the *buy* case
navigates; base `mrp` handles only `"manufacture"` and returns `undefined`. In
the BoM Overview's forecast view the supplier name renders as a live
`<a t-on-click="() => this.goToRoute(data.route_type)">`.

Driven in a browser, before and after the manifest was corrected:

| | before | after |
|---|---|---|
| `purchase_mrp` in any loaded script | none | `web.assets_web.esm.js` |
| vendor link present and clickable | yes | yes |
| result of clicking it | nothing | opens the component |
| console error | none | none |

Every existing lane passed throughout. `TestAssetPathsExist` passed because
`mrp/static/src/**/*.js` does match files. `eslint` and `prettier` read the file
off disk and never ask whether it is served. No test imported it, because it is
a patch: its only effect is on a component someone else renders.

## Decision

`test_lint` carries `TestOrphanAssets`: every `static/src` file of an installed
module with a bundled extension is in some bundle, or in a named `URL_FETCHED`
exemption. It runs in `asset_lint.yml`, alongside the other checks that need a
registry.

Three properties of the check are load-bearing:

- **It resolves bundles through `ir.asset._get_asset_paths`, never by globbing
  manifests.** Modules contribute paths through `ir.asset` *data records* and
  through `include` directives, neither of which a manifest sweep can see. A
  manifest-glob prototype reported **1076** orphans across 97 modules; the live
  resolver reports **6**. `mail/static/src/chatter/web/form_controller.js`
  appears in no manifest anywhere and is bundled all the same.
- **The exemption list is exact paths, not patterns.** All six standing entries
  are files the browser or platform fetches by URL — three service workers, two
  audio worklets, the module loader and the public database manager. A pattern
  would let the next real orphan hide behind it.
- **The exemption list is checked in both directions.** An entry that becomes
  bundled fails the test, because an exemption describing nothing is an
  exemption that will quietly cover something later.

Coverage is the lane's `INSTALL` set, exactly as for `TestBundleTokenDefs`: only
an installed module's bundles resolve. Widen `INSTALL` rather than assume the
tree is checked.

## Alternatives considered

**Sweep the manifests instead of resolving the bundles.** Rejected on a
measurement, and it is the reason the resolver property above is stated as
load-bearing rather than as an implementation note. A prototype that globbed
`assets` declarations reported 1076 orphans across 97 modules on 2026-08-28; the
resolver reported 6 against the same tree. The gap is not noise — modules
contribute paths through `ir.asset` data records and through `include`
directives, and a manifest sweep can see neither. `TestAssetPathsExist` can
afford to read manifests because it asks whether a *declared* path exists; this
check asks whether a shipped file is *served*, and only the resolver knows.

**Exempt by pattern rather than by exact path.** Rejected. Every standing
exemption is a file the browser or platform fetches by URL, and each is a
closed, nameable set — service workers, audio worklets, the module loader, the
database manager. A pattern such as `**/*_worker.js` would admit the next real
orphan that happened to match it, which converts the exemption list from a
statement about six files into a hole of unknown size.

**Let the exemption list be one-directional.** Rejected for the same reason the
ratchets here are `exact`: an entry that has since become bundled describes
nothing, and a list nobody is forced to prune is a list that silently grows
until it covers the defect the check exists to catch.

**Ask the harder question — is the file ever executed.** Not rejected, but
deliberately out of scope: a module patching a component nobody renders passes
this check. Answering it needs runtime coverage, not static resolution, and
building the weaker instrument first was preferred to shipping nothing while the
stronger one was designed.

## Consequences

A manifest that points at another module's paths, a file moved out of the glob
that names it, and a new source added to a module whose manifest nobody updated
all fail at the gate instead of shipping as a feature that renders and does
nothing.

The check cannot see a file whose bundle fails to assemble; it reports those
bundles separately rather than counting their files as orphans, because a
bundle that cannot assemble is `TestBundlesAssemble`'s finding and would
otherwise turn one defect into hundreds.

It does not check that a bundled file is ever *executed*. A module patching a
component nobody renders still passes. That is a different question and needs a
different instrument.

## Enforcement

`TestOrphanAssets` in `addons/test_lint/tests/test_orphan_assets.py`, run by
`.github/workflows/asset_lint.yml` — the lane for the `test_lint` checks that
need a real registry, since bundles resolve only against installed modules. The
class is named explicitly in that workflow rather than reached through
`--test-tags /test_lint`.

The check is self-guarding in the direction that usually rots: `URL_FETCHED` is
verified in both directions, so an exemption that becomes bundled fails the test
rather than lingering. Its blind spot is scope, not correctness — coverage is
the lane's `INSTALL` set, so a module outside that set is not examined. Widen
`INSTALL` rather than assume the tree is checked.
