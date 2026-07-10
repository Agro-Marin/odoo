# Web Module Architecture

High-level structure, data flow, and component organization for `core/addons/web/`.

> **See also**: `doc/COMPONENT_DIAGRAM.md` — 18 audit areas with file lists,
> invariants, and cross-cutting concerns. `doc/FLOW_DIAGRAM.md` — 14 end-to-end
> sequence diagrams (bootstrap, RPC, auth, view loading, onchange, save, etc.).
> `DIRECTORY_MAP.md` — All 238 directories mapped to FSD layers and responsibilities.
> `STATE_MANAGEMENT.md` — Decision tree for state patterns, record architecture, typed events.

## Module Identity

- **Name:** Web
- **Technical name:** `web`
- **Category:** Hidden (auto-installed with `base`)
- **Role:** Core webclient — the entire Odoo backend UI

## Layer Diagram

```
Browser
  |
  |  HTTP GET /odoo (SPA bootstrap)
  v
┌─────────────────────────────────────────────────────────┐
│  JavaScript (OWL Components + Services)                 │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐   │
│  │ Views    │  │ Services │  │ UI       │  │Webcli- │   │
│  │ form     │  │ orm      │  │ dialog   │  │ent     │   │
│  │ list     │  │ rpc      │  │ popover  │  │ navbar │   │
│  │ kanban   │  │ field    │  │ tooltip  │  │ menus  │   │
│  │ calendar │  │ hotkey   │  │ notif.   │  │ user   │   │
│  │ graph    │  │ ...      │  │ effects  │  │ menu   │   │
│  │ pivot    │  │          │  │ overlay  │  │        │   │
│  └────┬─────┘  └────┬─────┘  └──────────┘  └────────┘   │
│       │             │                                   │
│       └──────┬──────┘                                   │
│              │ orm.call(model, method, args, kwargs)    │
│              v                                          │
│  ┌───────────────────────────────────┐                  │
│  │ RPC Layer (core/network/rpc.js)   │                  │
│  │ POST /web/dataset/call_kw/{m}/{f} │                  │
│  └───────────────┬───────────────────┘                  │
└──────────────────│──────────────────────────────────────┘
                   │ JSON-RPC 2.0
                   v
┌──────────────────────────────────────────────────────────┐
│  Python (Controllers → ORM → Database)                   │
│                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │ Controllers  │───>│ Models       │───>│ PostgreSQL │  │
│  │ dataset.py   │    │ web_read.py  │    │            │  │
│  │ action.py    │    │ web_read_    │    │            │  │
│  │ session.py   │    │  group.py    │    │            │  │
│  │ binary.py    │    │ web_onchg.py │    │            │  │
│  │ export.py    │    │ ir_http.py   │    │            │  │
│  │ report.py    │    │ ir_model.py  │    │            │  │
│  └──────────────┘    └──────────────┘    └────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Request Flow

1. **Component** calls `orm.create()` / `orm.read()` / `orm.call(model, method, args, kwargs)`
2. **ORM Service** builds URL `/web/dataset/call_kw/{model}/{method}`, merges user context
3. **RPC function** sends JSON-RPC 2.0 POST, optional caching via `rpcCache`
4. **Python controller** (`dataset.py:call_kw`) dispatches to ORM method
5. **ORM model** executes business logic, returns result
6. **RPC** resolves Promise (or rejects with `RPCError`)
7. **Component** updates state, OWL re-renders

## Directory Structure

Top-level layout of `core/addons/web/` (detailed maps are separate docs):

| Path | Contents | Map |
|------|----------|-----|
| `controllers/` | 23 `.py` — HTTP endpoints (21 Controller classes) | `ROUTE_MAP.md` |
| `models/` | 22 `.py` — ORM extensions (web_read, web_read_group, ir_http, …) | `MODEL_MAP.md` |
| `static/src/` | 658 JavaScript/OWL source files across 238 directories (FSD layers) | `DIRECTORY_MAP.md` |
| `static/lib/` | 17 vendored JS libraries — DO NOT MODIFY | versions table below |
| `static/tests/` | 434 `.js` (incl. 378 `*.test.js` Hoot suites) | `TEST_TAGS.md` |
| `tests/` | 44 Python test files | `TEST_TAGS.md` |
| `views/` · `data/` · `security/` · `i18n/` | XML templates, data fixtures, `ir.model.access.csv`, translations | — |
| `doc/` | `COMPONENT_DIAGRAM.md` (18 audit areas) · `FLOW_DIAGRAM.md` (14 sequence diagrams) | — |

The `static/src/` JS layers are summarized in **JavaScript Architecture** below; the full per-directory layer + responsibility map is in `DIRECTORY_MAP.md`.

## JavaScript Architecture

Layered organization under `static/src/`:

| Layer | Directory | Purpose | Files |
|-------|-----------|---------|-------|
| **Boot** | `boot/` | App entry points: main.js, start.js (env.js, session.js, module_loader.js, service_worker.js at src/ root) | 2 JS |
| **Primitives** | `core/` | Registry, utils, browser abstraction, l10n, network, py_js, tree (relocated from components/), lib/ lazy ESM loaders (chartjs, fullcalendar) | 111 JS |
| **Components** | `components/` | Reusable OWL UI components (dropdown, colorpicker, etc.) — shrank by ~15 after tree utilities moved to core/ | 74 JS |
| **Services** | `services/` | Data & input singletons: orm, hotkey, field, file_upload, sortable, debug, web_vitals, multi_company_recovery, form_dialog_stack, slow_rpc, etc. | 37 JS |
| **UI** | `ui/` | Overlay services & components: dialog, popover, tooltip, notification, effects, block | 19 JS |
| **Fields** | `fields/` | 68 widget directories in 7 subcategories (basic, display, media, relational, selection, specialized, temporal); ~95 registry entries counting view-specific variants | 112 JS |
| **Views** | `views/` | View types: form, list, kanban, calendar, graph, pivot + view utilities + settings | 151 JS |
| **Webclient** | `webclient/` | App shell: navbar, menus, actions, user menu | 56 JS |
| **Search** | `search/` | Search bar, facets, filters, group-by, favorites, embedded actions bar | 32 JS |
| **Model** | `model/` | Client-side relational data model (Record, StaticList, etc.) | 42 JS |
| **Public** | `public/` | Public (anonymous) page features | 11 JS |
| **Legacy** | `legacy/` | Legacy compatibility namespace: Resig `Class` inheritance + public-widget loader (`legacy/js/core/`, `legacy/js/public/`) | 6 JS |
| **Vendored-in-src** | `libs/` | FontAwesome 7 icon CSS/webfonts + its JS glue — vendored inside `src/` (unlike `static/lib/`) | 1 JS |

## JavaScript Services

Services are registered in `registry.category("services")` and injected via `useService()`.

### Data Services (`services/`)
| Service | File | Purpose |
|---------|------|---------|
| `orm` | `services/orm_service.js` | ORM gateway — see full API table below |
| `http` | `services/http_service.js` | Low-level HTTP fetch wrapper (GET/POST) |
| `field` | `services/field_service.js` | Field metadata loader (calls `fields_get` via `orm.cache({type:"disk", immutable:true})` — warm hits share one deep-frozen payload instead of deep-copying per caller) |
| `name` | `services/name_service.js` | Display name caching with microtask batching; clears cache on `ACTION_MANAGER:UPDATE` (not CLEAR-CACHES) |

#### `orm` full public API

16 methods on the `ORM` class (`orm_service.js` onward). All return a Promise.

| Method | Python call | Notes |
|---|---|---|
| `call(model, method, args=[], kwargs={})` | any | Lowest level; direct dispatch |
| `create(model, records[], kwargs)` | `create` | |
| `read(model, ids, fields, kwargs)` | `read` | **Short-circuits on empty ids** — no RPC |
| `search(model, domain, kwargs)` | `search` | |
| `searchRead(model, domain, fields, kwargs)` | `search_read` | |
| `searchCount(model, domain, kwargs)` | `search_count` | |
| `unlink(model, ids, kwargs)` | `unlink` | **Short-circuits on empty ids** |
| `write(model, ids, data, kwargs)` | `write` | |
| `webRead(model, ids, kwargs)` | `web_read` | |
| `webSave(model, ids, data, kwargs)` | `web_save` | |
| `webSaveMulti(model, ids, data[], kwargs)` | `web_save_multi` | |
| `webSearchRead(model, domain, kwargs)` | `web_search_read` | |
| `webReadGroup(model, domain, groupby, aggregates, kwargs)` | `web_read_group` | |
| `webResequence(model, ids, kwargs)` | `web_resequence` | **Forces `specification: {}`** if caller omits |
| `formattedReadGroup` / `formattedReadGroupingSets` | same | Result is mutated: each group gets `__domain` built from `Domain.and([domain, __extra_domain])` |

**Methods NOT on `orm`**: `nameSearch`, `name_create`, `readGroup` (use `orm.call(model, "name_search", ...)` etc.). `UPDATE_METHODS` constant (create/write/unlink/web_save/web_save_multi/action_archive/action_unarchive) is exported for cache-invalidation consumers AND used inside orm_service itself: it seeds the private `NON_IDEMPOTENT_METHODS` superset (`orm_service.js`), which `call()` checks to hard-reject `retry`/`dedup`/`cache` on write-class methods (throws before anything reaches the network).

**`orm.cache({type:"disk"})`** — proxy pattern (`orm_service.js`): `Object.assign(Object.create(this), {_cache: options})`. Every `call()` passes `cache: this._cache` to `rpc()`, where `rpcCache.read(table, key, fetcher, options)` is invoked. **table** = python method name (e.g. `"fields_get"`). **key** = `JSON.stringify({url, params})`. Options pass through — `{type:"disk"}` and `{type:"ram"}` both valid; `cache:true` uses defaults. `{immutable:true}` makes warm hits share a single deep-frozen cached payload (`rpc_cache.js` — `immutable ? deepFreeze : deepCopy`) instead of deep-copying per read; only for consumers that never mutate the result (adopted by `field_service`).

**`orm.silent`** — same proxy pattern (`orm_service.js`) adds `_silent:true` for the downstream error_service to suppress dialogs. **Composable but not chainable with itself**: `orm.silent.cache({type:"disk"})` works; re-invoking `.silent` or `.cache()` re-creates, doesn't stack.

**`orm.dedup`** — same proxy pattern (`orm_service.js`) adds `_dedup: true` to subsequent calls. Concurrent callers issuing the same `(url, params)` key share a single in-flight fetch (stampede prevention for **uncached** reads). Redundant when chained onto `.cache(...)` — the cache layer already prevents duplicate fires. Abort semantics are shared: aborting any caller cancels the underlying fetch and rejects every observer with `ConnectionAbortedError`. Never apply to writes.

**`orm.retry(options)`** — same proxy pattern (`orm_service.js`) adds `_retry: options` to subsequent calls. Accepts a number (interpreted as retries with default backoff) or a partial config `{retries, baseMs, maxMs}`. Composes with `silent` and `cache`: `orm.silent.cache({type:"disk"}).retry(1).call(...)` is the canonical boot-path-resilient idiom (see `services/field_service.js`, `views/view_service.js`). Caller is responsible for ensuring the call is idempotent — never apply to writes (create/write/unlink/web_save/web_save_multi/web_resequence).

**Context merging rule** (`orm_service.js`): `fullContext = {...user.context, ...(kwargs.context||{})}`. Spread order means **caller keys win on collision** — `user.context` values can be overridden, though the keys themselves cannot be deleted (omit from caller context to inherit, set to a new value to override).

**rpc.js settings whitelist** (`rpc.js`): `cache, silent, headers, timeout, retry, dedup`. Any other key throws. The previous `xhr` setting (XHR injection escape hatch) was dropped along with the migration to `fetch`. `cache` + `retry` compose: cache wraps retry so warm hits skip the retry layer entirely. `timeout` (milliseconds) installs an `AbortSignal.timeout()` that combines with the caller-controlled abort signal via `AbortSignal.any()`. No `credentials`.

**Error class hierarchy** (`rpc.js`):
- `NetworkError` (base) — all network/RPC failures
- `RPCError extends NetworkError` — server-returned errors; `{name:"RPC_ERROR", type:"server", code, data, exceptionName, subType}`. **Never retryable** (server-deterministic).
- `ConnectionLostError extends NetworkError` — HTTP 502/503/504, JSON parse failure under an ``application/json`` content-type, missing content-type, or fetch network failure (DNS, CORS, server unreachable). Frontend never sees a status code for these. **Retryable**.
- `ServerOverloadError extends ConnectionLostError` — Server returned a non-JSON content-type (typically werkzeug HTML traceback from ``PoolError`` / ``OperationalError``). Carries ``status`` so callers can branch on the actual HTTP code; the message embeds it. Backward-compatible with existing ``instanceof ConnectionLostError`` catchers. **Retryable with a 1000ms backoff floor** so retries don't pile onto an overloaded backend (``SERVER_OVERLOAD_BACKOFF_FLOOR_MS`` in ``rpc.js``).
- `ConnectionAbortedError extends NetworkError` — caller invoked `promise.abort(true)` or an external `AbortController` aborted the signal. `abort(false)` silently cancels without rejection. **Never retryable** (caller intent).
- `ConnectionTimeoutError extends NetworkError` — `AbortSignal.timeout(ms)` fired (settings.timeout exhausted). Carries `url` and `timeoutMs` so callers can decide whether to retry, alert, or escalate. **Retryable**.

### UI Overlay Services (`ui/`)
| Service | File | Purpose |
|---------|------|---------|
| `ui` | `ui/block/ui_service.js` | Viewport size tracking, active element management, block UI |
| `dialog` | `ui/dialog/dialog_service.js` | Modal dialog stack management |
| `overlay` | `ui/overlay/overlay_service.js` | Base overlay layer manager (dialogs, popovers, tooltips) |
| `popover` | `ui/popover/popover_service.js` | Positioned popover with escape/clickaway |
| `tooltip` | `ui/tooltip/tooltip_service.js` | Data-attribute tooltip system |
| `notification` | `ui/notification/notification_service.js` | Toast notifications |
| `bottom_sheet` | `ui/bottom_sheet/bottom_sheet_service.js` | Mobile bottom sheet |
| `effect` | `ui/effects/effect_service.js` | Visual effects (rainbow_man, etc.) |

### Input Services (`services/`)
| Service | File | Purpose |
|---------|------|---------|
| `hotkey` | `services/hotkeys/hotkey_service.js` | Keyboard shortcut registration |
| `command` | `services/commands/command_service.js` | Command palette (Ctrl+K) |
| `file_upload` | `services/file_upload_service.js` | XHR file upload with progress |
| `datetime_picker` | `components/datetime/datetime_picker_service.js` | Date/time picker popover |

### Infrastructure Services
| Service | File | Purpose |
|---------|------|---------|
| `localization` | `services/localization_service.js` | Translation loader (IndexedDB cached, versioned by `registry_hash`) |
| `error` | `services/error_service.js` | Global error handler (`sequence: 1` — starts first, only sequenced service in core) |
| `scss_error_display` | `services/scss_error_display.js` | SCSS compilation error display (admin-only notification) |
| `title` | `services/title_service.js` | Document title management |
| `pwa` | `services/pwa/pwa_service.js` | PWA install prompt |
| `sortable` | `services/sortable_service.js` | Drag-and-drop sorting |
| `tree_processor` | `services/tree_processor_service.js` | Tree data structure processor (deps: `field`, `name`) |
| `web.frequent.emoji` | `services/frequent_emoji_service.js` | Emoji frequency tracking (dotted namespace key) |
| `lazy_session` | `webclient/session_service.js` | Lazy-loaded session info (profile_session, profile_collectors, etc.). Consumed by `profiling` service — refactoring this breaks profiling startup. |
| `multi_company_recovery` | `services/multi_company_recovery_service.js` | Recovers from `AccessError` when the server context carries `suggested_company`. `recoverFromLifecycleError` reloads after activating; `recoverFromSaveError` mutates the model context and activates with `reload:false` to preserve input. Used by FormController's onError paths. |
| `form_dialog_stack` | `services/form_dialog_stack_service.js` | Single global counter of open form-in-dialog instances; subscribes to `AppEvent.FORM_DIALOG_ADD/REMOVE` at startup and exposes `count`/`isEmpty` getters. Read by `beforeVisibilityChange` to suppress tab-switch auto-save while a child form dialog is active. |
| `slow_rpc` | `services/slow_rpc_service.js` | Patience-UX: shows a sticky `notification.add(_t("This is taking longer than usual…"))` toast when a non-silent RPC exceeds `SLOW_RPC_CONFIG.thresholdMs` (default 5 s, mutable). Listens on `rpcBus` for `RPC:REQUEST`/`RPC:RESPONSE`; success, error, abort, and timeout all clear the timer. Silent RPCs opt out, as with error dialogs. |

> Additional webclient-level services: `action`, `menu`, `view`, `currency`,
> `density`, `profiling`, `reloadCompany`, `shareTarget`, etc. These live in `webclient/` or `views/`.

## View Types

Each view type lives in `static/src/views/<type>/`:

| Type | Directory | Multi-record | Purpose |
|------|-----------|-------------|---------|
| Form | `views/form/` | No | Single record editing |
| List | `views/list/` | Yes | Tabular browsing, inline edit, sorting |
| Kanban | `views/kanban/` | Yes | Card columns, drag-drop |
| Calendar | `views/calendar/` | Yes | Event calendar (day/week/month) |
| Graph | `views/graph/` | Yes | Charts (bar, line, pie) — lazy loaded |
| Pivot | `views/pivot/` | Yes | Crosstab analysis — lazy loaded |

Field widgets (68 widget directories across 7 subcategories, ~95 registry entries counting view-specific variants) live in `fields/` (top-level). Import path: `@web/fields/*`.

## Controller Utilities (`views/view_utils.js`)

Shared logic extracted from form, list, and kanban controllers to eliminate duplication:

| Export | Purpose |
|--------|---------|
| `useControllerServices()` | Returns `{ action, dialog, notification, orm, uiHooks }` — replaces 4 `useService()` calls + `makeModelUIHooks()` in each controller |
| `makeModelUIHooks({ action, dialog, notification })` | Builds 8 hook implementations so model/record/list never import UI services directly |
| `computeArchiveEnabled(fields)` | Shared active/x_active writability check (used by list, kanban) |
| `buildActionMenuItems(staticItems, actionMenus)` | Shared filter-sort-map pipeline for action menu items |

**Model UI Hooks** (injected via `makeModelUIHooks`):
`onDisplayOnchangeWarning`, `onDisplayInvalidFields`, `onDisplayUrgentSave`, `onDisplayPropertyWarning`, `onDisplayArchiveAction`, `onConfirmArchive`, `onConfirmDuplicate`, `onDisplayLimitNotification`

> The data layer (`RelationalModel`, `Record`, `DynamicList` in `model/`) calls these hooks
> instead of importing dialog/notification/action services directly. Controllers wire the
> hooks via `useControllerServices()`. This decouples the data layer from UI concerns.

## Asset Pipeline (ESM + esbuild)

The web module ships **native ES modules**, delivered to the browser via an inline `module_loader.js` shim plus an esbuild-bundled `<script type="module">`. Marker convention: every native source carries `/** @odoo-module native */`; **zero** `odoo.define()` calls remain. ESM bundle membership is **declarative**: each module lists its bundles under an `esm` manifest key, aggregated and validated by `odoo.tools.assets.esm_registry.esm_registry()` (the old hardcoded frozensets in `assetsbundle.py` are gone). Full pipeline — loader contract, the `esm` manifest schema (`bundles` / `dynamic_children` / `import_map_includes` / `secondary_import_map_includes`), esbuild flags, import-map bridging, failure modes, and tunable `web.esbuild.*` params — is in **`ESM_BUNDLING.md`**.

### `remove` and `after` directives (manifest bundle composition)

The manifest uses 29 `remove` tuples to strip files from parent bundles, plus `after` directives for position-sensitive SCSS insertion. Load-bearing for refactors — removing a file from a `remove` list silently re-enables it in every bundle that composes the parent.
- `web.assets_backend` removes `clickbot.js`, `**/*.dark.scss`, all of `actions/reports/**/*` (re-adds `.js`/`.xml` only), `button_box/*.scss`
- `web.assets_frontend` removes `commands/**`, `debug_menu.js`, `file_viewer.dark.scss`, `emoji_data.js`, `database_manager.js`
- `web.report_assets_common` swaps `utilities_custom_backend.scss` + `bootstrap_review_backend.scss` for `utilities_custom_report.scss` via `after`

### Module metadata (`__manifest__.py`)
- `depends: ["base"]` · `auto_install: True` · `bootstrap: True` (loaded during server bootstrap, before regular addons)
- `data:` — 17 XML/CSV files (`webclient_templates.xml`, `report_templates.xml`, `web_menus.xml`, `ir.model.access.csv`, `web_cwv_metric_views.xml`, `web_cwv_metric_data.xml`, …)
- `external_dependencies`: none declared (vobject imported inline in `res_partner.py`); no demo data

## Asset Bundles

Defined in `__manifest__.py`. Bundles group JS/CSS/SCSS for specific contexts.

### Main Bundles (served to browser via `t-call-assets`)

| Bundle | Context | Includes |
|--------|---------|----------|
| `web.assets_web` | Full backend | `assets_backend` + `main.js` + `start.js` entry points |
| `web.assets_backend` | Backend components | Bootstrap, OWL, all services, **all views including graph + pivot**, webclient shell |
| `web.assets_frontend` | Public pages | OWL, Bootstrap, core services (no backend views) |
| `web.assets_frontend_minimal` | Early bootstrap | Session bootstrap (session.js), cookies (core/browser/cookie.js), minimal DOM helpers (core/utils/dom/ui.js), lazyloader + minimal_dom (legacy/js/public). **Does NOT contain `module_loader.js`** — the loader shim is emitted inline, not via any bundle. |
| `web.assets_frontend_lazy` | Frontend extended | Full frontend with all components |
| `web.assets_web_dark` | Dark mode | CSS overrides for backend |
| `web.assets_web_print` | Print | Print stylesheet overrides |
| `web.assets_emoji` | Emoji picker | Emoji data (lazy loaded) |
| `web.report_assets_common` | Reports | Common report assets |
| `web.report_assets_pdf` | PDF reports | PDF-specific report assets |

### Internal Sub-Bundles (composition via `include`)

| Bundle | Purpose |
|--------|---------|
| `web._assets_core` | Luxon, session.js, env.js, ui/, services/, components/, core/ — bundled as native ESM via esbuild. **OWL is NOT in this bundle** — it is loaded separately via a non-deferred `<script src="@odoo/owl">` resolved through the import map before the ESM bundle evaluates (see `ESM_BUNDLING.md`). The `module_loader.js` shim is also NOT part of this bundle; it is emitted separately by `ir.qweb._build_loader_shim_js()` as an inline `<script>`. Included only by `web.assets_backend`. |
| `web._assets_helpers` | SCSS functions, mixins, variable definitions |
| `web._assets_bootstrap` | Bootstrap SCSS (shared base) |
| `web._assets_bootstrap_backend` | Bootstrap SCSS (backend variant) |
| `web._assets_bootstrap_frontend` | Bootstrap SCSS (frontend variant) |
| `web._assets_backend_helpers` | Backend-specific SCSS overrides |
| `web._assets_frontend_helpers` | Frontend-specific SCSS overrides |
| `web._assets_primary_variables` | SCSS color/size variables |
| `web._assets_secondary_variables` | SCSS derived variables |

### Test Bundles

| Bundle | Purpose |
|--------|---------|
| `web.assets_unit_tests_setup` | HOOT framework + all backend assets + clickbot |
| `web.assets_unit_tests_setup_ui` | HOOT framework + minimal UI (no backend) — mobile/public test subset |
| `web.assets_unit_tests` | All JS test files (except tours) — the HOOT unit-test bundle |
| `web.assets_tests` | Tour test utilities and tour definitions (loaded on backend + frontend pages via `web.conditional_assets_tests`) |
| `web.assets_clickbot` | Click-everywhere automated UI testing bot |

> **Legacy QUnit chain removed.** The vendored QUnit 2.9.1 runner and the
> `web.tests_assets`, `web.__assets_tests_call__` and `web.qunit_suite_tests`
> bundles (plus the `/web/tests/legacy` controller route and `static/tests/legacy/`
> suite tree) were deleted. All JS unit testing now runs through HOOT
> (`web.assets_unit_tests*`). The two production-relevant legacy suites (`Class`
> and `publicWidget.Widget`) were ported to HOOT under
> `web/static/tests/legacy_js/`.

### Library Bundles

| Bundle | Library | Version |
|--------|---------|---------|
| `web.ace_lib` | ACE code editor (Python, XML, QWeb, JS, SCSS, JSON modes) | 1.43.6 |

> **`web.assets_signature_pad_lib` was removed.** signature_pad is now the
> upstream ESM build resolved through the `signature_pad` import-map bare
> specifier and lazy-loaded via dynamic `import()` in
> `components/signature/name_and_signature.js`. DOMPurify likewise dropped
> its eager UMD `<script>` (was in `web.assets_backend`, html_editor,
> project, and two enterprise manifests) for the `dompurify` bare
> specifier, imported directly by its consumers (html_editor sanitize
> plugin, web_tour, website_forum, ai_website_livechat).

> **`web.chartjs_lib` and `web.fullcalendar_lib` were removed.** Chart.js
> (+ its luxon adapter) and FullCalendar are now real ES modules resolved
> through import-map bare specifiers (`chart.js`, `chartjs-adapter-luxon`,
> `@fullcalendar/core`) and lazy-loaded via dynamic `import()` in
> `core/lib/chartjs.js` (`loadChartJS()`) and `core/lib/fullcalendar.js`
> (`loadFullCalendar()`). No `<script>` injection, no `window.Chart` /
> `window.FullCalendar` globals — importers read the live-bound `Chart` /
> `FullCalendar` exports after the loader resolves. See CONVENTIONS.md
> gotcha #6.

### Vendored libraries (`static/lib/`)

Versions below are extracted manually from each library's source (header
comment, `version = "..."` literal, or filename). There are **no
`VERSION.txt` files** in `static/lib/` — on upgrade, update both this table
and the version string in the source file.

| Library | Version | Used for |
|---------|---------|----------|
| `ace` | 1.43.6 | Code editor component (ace_field, ir_ui_view ace variant) |
| `bootstrap` | 5.3.8 | SCSS framework + optional JS plugins |
| `Chart` | 4.5.1 | Chart.js — graph view, gauge/journal-dashboard fields |
| `chartjs-adapter-luxon` | 1.3.1 | Luxon date-adapter for Chart.js |
| `diff_match_patch` | forked-from-google-diff-match-patch | Text diff/merge utility |
| `dompurify` | 3.3.1 | HTML sanitization (upstream ESM build; `dompurify` import-map external) |
| `fullcalendar` | 7.0.0 | Calendar view engine |
| `hoot` | internal | Odoo's in-house JS test framework |
| `hoot-dom` | internal | DOM helpers for Hoot |
| `luxon` | 3.7.2 | DateTime library (all date/datetime field widgets) |
| `odoo_ui_icons` | 1.2 | Icon font (replaces FontAwesome for most UI icons) |
| `owl` | internal | OWL component framework (loaded non-deferred before ESM bundle via import map) |
| `pdfjs` | 4.8.69 | PDF viewer field (`build/pdf.js` is the upstream ESM build; `pdfjs-dist` import-map external, lazy-loaded via `@web/core/utils/pdfjs.loadPDFJS`; `web/viewer.html` iframe app is self-contained) |
| `popper` | 2.11.8 | Popover positioning (dropdown, tooltip, popover services) |
| `prismjs` | 1.30.0 | Syntax highlighting in test setup UI |
| `signature_pad` | 5.1.3 | Signature component (upstream ESM build; `signature_pad` import-map external) |
| `zxing-library` | 0.21.3 | BarcodeDetector polyfill (barcode scanner) |

> **Three "internal" entries** (`owl`, `hoot`, `hoot-dom`) are maintained
> in-tree, versioned by git commit rather than a released tag.
>
> **`diff_match_patch` is forked** — upstream frozen since Google's last commit;
> the local copy has patches, so don't upgrade via npm.

## File Counts

| Category | Count |
|----------|-------|
| Python (controllers) | 23 (21 Controller classes + `__init__.py`, `export_writers.py`, `json_helpers.py`, `utils.py`) |
| Python (models) | 22 (21 model files + `__init__.py`) |
| Python (tests) | 44 |
| JavaScript (src) | 658 |
| JavaScript (tests) | 434 (incl. 378 `*.test.js` Hoot suites) |
| JavaScript (vendored libs) | 91 |
| SCSS/CSS | 202 (25 in `static/src/scss/` shared base; remaining 177 co-located with JS components) |
| XML (views/ + data/ + static/src OWL templates) | 277 (12 views + 3 data + 262 OWL templates) |
| i18n (.po + .pot) | 61 |
| Total | ~1,810+ |
