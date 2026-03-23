# Native ES Modules Migration Plan

**Goal**: Eliminate the Python regex transpiler by migrating Odoo's JS module system from `odoo.define()` + `require()` to browser-native ES modules with import maps.

**Status**: Phase 1 Complete (3406 modules native across core + enterprise + custom)
**Priority**: High (architectural improvement, enables ecosystem compatibility)

---

## Architecture

### Current (Phase 1 — hybrid native + legacy)

```
Source (.js with @odoo-module native)
  → served AS-IS via static files
  → <script type="importmap"> resolves @web/, @mail/, etc.
  → <script type="module"> bridge registers in odoo.loader.modules
  → legacy modules require() native modules normally

Source (.js with @odoo-module — legacy)
  → Python regex transpiler → odoo.define(name, deps, factory)
  → concatenated into bundle.min.js
  → module_loader.js resolves deps at parse time
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Import map generation | `assetsbundle.py:get_native_module_data()` | Builds `{specifier: url}` entries |
| Native→Legacy bridge | `assetsbundle.py:_build_native_to_legacy_bridge()` | `data:` URI shims with `await __legacyReady` |
| HTML injection | `ir_qweb.py:_get_native_module_nodes()` | OWL pre-load, import map, modulepreload, bridge script |
| Module loader | `module_loader.js` | `_nativePending`, `registerNativeModules()`, `__legacyReady` |
| OWL ESM shim | `owl_esm.js` | Re-exports `globalThis.owl` as named ES exports |
| OWL idempotency | `owl.js` line 4 | `if (exports.__esModule) return;` prevents re-initialization |
| Bundle-aware classification | `assetsbundle.py:ESM_BUNDLES` | Only `web.assets_web` treats modules as native |
| Transpile fallback | `assetsbundle.py:JavascriptAsset.is_transpiled` | Native modules transpiled in non-ESM bundles |
| Bundle-end signal | `assetsbundle.py:js()` | `odoo.__legacyReady_resolve?.()` at bundle end |

---

## Execution Order (Page Load)

```
1. <script> odoo = { csrf_token, debug }        (inline, immediate)
2. <script> odoo.__session_info__ = {...}        (inline, immediate)
3. <script src="owl.js">                         (sync, sets globalThis.owl)
4. <script type="importmap">                     (601 entries + bridges)
5. <link rel="modulepreload" href="...">         (601 hints)
6. <script> __native_module_names__.push(...)     (inline, immediate)
7. <script defer src="bundle.min.js">            (legacy modules + __legacyReady_resolve)
8. <script type="module" data-bridge>            (imports 601 native + registerNativeModules)
```

Steps 1-6 run during parsing. Step 7 runs after parsing (defer). Step 8 runs
after step 7 (module scripts execute after preceding defer scripts in document
order). Bridge shims (`data:` URIs) use `await odoo.__legacyReady` which
resolves at the end of step 7.

---

## Conversion Status

**601 / 603 modules native** in the `web` addon.

| Directory | Native | Total | Notes |
|-----------|--------|-------|-------|
| core/ | 98 | 100 | `dom/ui.js` (multi-bundle), `components.js` ✓ |
| core/l10n/ | 10 | 10 | Complete |
| core/utils/ | 44 | 44 | Complete (all subdirs) |
| services/ | 31 | 31 | Complete |
| components/ | 74 | 74 | Complete |
| views/ | 140 | 140 | Complete |
| fields/ | 110 | 110 | Complete |
| webclient/ | 45 | 45 | Complete |
| ui/ | 20 | 20 | Complete |
| model/ | 33 | 33 | Complete |
| search/ | 31 | 31 | Complete |
| public/ | 11 | 11 | Complete |
| Other (boot, session, etc.) | 4 | 4 | Complete |
| **Total** | **601** | **603** | |

Non-native (correct):
- `module_loader.js` — bootstrap IIFE, creates the module system
- `service_worker.js` — runs in worker context, no import map

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `ESM_BUNDLES` (bundle-aware) | Same file must be native in `web.assets_web` but transpiled in `web.assets_frontend` |
| `is_transpiled` includes native | Native files in non-ESM bundles must be transpiled, not served raw |
| `__legacyReady` at bundle end | Microtask timing unreliable; explicit resolve after all `define()` calls |
| `data:` URI bridge shims | No new HTTP endpoints needed; shims are tiny (~100 bytes each) |
| Bare URLs (no `?v=`) | Versioned URLs cause dual evaluation via relative imports |
| OWL idempotency guard | One-line fix; preserves class identity for `extends Component` |
| `_nativePending` in `define()` | Prevents overlapping bundles from re-defining native modules |
| Full bridge registration | Lazy bundles (`loadBundle()`) need all native modules in `odoo.loader.modules` |

---

## Phase 2: esbuild Production Bundling — COMPLETE

**Status**: Working. 615 native modules bundled in ~50ms into 1.2MB.

### How it works
In production mode (not `debug=assets`), `esbuild_native_bundle()` in
`assetsbundle.py`:
1. Generates an entry point importing all native modules as namespaces
2. Builds `--alias` flags from `odoo.addons.__path__` for bare specifier resolution
3. Runs esbuild: `--bundle --format=esm --minify --external:@odoo/*`
4. Returns bundled JS (includes `await __legacyReady` + `registerNativeModules()`)
5. `_get_native_module_nodes()` injects it as a single `<script type="module">`

Falls through to individual files when esbuild is unavailable.
Debug mode always uses individual files for source-level debugging.

### Metrics
| Metric | Legacy | Phase 1 | Phase 2 |
|--------|--------|---------|---------|
| Build | 320ms | 0ms | 50ms |
| Requests | 1 | 616 | 1 |
| JS size | ~4MB | 5.4MB | 3.2MB |
| HTML | minimal | 220KB | ~5KB |

---

## Phase 3: Remove Legacy Infrastructure (Future)

### Remove transpiler
- Delete `js_transpiler.py` (900 lines)
- Delete `module_loader.js` (371 lines)
- Simplify `assetsbundle.py` — no more transpilation branching
- Remove `odoo.define`, `require` from global scope

### Requirements
- Third-party addons updated (or compatibility shim kept)
- Template loading via fetch() or import assertions
- Tree-shaking, code splitting for lazy routes
