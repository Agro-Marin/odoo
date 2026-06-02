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
                                │  assetsbundle.py:122 / :128
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ AssetsBundle.__init__()   assetsbundle.py:1036                       │
│   files partitioned into:                                            │
│     • self.javascripts         (classic JS; legacy bundle)           │
│     • self.native_modules      (@odoo-module [native]; esbuild fuel) │
│     • self.templates           (XML for QWeb)                        │
│     • self.stylesheets         (SCSS/CSS)                            │
│   Only when bundle name ∈ ESM_BUNDLES.                               │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ HTTP GET /odoo                                                       │
│   ir_qweb._get_asset_nodes(bundle, debug)  ir_qweb.py:3505           │
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
             │                  │   assetsbundle.py:1290                 │
             │                  │                                        │
             │                  │ 1. Generate entry.js (tempfile):       │
             │                  │      import * as __m0 from "./path0";  │
             │                  │      ...                               │
             │                  │      odoo.loader.registerNativeModules │
             │                  │        ({ "@spec/0": __m0, ... });     │
             │                  │                                        │
             │                  │ 2. subprocess(esbuild,                 │
             │                  │      --bundle --format=esm             │
             │                  │      --minify --keep-names             │
             │                  │      --target=<target>                 │
             │                  │      --external:@odoo/*                │
             │                  │      --alias:<per-lib>...              │
             │                  │      timeout=<timeout_s>)              │
             │                  │                                        │
             │                  │ 3. Read output.js + metafile.json      │
             │                  │ 4. Write attachment                    │
             │                  │     /web/assets/esm/<hash>/<bundle>.js │
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
│     <script type="module" src=".../esm/<hash>/bundle.js"                  │
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

## Classification sets (assetsbundle.py)

| Set | Purpose | Edits go to |
|-----|---------|-------------|
| `_ESM_APP_BUNDLES` | Primary app-shell bundles | assetsbundle.py:581 |
| `_ESM_ADDON_BUNDLES` | Feature/addon bundles | assetsbundle.py:603 |
| `ESM_BUNDLES` | Union of the two | assetsbundle.py:676 (derived) |
| `DYNAMIC_ESM_BUNDLES` | Parent → lazy children (pre-registered in import map) | assetsbundle.py:688 |
| `IMPORT_MAP_INCLUDES` | Parent → satellites reusing parent's import map | assetsbundle.py:713 |
| `_LIB_CANDIDATES` | Vendored `@odoo/*` + `luxon` esbuild alias paths | assetsbundle.py:786 |

Invariants enforced at class-load by `_validate_esm_config` (assetsbundle.py:966):
- `_ESM_APP_BUNDLES` and `_ESM_ADDON_BUNDLES` are disjoint
- Every `DYNAMIC_ESM_BUNDLES` parent and child is in `ESM_BUNDLES`
- Every `IMPORT_MAP_INCLUDES` parent and include is in `ESM_BUNDLES`
- No bundle is both dynamic child AND include-satellite of the same parent
- No duplicate names within a children list

Cross-file invariant enforced at module-load (ir_qweb.py:5396) by
`_AssetsBundle._validate_external_libs(set(IrQweb._ODOO_EXTERNAL_LIBS))`:
- Every `_ODOO_EXTERNAL_LIBS` entry has either a matching `_LIB_CANDIDATES`
  alias or is covered by the `--external:@odoo/*` pattern flag

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
| `timeout_s` | `30` | `AssetsBundle._ESBUILD_TIMEOUT_S` (assetsbundle.py:1254) | subprocess timeout (seconds) |
| `target` | `"es2023"` | `AssetsBundle._ESBUILD_TARGET` (assetsbundle.py:1258) | esbuild `--target=`. es2023 so esbuild stops downlevel-polyfilling `Promise.withResolvers`; all es2023 features have >18mo support on Chrome 110+/Safari 16+/FF 115+. |
| `source_maps` | `""` | `AssetsBundle._ESBUILD_SOURCE_MAPS` (assetsbundle.py:1280) | esbuild `--sourcemap=<mode>`. `""` (off), `"linked"` (sidecar `.js.map` + `sourceMappingURL` comment — DevTools fetches only when opened), `"external"` (sidecar without comment), `"inline"` (base64 data URL appended — ~2x bundle size). Unknown modes silently fall back to `""`. |
| `cooldown_s` | `60.0` | `IrQweb._ESBUILD_COOLDOWN_S` (ir_qweb.py:3928) | Circuit-breaker cooldown after 1st failure |
| `extended_cooldown_s` | `600.0` | `IrQweb._ESBUILD_EXTENDED_COOLDOWN_S` (ir_qweb.py:3929) | Cooldown after 2nd consecutive failure |
| `lock_retries` | `1` | `IrQweb._ESBUILD_LOCK_RETRIES` (ir_qweb.py:4120) | Advisory-lock retry count |
| `lock_retry_sleep_s` | `0.2` | `IrQweb._ESBUILD_LOCK_RETRY_SLEEP_S` (ir_qweb.py:4121) | Sleep between lock attempts |
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
| `DuplicatedKeyError` in registry | Module loaded twice (separate instances) | Missing data-URI bridge; check `_build_native_to_legacy_bridge` |
| Test `patchWithCleanup(Klass.prototype, …)` has no effect; production code keeps using unpatched method | Parent + satellite each load their own copy of the same `@web/*` module → `Klass` in test bundle is a different class than the one the production controller instantiates | Add fingerprint logger to module body — two distinct `MODULE LOADED` events means two evaluations. Root cause is usually a sibling manifest (e.g. `spreadsheet/__manifest__.py:22` pulls `web/static/src/views/graph/graph_model.js` into `spreadsheet.o_spreadsheet`, which is then `('include',)`'d by the satellite test bundle). Fix wires the satellite import through the parent's self-bridge via the `prod_import_map[spec] = shim` override at `ir_qweb.py:4637`. |

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
| `modules: Map<string, any>` | field | Shared map of specifier → module namespace.  Populated by `registerNativeModules`; consulted by `data:` URI bridges so sibling bundles see the SAME object for `@web/core/registry` etc. |
| `bus: EventTarget` | field | Free extension point.  No events are dispatched by the loader itself today. |
| `registerNativeModules(map)` | method | Bulk-assign `specifier → namespace` into `modules`.  Last-write-wins on duplicate keys.  Called by the esbuild-generated entry and by `@web/core/assets.loadESMBundle` in cross-doc mode. |

### Error reporting

There is no runtime error reporter.  Missing-specifier, cycle, and
syntax errors surface from **esbuild at build time**: the bundle step
fails, the circuit breaker trips (see
`assetsbundle._esbuild_cooldowns`), and the request falls back to the
debug per-file serve path — where the browser's native module
resolver surfaces the error directly in DevTools.

## See also

- `ARCHITECTURE.md` — module-wide architecture (boot flow, services, views)
- `CONVENTIONS.md` — coding patterns and gotchas
- `doc/FLOW_DIAGRAM.md` — 14 end-to-end sequence diagrams
