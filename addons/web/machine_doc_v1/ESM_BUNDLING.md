# ESM Bundling — End-to-End Pipeline

Code path an asset travels from a `.js` file on disk to an executing module
in the browser, with observability hooks, failure modes, and tunable knobs.

## Pipeline diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ File on disk                                                         │
│   /addons/<addon>/static/src/**/*.js                                 │
│   Pragma: /** @odoo-module native */                                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  is_native_module() / is_odoo_module()
                                │  odoo/tools/assets/esm_graph.py
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ AssetsBundle.__init__()   assetsbundle/bundle.py                     │
│   files partitioned into:                                            │
│     • self.javascripts         (classic JS; legacy bundle)           │
│     • self.native_modules      (@odoo-module [native]; esbuild fuel) │
│     • self.templates           (XML for QWeb)                        │
│     • self.stylesheets         (SCSS/CSS)                            │
│   Only when bundle name ∈ esm_registry().bundles                     │
│   (assetsbundle/bundle.py sets self._is_esm_bundle).                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ HTTP GET /odoo                                                       │
│   ir_qweb._get_asset_nodes(bundle, debug)  ir_qweb_assets.py         │
└──────────┬────────────────────────────────┬──────────────────────────┘
           │  debug mode                    │  production
           ▼                                ▼
┌───────────────────────────┐   ┌───────────────────────────────────────┐
│ Per-file serve            │   │ Admin override? (config param)        │
│   get_native_module_data  │   │ Circuit open? (_esbuild_cooldowns)    │
│   → import_map per spec   │   │ Lock held? (pg_try_advisory_xact_lock)│
│   → <link modulepreload>  │   └─────────────────┬─────────────────────┘
│   → <script type=module>  │                     │  all green
│       /<addon>/static/... │                     ▼
└────────────┬──────────────┘   ┌────────────────────────────────────────┐
             │                  │ esbuild_native_bundle()                │
             │                  │   assetsbundle/bundle.py               │
             │                  │                                        │
             │                  │ 1. Generate entry.js (piped on STDIN — │
             │                  │    nothing written to the code tree):  │
             │                  │      import * as __owl from "@odoo/owl";│
             │                  │      import * as __m0 from "./path0";   │
             │                  │      ...                               │
             │                  │      odoo.loader.registerNativeModules(│
             │                  │        {"@odoo/owl":__owl,"@spec/0":..})│
             │                  │      (+ hoot-family modules.set aliases)│
             │                  │                                        │
             │                  │ 2. subprocess(esbuild, cwd=odoo_root,  │
             │                  │      --bundle --format=esm --minify    │
             │                  │      --keep-names --target=<target>    │
             │                  │      --external:@odoo/*                │
             │                  │      --external:/web/static/lib/*      │
             │                  │      --external:<EXTERNAL_BARE_SPEC>...│
             │                  │      --alias:<@odoo/* per-lib>...      │
             │                  │      --resolve-extensions=.js,.mjs,... │
             │                  │      --outfile --metafile [--sourcemap]│
             │                  │      timeout=<timeout_s>)              │
             │                  │                                        │
             │                  │ 3. Read output.js + metafile.json      │
             │                  │ 4. Write attachment (+ .meta.json,     │
             │                  │    .esm.js.map siblings):              │
             │                  │  /web/assets/esm/<hash>/<bundle>.esm.js│
             │                  └─────────────────┬──────────────────────┘
             │                                    │
             └───────────────────┬────────────────┘
                                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ Rendered HTML                                                             │
│   pre_nodes:                                                              │
│     <script>/* module_loader.js shim */</script>    (inline)              │
│     <script type="importmap">{imports:{@odoo/*: ...,}}</script>           │
│     <link rel="modulepreload" href=".../specs"> (prod only)               │
│   [legacy bundle, if any]                                                 │
│   post_nodes:                                                             │
│     <script type="module" src=".../esm/<hash>/<bundle>.esm.js"            │
│             data-bridge="<bundle>"></script>                              │
│     <script type="module">import { templates } from @web/core/...</script>│
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ Browser                                                                   │
│   1. Shim executes (sync): globalThis.odoo.loader = new OdooModuleLoader()│
│   2. Import map resolves @odoo/owl etc. to vendored ESM                   │
│   3. Bundle <script type=module> fetches, parses, executes                │
│   4. Bundle entry calls odoo.loader.registerNativeModules({...})          │
│   5. Template module calls odoo.loader.modules.get("@web/core/templates") │
│   6. boot/main.js → boot/start.js → mountComponent(WebClient)             │
└───────────────────────────────────────────────────────────────────────────┘
```

## Declarative ESM registry (`odoo.tools.assets.esm_registry`)

The old hardcoded frozensets in `assetsbundle.py`
(`_ESM_APP_BUNDLES` / `_ESM_ADDON_BUNDLES` / `ESM_BUNDLES` /
`DYNAMIC_ESM_BUNDLES` / `IMPORT_MAP_INCLUDES`) are **gone**. Each module now
declares its own ESM bundle relationships in its `__manifest__.py` under an
`esm` key; the aggregate is built once per process from
`Manifest.all_addon_manifests()` by `esm_registry()`
(odoo/tools/assets/esm_registry.py, returning an `EsmRegistry`
NamedTuple) and invalidated by `invalidate_esm_registry()`,
wired into `AssetsBundle.invalidate_addon_scan_cache` (the canonical
"addons on disk changed" signal from `ir.module.module.update_list()`).

| `esm` manifest key | Purpose (old equivalent) |
|-----|---------|
| `bundles` | This module's esbuild-compiled bundles (old `ESM_BUNDLES` membership) |
| `dynamic_children` | Parent → lazy children pre-registered in the parent's import map for runtime `import()` via `loadBundle` (old `DYNAMIC_ESM_BUNDLES`); declared by the CHILD's module |
| `import_map_includes` | Parent → satellites reusing the parent's import map, skipping esbuild (old `IMPORT_MAP_INCLUDES`); used for test-runner bundles |
| `secondary_import_map_includes` | Parent → satellites loaded as a separate later `<script>`; only the satellite's NEW import-map specifiers merge into the parent's map |

Example:

```python
# web/__manifest__.py — the only manifest using all four keys:
'esm': {
    'bundles': [...14 bundles...],
    'dynamic_children': {'web.assets_web': ['web.assets_clickbot',
                                            'web.assets_emoji']},
    'import_map_includes': {'web.assets_unit_tests_setup':
                            ['web.assets_unit_tests']},
    'secondary_import_map_includes': {'web.assets_web': ['web.assets_tests'],
                                      'web.assets_frontend': ['web.assets_tests']},
}
# web_tour/__manifest__.py — the CHILD declares its lazy bundles under the parent:
'esm': {
    'bundles': ['web_tour.automatic', 'web_tour.interactive', 'web_tour.recorder'],
    'dynamic_children': {'web.assets_web': ['web_tour.automatic',
                                            'web_tour.interactive',
                                            'web_tour.recorder']},
}
# point_of_sale/__manifest__.py — bundles-only (no children/includes).
```

Invariants (same as the old class-level `_validate_esm_config`) are enforced
by `validate_esm_config` (`esm_registry.py`) when the registry is built —
loud by design, so a bad manifest fails the first render/bundle that touches
the registry.  For ALL THREE mappings (`dynamic_children`,
`import_map_includes`, AND `secondary_import_map_includes`):
- Every parent is a registered ESM bundle (in `bundles`)
- Every child is a registered ESM bundle (in `bundles`)
- No duplicate name within a parent's merged children list
Plus, cross-mapping: no bundle is both a dynamic child AND an
import-map-include of the same parent.  Unknown keys under `esm` are rejected
(`_ESM_MANIFEST_KEYS`); a non-Mapping `esm`, a bare-string `bundles`, or a
non-dict mapping value raise `TypeError` earlier in the build.

The esbuild alias table `_LIB_CANDIDATES` (vendored `@odoo/*` paths)
lives on `EsbuildCompiler` (odoo/tools/assets/esbuild.py).
Cross-file invariants enforced at module-load
(`AssetsBundle._validate_external_libs(ODOO_EXTERNAL_LIBS)` in
assetsbundle/bundle.py, invoked at import time; `ODOO_EXTERNAL_LIBS`
itself is defined in odoo/libs/constants.py with a class alias
`IrQweb._ODOO_EXTERNAL_LIBS` in ir_qweb_assets.py):
- Every `ODOO_EXTERNAL_LIBS` entry has a matching `_LIB_CANDIDATES` alias,
  an `EXTERNAL_BARE_SPECIFIERS` membership, or `--external:@odoo/*`
  pattern coverage
- Every `EXTERNAL_BARE_SPECIFIERS` entry has an `ODOO_EXTERNAL_LIBS` URL
  (esbuild emits those imports verbatim; the browser needs the map entry)
- Every `ODOO_EXTERNAL_LIBS` URL exists on disk (URLs under addons absent
  from `addons_path` are skipped)
- Every `_LIB_CANDIDATES` alias target exists on disk (same skip rule — the
  addon scan would otherwise silently skip a typo'd alias and every bundle
  importing it would fail to build)

Bridge export surfaces and import discovery are primarily computed by a
persistent `es-module-lexer` node worker (`odoo/tools/assets/esm_lexer.py` +
`odoo/tools/assets/js/esm_lexer_worker.mjs`, installed by the same
`npm install` that provides esbuild); the historical regex extractor in
`esm_graph.py` remains as the automatic fallback when the worker is
unavailable or a source doesn't lex.

Worker robustness contract (`esm_lexer.py`):
- **POSIX-only.** The worker uses `select` on pipes; on non-POSIX the regex
  path is always used.
- **Hard per-request deadline** (`_REQUEST_TIMEOUT_S`, 10s). The pipes are
  binary + non-blocking and BOTH the request write and the response read are
  gated by a wall-clock deadline (`_write_all` / `_read_line`), so a worker
  that stopped reading (full ~64 KB pipe) or emitted a partial line can never
  block a caller past the budget — a plain `stdin.write` / `readline` could.
- **Respawn-once, then disable.** A worker that dies mid-request is respawned
  and the request retried once; a *spawn* failure (no `node`) disables the
  worker for the process immediately; and `_MAX_CONSECUTIVE_FAILURES` (2)
  consecutive request failures also disable it — so a present-but-broken
  worker degrades the whole process to the regex path fast instead of paying
  the 10s budget on every module (which would be minutes across a big bundle).
- **Discovery parity.** The regex fallback (`_IMPORT_ANY_RE`) covers named /
  default / namespace / mixed (`import D, { y } from …`) / bindingless
  side-effect imports, matching the worker's specifier discovery. `has_default`
  can differ cosmetically for `export { x as default }`, harmless because the
  shim emits the default block unconditionally.

## Logger taxonomy (Python ↔ JS)

Both sides use the same category names so `grep event=bundled` works across
the whole stack when logs are merged.

| Category | Python logger | JS logger | Emitted at |
|----------|---------------|-----------|-----------|
| `bundle` | `odoo.assets.bundle` | — | AssetsBundle lifecycle (init, asset partitioning) |
| `bridge` | `odoo.assets.bridge` | — | Native-to-legacy data-URI bridge construction |
| `esbuild` | `odoo.assets.esbuild` | — | subprocess invoke / success / timeout / fail |
| `loader` | `odoo.assets.loader` | inline `[asset.loader]` | `module_loader.js` shim — idempotent install check and `registerNativeModules` entry counts |
| `attach` | `odoo.assets.attach` | — | ir.attachment writes/reuse for bundle output |
| `fallback` | `odoo.assets.fallback` | — | Prod→debug degradation, circuit open, admin override |
| `lock` | `odoo.assets.lock` | — | PG advisory-lock acquire/release |
| `esm` | `odoo.assets.esm` | `makeAssetLog("esm")` | Import-map + bundle-node generation |
| `env` | — | `makeAssetLog("env")` | Service launcher, wave resolution |
| `js` | — | `makeAssetLog("js")` | Lazy bundle fetch (core/assets.js) |
| `templates` | — | `makeAssetLog("templates")` | registerTemplate / getTemplate |
| `registry` | — | `makeAssetLog("registry")` | Sub-registry creation |

> No `boot` category exists on either side — boot events surface through
> `loader` (Python shim + JS inline) and `env` (JS service launcher).

Event format (Python `log_event`): `event=<name> k1=v1 k2=v2`.
Event format (JS `assetLog`): `[asset.<category>] <...parts>` via `console.debug`.

## Debug toggles

### Python side
```bash
odoo-bin --log-handler=odoo.assets:DEBUG              # full trace
odoo-bin --log-handler=odoo.assets.esbuild:INFO       # esbuild only
odoo-bin --log-handler=odoo.assets.fallback:WARNING   # alerting
```

### JS side (any of)
- URL: `?debug=assets` (or any debug mode containing "assets")
- DevTools: `localStorage.setItem("debug.assets", "1")`
- DevTools: `window.__ODOO_ASSET_TRACE__ = true`

Then enable the DevTools "Verbose" log level so `console.debug` lines
become visible.

## Tunable parameters (ir.config_parameter)

All names are `web.esbuild.<key>`.  Defaults come from the hardcoded
class constants listed in the table and apply when the parameter is
unset or unparseable.

| Key | Default | Class constant (file:line) | Effect |
|-----|---------|---------------------------|--------|
| `timeout_s` | `30` | `EsbuildCompiler._ESBUILD_TIMEOUT_S` (odoo/tools/assets/esbuild.py) | subprocess timeout (seconds) |
| `target` | `"es2023"` | `EsbuildCompiler._ESBUILD_TARGET` (esbuild.py) | esbuild `--target=`. es2023 so esbuild stops downlevel-polyfilling `Promise.withResolvers`; all es2023 features have >18mo support on Chrome 110+/Safari 16+/FF 115+. |
| `source_maps` | `""` | `EsbuildCompiler._ESBUILD_SOURCE_MAPS` (esbuild.py) | esbuild `--sourcemap=<mode>`. `""` (off), `"linked"` (sidecar `.js.map` + `sourceMappingURL` comment — DevTools fetches only when opened), `"external"` (sidecar without comment), `"inline"` (base64 data URL appended — ~2x bundle size). Unknown modes silently fall back to `""`. |
| `cooldown_s` | `60.0` | `IrQweb._ESBUILD_COOLDOWN_S` (ir_qweb_assets.py) | Circuit-breaker cooldown after 1st failure |
| `extended_cooldown_s` | `600.0` | `IrQweb._ESBUILD_EXTENDED_COOLDOWN_S` (ir_qweb_assets.py) | Cooldown after 2nd consecutive failure |
| `lock_retries` | `1` | `IrQweb._ESBUILD_LOCK_RETRIES` (ir_qweb_assets.py) | Advisory-lock retry count |
| `lock_retry_sleep_s` | `0.2` | `IrQweb._ESBUILD_LOCK_RETRY_SLEEP_S` (ir_qweb_assets.py) | Sleep between lock attempts |
| `force_fallback_bundles` | `""` | — | Comma-separated bundle names to force into debug path |

Operators set these via the UI (Settings → Technical → System Parameters)
or programmatically:

```python
env['ir.config_parameter'].sudo().set_param('web.esbuild.timeout_s', '60')
```

## Failure modes

| Symptom | Cause | Signal |
|---------|-------|--------|
| `Failed to resolve module specifier` in browser | import map missing a spec | `odoo.assets.esm DEBUG event=no_native_modules` or validator error at startup |
| esbuild subprocess non-zero exit | Syntax error in an ESM source | `odoo.assets.esbuild WARNING event=failed bundle=<name> exit=<code>` + stderr on next line |
| Requests serve un-minified bundles | Circuit open after failure | `odoo.assets.fallback WARNING event=circuit_open` (at trip) then `DEBUG event=circuit_blocked` (per request) |
| Duplicate CPU on cold start | Multiple workers cold-building same bundle | `odoo.assets.lock INFO event=contention` |
| `[registry] Duplicate add for key "…" … (first registration wins)` console.warn in debug | Module loaded twice (separate instances) — `registry.add` is first-wins + warns, it no longer throws | Missing bridge shim (happy path is an attachment URL; `data:` URI only as the read-only-cursor fallback); check `_build_native_to_legacy_bridge` |
| Test `patchWithCleanup(Klass.prototype, …)` has no effect; production code keeps using unpatched method | Parent + satellite each load their own copy of the same `@web/*` module → `Klass` in test bundle is a different class than the one the production controller instantiates | Add fingerprint logger to module body — two distinct `MODULE LOADED` events means two evaluations. Root cause is usually a sibling manifest (e.g. `spreadsheet/__manifest__.py` pulls `web/static/src/views/graph/graph_model.js` into `spreadsheet.o_spreadsheet`, which is then `('include',)`'d by the satellite test bundle). Fix wires the satellite import through the parent's self-bridge via the `prod_import_map[alias] = shim` override in `_esm_prod_nodes` (`ir_qweb_assets.py`). |

## Cache invalidation on source change — no manual flush needed

**Dev mode rebuilds a bundle on a source-file mtime change; you do NOT need
to `DELETE FROM ir_attachment WHERE name LIKE '%assets_unit%'` before a run.**

The bundle's served URL carries a 7-hex *version* segment
(`/web/assets/<version>/web.assets_unit_tests.min.js`), which is
`AssetsBundle.get_checksum()[0:7]` — a SHA256 over each member's
`unique_descriptor`. That descriptor is `"{url},{last_modified}"`
(`assetsbundle/assets.py`), and `last_modified` is the file's `st_mtime`,
freshly `stat()`'d by `ir_asset._glob_static_file`. So editing any JS source
changes its mtime → changes the checksum → changes the version → the render
path looks up a version with no attachment → **rebuilds** (esbuild for the
ESM bundle, concatenation for the legacy `.min.js`) and writes the new row.
Stale content is impossible once the version differs; the old attachment is
just GC'd later.

Proven empirically (2026-07): with a warm DB (unit-test bundle already built
at version `7752687`), adding one `test(...)` to
`web/static/tests/components/emoji_picker.test.js` and re-running
`--test-tags '/web:WebSuite.test_components[...]' --stop-after-init` — **with
no attachment flush** — ran the new test and bumped the version to `d4cc434`.

The one caveat is the `cache="assets"` **ormcache** on
`ir_qweb._generate_asset_links_cache` / `ir_asset._get_asset_paths`: its key
does NOT include mtime (it's `bundle`/`assets_params`/`rtl`/…), and it's only
bypassed when `dev_mode` contains `"xml"` (`@tools.conditional`,
`ir_qweb_assets.py`). But that ormcache is **in-memory, per-process**, so:

- **`--stop-after-init` test loop** (a fresh process per run, the workflow
  used here): the ormcache starts cold every run, recomputes from fresh
  mtimes, and always reflects edits. No flush, ever.
- **A long-lived server** (`config/p314o19marin.conf`, no `--dev`): the
  ormcache persists in-process, so an edit made while the server is up is
  invisible until the `"assets"` cache clears (server restart,
  Settings → Technical → *Clear cache*, or any asset-attachment unlink). If
  you want live reload against a running server, start it with
  `--dev=xml,reload` — `xml` disables the conditional ormcache and `reload`
  restarts on `.py` change; JS is then picked up on the next request. This is
  a server-lifecycle choice, not a bug, and still needs no manual SQL flush.

## Serving & caching

ESM artifacts are served by a dedicated route
(`web/controllers/binary.py::content_esm_assets`,
`/web/assets/esm/<unique>/<filename>`) with `Cache-Control: immutable` +
one-year `max-age` — safe because every URL is content-addressed (the
`<unique>` segment is a hash of the bytes, or `bridges` with the hash in
the filename). There is deliberately no on-the-fly rebuild on this route:
a missing row is a hard 404, and regeneration happens through the render
path after `ir.attachment.unlink`'s assets-cache clear.

Persistence is decoupled from the request transaction:
`IrQweb._persist_esm_attachment_rows` (bundle/templates/sourcemap) and
`BridgeShimManager._persist_bridges_via_rw_cursor` (loader bridges) create
attachment rows through a dedicated read-write registry cursor that commits
independently, so a request rollback can never orphan an ormcached bundle
URL, and read-only replica renders persist + reference by URL instead of
inlining the bundle. Inlining survives only as the degradation path when no
writable cursor exists at all (read-only test cursors, primary down). Content
reverts (A → B → A) reuse the old row and bump its `write_date`, which
`_gc_esm_assets` uses for newest-per-name liveness.

**Current-cursor guard (deadlock avoidance).** The out-of-band cursor exists
ONLY to survive an HTTP-request rollback. When there is no request — registry
preload / asset pregeneration (`lifecycle._run_post_install_tests` →
`_pregenerate_assets_bundles`), cron, CLI — the current cursor is already the
durable one, and opening a SECOND real `registry.cursor()` on the same thread
self-deadlocks: this thread holds `ir_attachment` locks on the current cursor,
so the second cursor's INSERT waits on a lock only the now-suspended thread can
release (a one-thread/two-cursor cycle Postgres cannot break). Both savers
therefore persist on the current cursor when there is no request. **The two
guards are intentionally NOT identical:**

- `_persist_esm_attachment_rows`: `if _module.current_test or not request:`
  → current cursor. The `current_test` term is required because a plain
  `TransactionCase`'s `registry.cursor()` is a REAL cursor whose out-of-band
  commit would leak rows past the test rollback.
- `_persist_bridge_shims`: `if not request:` → current cursor, else the rw
  cursor **even under a test**. A bare `current_test` branch here would break
  HttpCase tours: the browser fetches loader-bridge URLs on SEPARATE
  TestCursors, and only the `registry.cursor()` path publishes rows visible to
  them; persisting on the render's own cursor left dynamic-child bridges
  unfetchable (`Failed to fetch dynamically imported module`). Do not "unify"
  these guards.

## Service worker

`/web/static/src/service_worker.js` is NOT an `@odoo-module native` file —
it uses `@odoo-module ignore` so the bundler treats it as a classic script,
served via the `/service-worker.js` controller as a plain script (service
workers have limited ESM support — no import maps in some browsers). Do not
migrate without verifying import-map + module-worker support across the
browser-support matrix.

## Loader contract (`module_loader.js`)

The shim installs `globalThis.odoo.loader` as an instance of
`OdooModuleLoader`, a real ES class so Hoot's test helpers can subclass
it via `Object.getPrototypeOf(odoo.loader.constructor)`. The esbuild-generated
entry exercises exactly one method (`registerNativeModules`). Current surface:

### Public API

| Member | Kind | Purpose |
|--------|------|---------|
| `modules: Map<string, any>` | field | Shared map of specifier → module namespace.  Populated by `registerNativeModules`; consulted by bridge shims so sibling bundles see the SAME object for `@web/core/registry` etc. |
| `bus: EventTarget` | field | Loader lifecycle events.  One event today: `rebind` (CustomEvent, `detail.specifiers`), fired when `registerNativeModules` re-binds a known specifier to a DIFFERENT namespace object — a singleton-split signal in production, the expected signal under dev hot-reload.  Subscribe via `odoo.loader.bus.addEventListener("rebind", …)`. |
| `registerNativeModules(map)` | method | Bulk-assign `specifier → namespace` into `modules`.  Last-write-wins on duplicate keys; same-object re-binds stay silent, different-object re-binds dispatch `rebind` + a debug-gated `[asset.loader]` log (never a throw — it runs at bundle top level).  Called by the esbuild-generated entry and by `@web/core/assets.loadESMBundle`. |
| `handleAssetLoadError(target)` | method | One-shot, rate-limited (60 s via `sessionStorage`) `location.reload()` that self-heals a 404'd content-addressed bundle/bridge URL — e.g. a client holding an old page after a GC sweep or `clear_cache("assets")`. Invoked by the capture-phase resource-load `error` listener in the inline reporter. |

### Error reporting

Build-time errors (missing specifier, cycle, syntax) surface from
**esbuild**: the bundle step fails, the circuit breaker trips (see
`ir_qweb._esbuild_cooldowns`), and the request falls back to the
debug per-file serve path — where the browser's native module
resolver surfaces the error directly in DevTools.

The shim additionally inlines a **pre-bundle error reporter**: it
installs `error` / `unhandledrejection` listeners before any module
evaluates and `sendBeacon`s to `/web/observability/js_error`
(throttled to one beacon per (message, line, col) per page).  This
covers the window where the bundle itself fails to parse/evaluate and
`@web/services/error_service` is unreachable; it is the pre-ESM
mirror of `@web/core/errors/error_beacon` — keep payload fields and
endpoint in sync with that module and
`observability.py::js_error`.

The reporter installs three listeners: bubble-phase `error` (runtime
errors, `kind:"error"`), capture-phase `error` (resource-load failures —
a 404'd module/link — which beacon `kind:"asset_load_error"` AND call
`odoo.loader.handleAssetLoadError(target)` for the one-shot self-heal
reload above), and `unhandledrejection`. Each payload carries a
`phase` of `pre_boot` / `post_boot` (from `odoo.isReady`), so a beacon
tells you whether the failure happened before or after the web client
mounted.

## See also

- `ARCHITECTURE.md` — module-wide architecture (boot flow, services, views)
- `CONVENTIONS.md` — coding patterns and gotchas
- `doc/FLOW_DIAGRAM.md` — 14 end-to-end sequence diagrams
