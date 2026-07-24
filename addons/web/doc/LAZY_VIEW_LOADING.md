# Lazy View Loading — Feasibility & Decision Record

Status: **Investigated. Not implemented — no code in the tree.** A minimal
mechanism was prototyped and reverted as unused (YAGNI). This document records
the analysis so the question isn't re-litigated. Date: 2026-07-23. Scope:
`addons/web` view loading + ESM asset pipeline.

## Problem

`web/__manifest__.py` globs `web/static/src/views/**/*` into the eager
`web.assets_backend` bundle, so **all** view types — including graph, pivot and
calendar, which most sessions never open — are parsed and evaluated at every
backend boot. The idea was to defer that heavy view code out of the initial
bundle to speed boot.

## The mechanism we prototyped (and reverted)

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

It was correct and Hoot-tested, with one useful property: **a no-op whenever the
descriptor is already eagerly registered** (`viewRegistry.contains`), so
declaring a view lazy is harmless while its code is still eager. It was reverted
because **nothing used it** — adding an `await`-able branch and a registry to the
hot view-loading path for a deferred, low-ROI direction is a speculative
abstraction. Re-introduce it only alongside a real consumer.

## Feasibility investigation

### Measured ROI (real esbuild `--metafile` bytes, not estimates)

The metafile is persisted next to every bundle as a `.meta.json` `ir.attachment`
(`ir_qweb_assets.py`, `_persist_esm_attachment_rows`). Reading the real
`web.assets_web` metafile (web + web_enterprise, minified):

| | minified | % of 3.5 MB backend bundle |
|---|---|---|
| graph base | 24 KB | 0.69% |
| pivot base | 27 KB | 0.78% |
| calendar base | 61 KB | 1.75% |
| **all three bases** | **110 KB** | **3.2%** |
| with ~47 extensions (est.) | ~180–200 KB | ~5–6% |
| Chart.js (the heavy dep) | **already lazy** (`loadChartJS`) | ~0 eager |
| for scale: `mail/odoo_sfu.js` (one file) | 232 KB | 6.6% |

The whole target is ~3–6% of the bundle; the genuinely heavy dependency
(Chart.js) is **already deferred**; the bundle is content-addressed and cached
after first load, so the recurring cost is only parse/eval (~10–25 ms per full
page load). A single unrelated eager file (`odoo_sfu.js`, WebRTC, rarely used) is
**larger than all three view bases combined.**

### Why it is hard — three independent blockers

1. **Import-time side effects (root cause, not the bundler).** Views register at
   module top level (`registry.category("views").add(...)`) **and** extend via
   top-level `class Sub extends BaseController` (static import of the base). Both
   force eager evaluation. Verified empirically: making the calendar
   `attendee_calendar` view lazy and then installing `google_calendar` (which does
   `class GoogleCalendarController extends AttendeeCalendarController`) **crashes
   boot** — `Cannot read properties of undefined (reading 'prototype')` — because
   the pipeline shims the now-child-exclusive base to `odoo.loader.modules.get()`,
   which is `undefined` until the lazy bundle loads, and the eager subclass
   evaluates `extends undefined` at boot. **Per-consumer lazy bundles are unsafe
   for any extended view.**

2. **The bases are eager-imported by NON-view code.** Measured: `spreadsheet`
   (`pivot_model`, `chart_data_source`), `web_studio` view editors, `stock`
   forecast dashboards, and ~85 calendar-utility consumers (field widgets,
   activity components importing calendar model/helpers). The base can't be
   wholesale-deferred; it would need splitting into a lazy Controller/Renderer
   layer vs. an eager model/utility layer.

3. **Pipeline constraint + double-class hazard.** The esbuild bridge only shims a
   bundle's *own* dynamic children or its *parent* — not a *sibling* lazy bundle.
   A lazy consumer importing a lazy base inlines it → two class identities,
   breaking `patchWithCleanup`/`instanceof`/`patch` (`ESM_BUNDLING.md`, the
   spreadsheet→graph_model note). The only split-free shape is one lazy bundle
   per *family* (base + every extension across every module, one copy) with every
   `js_class` mapped to it — which is **atomic per family**: every importer must
   convert together or boot crashes (blocker 1). For calendar alone that's ~13
   coordinated modules (mail, project, calendar, hr_holidays, event,
   hr_work_entry, hr_timesheet, maintenance, hr_homeworking_calendar + enterprise
   planning, hr_payroll, timesheet_grid, web_studio, knowledge, google/microsoft/
   appointment); comparable sets for graph and pivot — several hundred files
   fork-wide, not incrementally parallelizable.

### How other systems solve this

- **`import defer` (TC39 Stage 3)** — the purpose-built native fix: load a module
  to execution-ready state but defer *evaluation* until first property access, so
  a subclass can import a base without eagerly evaluating it. As of 2026 esbuild
  (0.25.7) only *parses* the syntax; no deferred-eval bundling (Vite 8/Webpack 6
  partial). **Not usable in this pipeline yet.**
- **Composition over inheritance** — the durable answer; avoids `extends` across
  module boundaries so extensions stay code-splittable (the direction the
  SearchModel mixin refactors took). Reworking view extension this way is a
  framework project, not a rollout.
- **Module Federation shared modules** — runtime singleton sharing across chunks;
  Odoo's `odoo.loader.modules` + shim bridge is already a homegrown equivalent.

## Decision

**Do not pursue the fork-wide lazy-view rollout, and do not carry the mechanism
until there is a consumer.** As framed it is low ROI (~3–6% of the bundle, heavy
dep already lazy, cached after first load) and high cost/risk (atomic per-family
conversion of hundreds of files, boot-crash trap for extended views, base blocked
by non-view eager importers). The per-consumer prototype was empirically shown to
crash boot with an eager extender installed, and reverted.

### If boot speed is a priority, target bigger/safer wins first
1. **Profile the real backend boot** — at 3.2% the view bases are not the
   bottleneck.
2. **`odoo_sfu.js` (232 KB, WebRTC, leaf library, rarely used)** — 2× the payoff
   of all three view bases, and a leaf with no inheritance coupling (none of the
   hazards above). Prime lazy candidate.

### If lazy views are ever revisited
- A **leaf** view (nothing extends it, no eager non-view importer) is safe to
  defer with a small `lazy_views`-style registry + a `loadBundle` in
  `View.loadView` (the prototype above) plus a per-view dynamic-child bundle. The
  three big families are **not** leaves and need the atomic per-family treatment.
- Prefer adopting `import defer` once esbuild ships deferred-eval bundling, and/or
  moving view extension toward composition — both remove the root cause instead of
  working around it.

Key files: `web/static/src/views/view.js` (`viewRegistry`, `View.loadView`) ·
`web/static/src/core/assets.js` (`loadBundle`, `LazyComponent`) ·
`odoo/addons/base/models/ir_qweb_assets.py` (esbuild + metafile persistence) ·
`web/machine_doc_v1/ESM_BUNDLING.md` (bridge/self-bridge, double-class hazard).
