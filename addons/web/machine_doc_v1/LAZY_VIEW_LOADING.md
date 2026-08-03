# Lazy View Loading — Feasibility & Decision Record

Status: **Investigated. Not implemented — no code in the tree.** Prototyped, then
reverted as unused. Date: 2026-07-23. Scope: `addons/web` view loading + ESM
asset pipeline.

## Problem

`web/__manifest__.py` globs `web/static/src/views/**/*` into the eager
`web.assets_backend` bundle. All view types — including graph, pivot and
calendar, which most sessions never open — are parsed and evaluated at every
backend boot. Goal: defer that code out of the initial bundle.

## Prototyped mechanism (reverted)

A `lazy_views` registry mapping a view key (view `type`, or an arch `js_class`)
to the bundle that registers the real descriptor, consulted by `View.loadView`
just before resolving the descriptor:

```js
if (!viewRegistry.contains(jsClass) && lazyViewRegistry.contains(jsClass)) {
    await loadBundle(lazyViewRegistry.get(jsClass));
    if (loadId !== this.loadViewId) { return; }   // same epoch guard as loadViews
}
const descr = viewRegistry.get(jsClass);
```

Correct and Hoot-tested. Useful property: **no-op whenever the descriptor is
already eagerly registered** (`viewRegistry.contains`), so declaring a view lazy
is harmless while its code is still eager. Reverted because nothing used it —
an `await`-able branch plus a registry on the hot view-loading path, with no
consumer. Re-introduce only alongside one.

## Feasibility investigation

### Measured ROI (esbuild `--metafile` bytes)

The metafile is persisted beside every bundle as a `.meta.json` `ir.attachment`
(`ir_qweb_assets.py`, `_persist_esm_attachment_rows`), read here from
`web.assets_web` (web + web_enterprise, minified).

**Point-in-time reading of a 2026-07-23 build.** Re-deriving needs a rebuild;
re-read the `.meta.json` attachment before quoting these as current.

| | minified | % of 3.5 MB backend bundle |
|---|---|---|
| graph base | 24 KB | 0.69% |
| pivot base | 27 KB | 0.78% |
| calendar base | 61 KB | 1.75% |
| **all three bases** | **110 KB** | **3.2%** |
| with ~47 extensions (est.) | ~180–200 KB | ~5–6% |
| Chart.js (the heavy dep) | **already lazy** (`loadChartJS`) | ~0 eager |
| for scale: `mail/static/lib/odoo_sfu/odoo_sfu.js` (one file) | 232 KB | 6.6% |

The whole target is ~3–6% of the bundle; the genuinely heavy dependency
(Chart.js) is **already deferred**; the bundle is content-addressed and cached
after first load, so the recurring cost is only parse/eval (~10–25 ms per full
page load). A single unrelated eager file (`odoo_sfu.js`, WebRTC, rarely used) is
**larger than all three view bases combined.**

### Why it is hard — three independent blockers

1. **Import-time side effects (root cause, not the bundler).** Views register at
   module top level (`registry.category("views").add(...)`) and reach into a base
   at module top level — `class Sub extends BaseController` or
   `patch(BaseController.prototype, {...})`. Both dereference the base binding
   during module evaluation, forcing eager evaluation.

   Verified: making `attendee_calendar` lazy, then installing `google_calendar`,
   crashes boot with `Cannot read properties of undefined (reading 'prototype')`.
   The pipeline shims the now-child-exclusive base to `odoo.loader.modules.get()`,
   `undefined` until the lazy bundle loads.

   The error string discriminates the two forms.
   `google_calendar_controller.js` uses `patch(...prototype)` →
   `undefined.prototype`. An `extends` consumer throws
   `Class extends value undefined is not a constructor or null` instead. Both
   boot-fatal.

   **Per-consumer lazy bundles are unsafe for any extended *or patched* view.**
   `patch` is the commoner form here, so the blast radius exceeds what an
   `extends`-only survey shows.

2. **The bases are eager-imported by non-view code.** `spreadsheet`
   (`pivot_model`, `chart_data_source`), `web_studio` view editors, `stock`
   forecast dashboards, and 64 files outside `web/static/src/views/calendar/`
   importing `@web/views/calendar/…` (field widgets, activity components). No
   wholesale deferral: the base needs splitting into a lazy Controller/Renderer
   layer and an eager model/utility layer.

3. **Pipeline constraint + double-class hazard.** The esbuild bridge shims a
   bundle's own dynamic children or its parent — not a *sibling* lazy bundle. A
   lazy consumer importing a lazy base inlines it → two class identities,
   breaking `patchWithCleanup` / `instanceof` / `patch` (`ESM_BUNDLING.md`,
   spreadsheet→graph_model note).

   The only split-free shape is one lazy bundle per *family* (base + every
   extension across every module, one copy), every `js_class` mapped to it.
   That is **atomic per family**: every importer converts together or boot
   crashes per blocker 1. Calendar alone spans ~13 modules — mail, project,
   calendar, hr_holidays, event, hr_work_entry, hr_timesheet, maintenance,
   hr_homeworking_calendar, plus enterprise planning, hr_payroll,
   timesheet_grid, web_studio, knowledge, google/microsoft/appointment.
   Comparable sets for graph and pivot: several hundred files fork-wide, not
   incrementally parallelizable.

### How other systems solve this

- **`import defer` (TC39 Stage 3)** — the purpose-built fix: load a module to
  execution-ready state, defer *evaluation* to first property access, so a
  subclass imports a base without evaluating it. esbuild
  (`node_modules/esbuild`, 0.25.12) only parses the syntax; no deferred-eval
  bundling (Vite 8 / Webpack 6 partial). **Not usable here yet.**
- **Composition over inheritance** — durable fix. Avoids `extends` across module
  boundaries, keeping extensions code-splittable; the direction the SearchModel
  mixin refactors took. A framework project, not a rollout.
- **Module Federation shared modules** — runtime singleton sharing across chunks.
  `odoo.loader.modules` + shim bridge is already a homegrown equivalent.

## Decision

**Do not pursue the fork-wide rollout. Do not carry the mechanism without a
consumer.**

Low ROI: ~3–6% of the bundle, heavy dep already lazy, cached after first load.
High cost/risk: atomic per-family conversion of hundreds of files, boot-crash
trap for extended views, base blocked by non-view eager importers. The
per-consumer prototype crashed boot with an eager extender installed.

### Higher-value boot-speed targets
1. **Profile the real backend boot.** At 3.2%, the view bases are not the
   bottleneck.
2. **`odoo_sfu.js`** (232 KB, WebRTC, rarely used). 2× the payoff of all three
   view bases, and a leaf — none of the hazards above. Prime lazy candidate.

### If revisited
- A **leaf** view (nothing extends it, no eager non-view importer) is safe to
  defer: `lazy_views`-style registry + `loadBundle` in `View.loadView`, plus a
  per-view dynamic-child bundle. The three big families are not leaves and need
  the atomic per-family treatment.
- Prefer `import defer` once esbuild ships deferred-eval bundling, and/or move
  view extension toward composition. Both remove the root cause.

Key files: `web/static/src/views/view.js` (`viewRegistry`, `View.loadView`) ·
`web/static/src/core/assets.js` (`loadBundle`, `LazyComponent`) ·
`odoo/addons/base/models/ir_qweb_assets.py` (esbuild + metafile persistence) ·
`web/machine_doc_v1/ESM_BUNDLING.md` (bridge/self-bridge, double-class hazard).
