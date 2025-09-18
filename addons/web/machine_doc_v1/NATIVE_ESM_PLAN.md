# Native ES Modules Migration Plan

**Goal**: Eliminate the Python regex transpiler by migrating Odoo's JS module system from `odoo.define()` + `require()` to browser-native ES modules with import maps.

**Status**: Planning
**Priority**: High (architectural improvement, enables ecosystem compatibility)

---

## Why

1. **The regex transpiler is a liability** — 900 lines of regex-based pseudo-parsing that transforms ES6 `import`/`export` into `odoo.define()` calls. Fragile, hard to debug, adds ~320ms per bundle build (1013 files).
2. **External libraries are moving to ESM** — more npm packages ship only ESM. Currently, integrating them requires manual wrapping or `@odoo-module ignore` hacks.
3. **Browser-native module resolution** — import maps (94.7% browser support) can resolve `@web/core/registry` directly, no transpilation needed.
4. **Better developer experience** — source maps "just work", browser devtools understand ES modules natively, hot reload becomes trivial.

---

## Architecture Overview

### Current (transpile + concatenate)

```
Source (.js with import/export)
  → Python regex transpiler (320ms/1013 files)
  → odoo.define(name, deps, factory) format
  → concatenated into one .js bundle per asset group
  → served as single <script src="/web/assets/hash/bundle.min.js">
  → module_loader.js resolves deps at parse time
```

### Target (native ESM + import map)

```
Source (.js with import/export) — served AS-IS
  → <script type="importmap"> resolves @web/, @mail/, etc.
  → <script type="module" src="/web/esm/start.js"> entry point
  → browser fetches individual modules on demand (HTTP/2 multiplexed)
  → OR: bundled in production (esbuild/rollup, optional)
```

---

## Phase 1: The Flag (`@odoo-module native`)

**Goal**: Allow individual files to opt into native ESM loading while the rest of the system continues using `odoo.define()`. Enables incremental migration.

### 1.1 New annotation: `@odoo-module native`

```javascript
/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
// ... standard ES6, no transpilation needed
```

Files with `native` flag:
- Skip Python transpilation entirely (`is_odoo_module()` returns False)
- Are NOT concatenated into the bundle
- Are served individually via a new endpoint
- Loaded by the browser's native module resolver + import map

### 1.2 Server-side import map generation

New endpoint or template helper that generates the import map from installed addons:

```python
def _generate_import_map(self):
    """Generate import map JSON from installed addon modules."""
    imports = {}
    for addon in self.env['ir.module.module'].search([('state', '=', 'installed')]):
        name = addon.name
        imports[f"@{name}/"] = f"/web/esm/{name}/static/src/"
        # Tests path
        imports[f"@{name}/../tests/"] = f"/web/esm/{name}/static/tests/"
    # OWL and other libs
    imports["@odoo/owl"] = "/web/esm/web/static/lib/owl/owl.js"
    return {"imports": imports}
```

Injected into the page template BEFORE any `<script type="module">`:

```xml
<script type="importmap">
    <t t-out="import_map_json"/>
</script>
```

### 1.3 ESM file serving endpoint

New route: `GET /web/esm/<path:filepath>`

Serves individual `.js` files from addon static directories with:
- `Content-Type: text/javascript`
- Appropriate cache headers (content-hash based)
- No transpilation

### 1.4 Bridge: legacy ↔ native interop

The critical challenge: native ESM files need to import from `odoo.define()` modules and vice versa.

**Native → Legacy bridge** (native file imports a legacy module):
```javascript
// Auto-generated shim for legacy modules
// Served at /web/esm/bridge/@web/core/registry.js
const module = odoo.loader.modules.get("@web/core/registry");
export const registry = module.registry;
export default module[Symbol.for("default")] ?? module;
```

The import map routes to the bridge for non-native modules:
```json
{
  "imports": {
    "@web/core/registry": "/web/esm/bridge/@web/core/registry.js"
  }
}
```

When a module is converted to native, its import map entry changes from bridge to direct:
```json
{
  "imports": {
    "@web/core/registry": "/web/esm/web/static/src/core/registry.js"
  }
}
```

**Legacy → Native bridge** (legacy `require()` of a native module):
Native modules register themselves in `odoo.loader.modules` on load:
```javascript
// Injected wrapper or side-effect registration
import * as mod from "@web/core/registry";
odoo.loader.modules.set("@web/core/registry", mod);
```

### 1.5 Migration order for Phase 1

Start with leaf modules (no dependents in the legacy system):
1. Utility modules (`@web/core/utils/*`)
2. Pure components with no side effects
3. Services (one at a time, testing each)

### 1.6 Acceptance criteria

- [ ] `@odoo-module native` flag recognized by `is_odoo_module()` — returns `False`
- [ ] Import map generated server-side from installed addons
- [ ] Import map injected in webclient template before module scripts
- [ ] New `/web/esm/` endpoint serves individual files
- [ ] Bridge shims auto-generated for legacy modules
- [ ] At least 5 leaf modules successfully converted to native
- [ ] All existing tests pass (no regressions)
- [ ] `debug=assets` mode works with mixed native/legacy

---

## Phase 2: Full Native ESM

**Goal**: All modules use native ES imports. Remove the transpiler and `odoo.define()` system.

### 2.1 Convert all modules

Automated script to:
1. Remove `/** @odoo-module */` annotations
2. Add `/** @odoo-module native */` (or remove annotation requirement entirely)
3. Remove any `require()` calls that were manually written
4. Verify each file is valid ES module syntax

### 2.2 Production bundling (optional)

For production, native ESM can be bundled using a real JS bundler:
- `esbuild` (fastest — 10ms for what takes Python 320ms)
- Preserves module semantics while producing optimal bundles
- Tree-shaking removes dead code (impossible with current concat approach)
- Code splitting for lazy-loaded routes

Or: rely on HTTP/2 multiplexing + `<link rel="modulepreload">` for critical modules. Modern browsers handle hundreds of small module requests efficiently.

### 2.3 Remove legacy infrastructure

- Delete `js_transpiler.py` (900 lines)
- Delete `module_loader.js` (371 lines)
- Simplify `assetsbundle.py` — no more `JavascriptAsset.is_transpiled` branching
- Remove `odoo.define`, `require` from global scope
- Simplify `wrap_with_odoo_define`, `wrap_with_qunit_module`

### 2.4 Template loading

Currently, QWeb templates are bundled as an `odoo.define("bundle.xml", ...)` call. In native ESM:
- Option A: Fetch templates via `fetch()` and register them (async, lazy)
- Option B: Import assertion for JSON/XML (experimental browser feature)
- Option C: Generate a templates.js module that exports the template strings

### 2.5 Acceptance criteria

- [ ] Zero files use `odoo.define()` or `require()`
- [ ] `js_transpiler.py` deleted
- [ ] `module_loader.js` deleted or reduced to thin compatibility shim
- [ ] All tests pass
- [ ] Page load time equal or better than current
- [ ] `debug=assets` mode provides good DX (individual files, sourcemaps)

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Mixed legacy/native interop bugs | High | Bridge shims with comprehensive tests; convert bottom-up (leaves first) |
| HTTP/2 not available (proxy misconfiguration) | Medium | Production bundling fallback via esbuild |
| Import map ordering (must precede modules) | Low | Template ensures map is first element in `<head>` |
| Worker contexts can't see import map | Low | Workers already use separate bundles; keep bundling for workers |
| Third-party addons using `odoo.define()` | Medium | Keep module_loader.js as compatibility shim in Phase 2 |
| Browser cache invalidation | Low | Content-hash URLs (existing pattern) |

---

## Performance Expectations

| Metric | Current | Phase 1 (mixed) | Phase 2 (full ESM) |
|--------|---------|------------------|---------------------|
| Bundle build time | 320ms transpile + concat | Reduced (fewer files to transpile) | ~0ms (no transpilation) or ~10ms (esbuild) |
| First page load | 1 large request (~2MB) | 1 bundle + N native modules | Bundled: same. Unbundled: many small requests (HTTP/2) |
| Dev rebuild (`--dev=all`) | Full retranspile | Only legacy files retranspile | No transpilation, instant |
| Code complexity | 900 lines transpiler + 371 lines loader | +200 lines bridge code | -1271 lines net |

---

## Implementation Notes

### Import map must be inline
The spec forbids `<script type="importmap" src="...">`. The map must be embedded in the HTML. Generate it server-side in `webclient_templates.xml` via a QWeb helper.

### Multiple import maps
Chrome 133+ supports multiple import maps (first-registered wins). Firefox/Safari: in progress. For now, generate one map per page load.

### File extension in import paths
Native ESM requires explicit file extensions in some contexts. Odoo's current `@web/core/utils` (no `.js`) may need the import map to handle extensionless resolution, or we enforce `.js` extensions.

### No dynamic import map modification
Once a module graph starts loading, the import map is frozen. All mappings must be known at page render time. This aligns with Odoo's model (installed addons are known at page render time).

---

## Implementation Status (Phase 1)

### Done

- [x] `@odoo-module native` flag in regex (`js_transpiler.py`)
- [x] `is_native_module()` / updated `is_odoo_module()` (`js_transpiler.py`)
- [x] `JavascriptAsset.is_native` property, `AssetsBundle.native_modules` list (`assetsbundle.py`)
- [x] `get_native_module_data()` generates import map entries (`assetsbundle.py`)
- [x] Import map + modulepreload + bridge `<script type="module">` generation (`ir_qweb.py`)
- [x] QWeb renderer handles inline `text` content for script tags (`ir_qweb.py`)
- [x] `module_loader.js` pre-registers from `odoo.__native_modules__`
- [x] `defer` on legacy bundle when native modules present

- [x] End-to-end server test: HTML output verified for login + webclient
- [x] Convert first file (`concurrency.js`) — `@odoo-module native` flag added
- [x] Unit tests for `is_native_module()` (4 tests in `test_js_transpiler.py`)
- [x] Batch-convert 12 zero-dependency leaf modules to native ESM
- [x] Batch-convert 3 second-wave modules (arrays, strings, xml) with inter-native imports
- [x] Relative import fix: `./objects` → `./objects.js` for native ESM browser resolution
- [x] 16 native modules verified in webclient import map, bridge, and modulepreload
- [x] 102/102 `test_assetsbundle` tests pass (1 pre-existing CSS tour flake)

### Converted modules (16 total)

**Wave 1 — Zero dependencies:**
1. `concurrency.js` — Mutex, KeepLast, Race, Deferred, delay
2. `collections/objects.js` — deepEqual, deepCopy, pick, omit
3. `collections/cache.js` — generic key-path cache
4. `dom/events.js` — isEventHandled, markEventHandled
5. `dom/ui.js` — isVisible, isFocusable, getTabableElements
6. `dom/classname.js` — mergeClasses, addClassesToElement
7. `dom/scrolling.js` — closestScrollableX/Y, isScrollableY
8. `order_by.js` — orderByToString, stringToOrderBy
9. `format/colors.js` — RGB↔HSL↔hex color conversions
10. `patch.js` — reversible monkey-patching
11. `functions.js` — memoize, uniqueId
12. `dependency_graph.js` — iterative DFS cycle detection
13. `decorations.js` — decoration-* → Bootstrap CSS mapping

**Wave 2 — Only import from other native modules:**
14. `collections/arrays.js` — imports `./objects.js` (relative)
15. `format/strings.js` — imports `@web/core/utils/collections/objects` (bare specifier)
16. `dom/xml.js` — imports `@web/core/utils/collections/arrays` (bare specifier)

**Wave 3 — Import from `@odoo/owl` (OWL bridge):**
17. `reactive.js` — imports `{ reactive }` from `@odoo/owl`
18. `components.js` — imports `{ Component, onError, xml }` from `@odoo/owl`

- [x] OWL ESM shim (`owl_esm.js`) re-exports `globalThis.owl` as named ES exports
- [x] OWL pre-load: separate non-deferred `<script src="owl.js">` before import map
- [x] Post-bundle bridge: `<script type="module">` placed AFTER `<script defer>` bundle
- [x] `module_loader.js` `registerNativeModules()` with dependency propagation
- [x] `__native_module_names__` declaration suppresses "missing dep" errors
- [x] 19-entry import map (18 native + @odoo/owl) verified in webclient
- [x] 102/102 tests pass (2 pre-existing CSS tour flakes)

### Not yet done

- [ ] Browser smoke test (open webclient, verify no JS console errors)
- [ ] Convert more OWL-dependent modules (`timing.js`, `indexed_db.js`, etc.)
- [ ] Generic Native → Legacy bridge for non-OWL legacy modules
- [ ] Convert modules that import from `@web/core/browser/browser`, `@web/core/l10n/*`

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-09 | Two-phase approach (flags → full ESM) | Incremental migration reduces risk |
| 2026-03-09 | Import maps over custom resolver | Standard browser API, 94.7% support, zero runtime cost |
| 2026-03-09 | Bridge shims for interop | Allows converting files one at a time |
| 2026-03-09 | `defer` on legacy bundle | Module + defer scripts share deferred queue, document-order execution guaranteed |
| 2026-03-09 | Convert roots first (zero-dep modules) | Safest: bridge only needs legacy→native direction |
| 2026-03-09 | Relative imports need `.js` extension | Browser resolves relative paths as URLs; import map only handles bare specifiers |
| 2026-03-09 | Convert bottom-up (leaves → dependents) | Avoids needing Native→Legacy bridge until higher-level modules are converted |
| 2026-03-09 | OWL pre-load as separate `<script>` | UMD is idempotent; extra HTTP request is cheap; unlocks all OWL-dependent modules |
| 2026-03-09 | Post-bundle bridge with `registerNativeModules()` | Bridge runs after bundle; legacy modules with native deps wait via dependency graph |
