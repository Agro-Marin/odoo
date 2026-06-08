# Web Module Architecture

High-level structure, data flow, and component organization for `core/addons/web/`.

> **See also**: `doc/COMPONENT_DIAGRAM.md` — 18 audit areas with file lists,
> invariants, and cross-cutting concerns. `doc/FLOW_DIAGRAM.md` — 14 end-to-end
> sequence diagrams (bootstrap, RPC, auth, view loading, onchange, save, etc.).
> `JS_FILE_INDEX.md` — Complete index of all 630 JS files with purpose descriptions (subtotals partially stale; see file header).
> `DIRECTORY_MAP.md` — All 237 directories mapped to FSD layers and responsibilities.
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

```
core/addons/web/
├── __manifest__.py           # Module metadata + asset bundle definitions
├── controllers/              # 21 controller classes across 23 .py files (HTTP endpoints)
│   ├── dataset.py            #   call_kw + call_button: gateway for ORM RPC
│   ├── session.py            #   authenticate, session_info, logout
│   ├── home.py               #   /, /odoo, /web/login, /web/health
│   ├── binary.py             #   /web/image, /web/content, /web/assets
│   ├── action.py             #   /web/action/load, /run, /load_breadcrumbs
│   ├── export.py             #   /web/export (CSV, XLSX)
│   ├── report.py             #   /report (HTML, PDF, barcode)
│   ├── database.py           #   /web/database (manager, create, drop, backup)
│   ├── webclient.py          #   translations, version_info, bundles, test runners
│   ├── json.py               #   /json/1/ (bearer-auth JSON API)
│   ├── model.py              #   /web/model/get_definitions
│   ├── domain.py             #   /web/domain/validate
│   ├── view.py               #   /web/view/edit_custom
│   ├── pivot.py              #   /web/pivot/export_xlsx
│   ├── profiling.py          #   /web/set_profiling, /web/speedscope
│   ├── webmanifest.py        #   PWA manifest, service worker, offline page
│   ├── vcard.py              #   vCard download
│   ├── settings.py           #   /base_setup/data, /base_setup/demo_active
│   ├── observability.py      #   /web/observability/cwv (Core Web Vitals beacon)
│   ├── export_writers.py     #   Export format base class
│   ├── json_helpers.py       #   JSON API helpers
│   └── utils.py              #   clean_action() and shared helpers
├── models/                   # 21 Python model files (ORM extensions)
│   ├── web_read.py           #   web_read, web_save, web_search_read (core CRUD)
│   ├── web_read_group.py     #   web_read_group (grouped data for views)
│   ├── web_onchange.py       #   onchange() (form change simulation)
│   ├── record_snapshot.py    #   Snapshot diffing for onchange
│   ├── web_search_panel.py   #   Sidebar filter panels
│   ├── ir_http.py            #   session_info(), bootstrap context
│   ├── ir_ui_menu.py         #   load_web_menus() (sidebar)
│   ├── ir_ui_view.py         #   View type metadata
│   ├── ir_model.py           #   Schema introspection
│   ├── ir_qweb_fields.py     #   QWeb image rendering
│   ├── res_users.py          #   User search priority, CAPTCHA
│   ├── res_users_settings.py #   UI density, embedded actions
│   ├── res_users_settings_embedded_action.py # Per-user action config
│   ├── base_document_layout.py # Report layout wizard
│   ├── res_company.py        #   Report style regeneration
│   ├── res_config_settings.py #  web_app_name config
│   ├── res_partner.py        #   vCard export
│   ├── web_read_group_helpers.py # Temporal fill, group expansion formatters
│   ├── web_search_panel_helpers.py # Filter panel helpers
│   ├── properties_base_definition.py # Property field definitions
│   └── web_cwv_metric.py     #   Core Web Vitals storage + retention (RUM Phase 2)
├── static/
│   ├── src/                  # 630 JavaScript/OWL source files (4 at src/ root — env.js, session.js, module_loader.js, service_worker.js — counted in the total)
│   │   ├── boot/             #   App entry points: main.js, start.js (env.js and session.js are at src/ root)
│   │   ├── core/             #   Framework primitives: registry, utils, browser, l10n, network, py_js
│   │   ├── components/       #   Reusable OWL UI components (dropdown, colorpicker, etc.)
│   │   ├── services/         #   Data & input services (orm, hotkey, field, etc.)
│   │   ├── ui/               #   UI overlay services & components (see UI Layer below)
│   │   │   ├── block/        #     Block UI overlay + ui_service
│   │   │   ├── bottom_sheet/ #     Mobile bottom sheet
│   │   │   ├── dialog/       #     Modal dialog + confirmation_dialog + dialog_service
│   │   │   ├── effects/      #     Visual effects (rainbow_man) + effect_service
│   │   │   ├── notification/ #     Toast notifications + notification_service
│   │   │   ├── overlay/      #     Base overlay layer manager + overlay_service
│   │   │   ├── popover/      #     Positioned popover + popover_service
│   │   │   └── tooltip/      #     Data-attribute tooltips + tooltip_service
│   │   ├── fields/           #   68 widget directories (7 subcategories; ~95 registry entries counting view-specific variants)
│   │   │   ├── basic/        #     21 widgets: boolean, char, float, html, integer, text, url, ...
│   │   │   ├── display/      #     8 widgets: badge, gauge, handle, progress_bar, statusbar, ...
│   │   │   ├── media/        #     7 widgets: binary, image, image_url, pdf_viewer, signature, ...
│   │   │   ├── relational/   #     11 widgets + 5 utilities: many2one, many2many_tags, x2many, reference, ...
│   │   │   ├── selection/    #     7 widgets: selection, radio, priority, state_selection, ...
│   │   │   ├── specialized/  #     11 widgets: domain, properties, ace, color_picker, ...
│   │   │   └── temporal/     #     3 widgets: datetime, remaining_days, timezone_mismatch
│   │   ├── views/            #   View types: form, list, kanban, calendar, graph, pivot
│   │   ├── webclient/        #   App shell: navbar, menus, user menu, burger menu
│   │   ├── search/           #   Search bar, facets, filters, group-by, favorites
│   │   ├── model/            #   Client-side relational data model
│   │   ├── public/           #   Public (anonymous) page features
│   │   ├── libs/             #   Internal utility libraries
│   │   ├── polyfills/        #   Browser polyfills
│   │   ├── legacy/           #   Legacy compatibility code
│   │   ├── @types/           #   TypeScript type declarations
│   │   └── scss/             #   ~197 SCSS stylesheets
│   ├── lib/                  # Vendored JS libraries (DO NOT MODIFY)
│   │   ├── owl/              #   OWL component framework
│   │   ├── luxon/            #   DateTime library
│   │   ├── bootstrap/        #   CSS framework
│   │   ├── Chart/            #   Chart.js
│   │   ├── fullcalendar/     #   Calendar library
│   │   └── ...               #   19 vendored libraries total
│   ├── tests/                # JS test files (413 .js incl. 329 *.test.js Hoot suites)
│   └── fonts/                # Web fonts (Google, Inter, Lato, Sign)
├── tests/                    # 36 Python test files (see machine_doc_v1/TEST_TAGS.md)
├── views/                    # XML templates (backend UI, reports)
├── data/                     # XML data fixtures
├── security/                 # Access control (ir.model.access.csv)
├── i18n/                     # Translation files
├── doc/                      # Architecture diagrams for correctness audits
│   ├── COMPONENT_DIAGRAM.md  #   18 audit areas with files, invariants, cross-cutting concerns
│   └── FLOW_DIAGRAM.md       #   14 end-to-end sequence diagrams (bootstrap → save → cache)
├── tooling/                  # ESLint, JSConfig, git hooks
└── machine_doc_v1/           # Machine-consumable documentation (this directory)
```

## JavaScript Architecture

Layered organization under `static/src/`:

| Layer | Directory | Purpose | Files |
|-------|-----------|---------|-------|
| **Boot** | `boot/` | App entry points: main.js, start.js (env.js, session.js, module_loader.js, service_worker.js at src/ root) | 2 JS |
| **Primitives** | `core/` | Registry, utils, browser abstraction, l10n, network, py_js, tree (relocated from components/) | 102 JS |
| **Components** | `components/` | Reusable OWL UI components (dropdown, colorpicker, etc.) — shrank by ~15 after tree utilities moved to core/ | 74 JS |
| **Services** | `services/` | Data & input singletons: orm, hotkey, field, file_upload, sortable, debug, web_vitals, multi_company_recovery, form_dialog_stack, slow_rpc, etc. | 35 JS |
| **UI** | `ui/` | Overlay services & components: dialog, popover, tooltip, notification, effects, block | 20 JS |
| **Fields** | `fields/` | 68 widget directories in 7 subcategories (basic, display, media, relational, selection, specialized, temporal); ~95 registry entries counting view-specific variants | 111 JS |
| **Views** | `views/` | View types: form, list, kanban, calendar, graph, pivot + view utilities + settings | 144 JS |
| **Webclient** | `webclient/` | App shell: navbar, menus, actions, user menu | 54 JS |
| **Search** | `search/` | Search bar, facets, filters, group-by, favorites | 31 JS |
| **Model** | `model/` | Client-side relational data model (Record, StaticList, etc.) | 34 JS |
| **Public** | `public/` | Public (anonymous) page features | 11 JS |

## JavaScript Services

Services are registered in `registry.category("services")` and injected via `useService()`.

### Data Services (`services/`)
| Service | File | Purpose |
|---------|------|---------|
| `orm` | `services/orm_service.js` | ORM gateway — see full API table below |
| `http` | `services/http_service.js` | Low-level HTTP fetch wrapper (GET/POST) |
| `field` | `services/field_service.js` | Field metadata loader (calls `fields_get` via `orm.cache({type:"disk"})`) |
| `name` | `services/name_service.js` | Display name caching with microtask batching; clears cache on `ACTION_MANAGER:UPDATE` (not CLEAR-CACHES) |

#### `orm` full public API

16 methods on the `ORM` class (`orm_service.js:67-416`). All return a Promise.

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

**Methods NOT on `orm`**: `nameSearch`, `name_create`, `readGroup` (use `orm.call(model, "name_search", ...)` etc.). `UPDATE_METHODS` constant (create/write/unlink/web_save/web_save_multi/action_archive/action_unarchive) is declared but **not used inside orm_service** — exported for cache-invalidation consumers.

**`orm.cache({type:"disk"})`** — proxy pattern (`orm_service.js:86`): `Object.assign(Object.create(this), {_cache: options})`. Every `call()` passes `cache: this._cache` to `rpc()`, where `rpcCache.read(table, key, fetcher, options)` is invoked. **table** = python method name (e.g. `"fields_get"`). **key** = `JSON.stringify({url, params})`. Options pass through — `{type:"disk"}` and `{type:"ram"}` both valid; `cache:true` uses defaults.

**`orm.silent`** — same proxy pattern (`orm_service.js:78`) adds `_silent:true` for the downstream error_service to suppress dialogs. **Composable but not chainable with itself**: `orm.silent.cache({type:"disk"})` works; re-invoking `.silent` or `.cache()` re-creates, doesn't stack.

**`orm.dedup`** — same proxy pattern (`orm_service.js:114`) adds `_dedup: true` to subsequent calls. Concurrent callers issuing the same `(url, params)` key share a single in-flight fetch (stampede prevention for **uncached** reads). Redundant when chained onto `.cache(...)` — the cache layer already prevents duplicate fires. Abort semantics are shared: aborting any caller cancels the underlying fetch and rejects every observer with `ConnectionAbortedError`. Never apply to writes.

**`orm.retry(options)`** — same proxy pattern (`orm_service.js:137`) adds `_retry: options` to subsequent calls. Accepts a number (interpreted as retries with default backoff) or a partial config `{retries, baseMs, maxMs}`. Composes with `silent` and `cache`: `orm.silent.cache({type:"disk"}).retry(1).call(...)` is the canonical boot-path-resilient idiom (see `services/field_service.js`, `views/view_service.js`). Caller is responsible for ensuring the call is idempotent — never apply to writes (create/write/unlink/web_save/web_save_multi/web_resequence).

**Context merging rule** (`orm_service.js:151`): `fullContext = {...user.context, ...(kwargs.context||{})}`. Spread order means **caller keys win on collision** — `user.context` values can be overridden, though the keys themselves cannot be deleted (omit from caller context to inherit, set to a new value to override).

**rpc.js settings whitelist** (`rpc.js:23`): `cache, silent, headers, timeout, retry, dedup`. Any other key throws. The previous `xhr` setting (XHR injection escape hatch) was dropped along with the migration to `fetch`. `cache` + `retry` compose: cache wraps retry so warm hits skip the retry layer entirely. `timeout` (milliseconds) installs an `AbortSignal.timeout()` that combines with the caller-controlled abort signal via `AbortSignal.any()`. No `credentials`.

**Error class hierarchy** (`rpc.js:43-92`):
- `NetworkError` (base) — all network/RPC failures
- `RPCError extends NetworkError` — server-returned errors; `{name:"RPC_ERROR", type:"server", code, data, exceptionName, subType}`. **Never retryable** (server-deterministic).
- `ConnectionLostError extends NetworkError` — HTTP 502/503/504, JSON parse failure under an ``application/json`` content-type, missing content-type, or fetch network failure (DNS, CORS, server unreachable). Frontend never sees a status code for these. **Retryable**.
- `ServerOverloadError extends ConnectionLostError` (T2.3, 2026-05-22) — Server returned a non-JSON content-type (typically werkzeug HTML traceback from ``PoolError`` / ``OperationalError``). Carries ``status`` so callers can branch on the actual HTTP code; the message embeds it. Backward-compatible with existing ``instanceof ConnectionLostError`` catchers. **Retryable with a 1000ms backoff floor** so retries don't pile onto an overloaded backend (``SERVER_OVERLOAD_BACKOFF_FLOOR_MS`` in ``rpc.js``).
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
| `multi_company_recovery` | `services/multi_company_recovery_service.js` | Recovers from `AccessError` when the server tags the error context with `suggested_company`. Two strategies: `recoverFromLifecycleError` reloads the page after activating; `recoverFromSaveError` mutates the model's context and activates with `reload:false` to preserve user input. Used by FormController in both onError paths. |
| `form_dialog_stack` | `services/form_dialog_stack_service.js` | Single global counter of currently-open form-in-dialog instances. Subscribes to `AppEvent.FORM_DIALOG_ADD/REMOVE` once at startup; exposes `count` and `isEmpty` getters. Replaces the per-FormController counter that drifted when controllers mounted after a dialog was already open. Read by `beforeVisibilityChange` to suppress tab-switch auto-save when a child form dialog is active. |
| `slow_rpc` | `services/slow_rpc_service.js` | Patience-UX service: shows a sticky `notification.add(_t("This is taking longer than usual…"))` toast when any non-silent RPC exceeds `SLOW_RPC_CONFIG.thresholdMs` (default 5 s, mutable so a future `slow_rpc.threshold_ms` ir.config_parameter can tune it without an API change). Listens passively on `rpcBus` for `RPC:REQUEST` / `RPC:RESPONSE`; success, error, abort, and timeout responses all clear the timer. Pairs with the existing `silent` setting — silent RPCs (boot-time field metadata, action loads, retry-internal calls) opt out of the patience UI just as they opt out of error dialogs. Added 2026-05-04. |

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

The web module ships **native ES modules**. JS reaches the browser through a
two-stage bootstrap:

1. **Inline loader shim** — `ir.qweb._build_loader_shim_js()` reads
   `static/src/module_loader.js` from disk at asset-node generation time,
   minifies it, and emits it as an inline `<script>` tag. This installs
   `window.odoo.loader` BEFORE any `<script type="module">` runs. The file
   itself is **not** included in any asset bundle.
2. **ESM bundle** — `AssetsBundle.esbuild_native_bundle()`
   (`core/odoo/addons/base/models/assetsbundle.py:1018`) invokes esbuild to
   bundle + minify all native ESM files into a single file served via
   `<script type="module">`. At evaluation time the bundle calls
   `odoo.loader.registerNativeModules({...})` so sibling bundles share the
   same singleton module instances.

### Bundle classification

Defined in `AssetsBundle` (`assetsbundle.py:385-531`):

| Constant | Purpose |
|----------|---------|
| `ESM_BUNDLES` | Bundles that go through esbuild. Covers every main webclient bundle (`assets_web`, `assets_frontend`, report and test bundles) plus most addon asset bundles. |
| `DYNAMIC_ESM_BUNDLES` | Parent → lazy-child mapping. Children's specifiers are pre-registered in the parent's import map so runtime `import()` (via `loadBundle`) can resolve them. `@web/*` deps are bridged through `odoo.loader.modules` `data:` URI shims to preserve singleton identity. |
| `IMPORT_MAP_INCLUDES` | Parent → satellite bundles whose specifiers piggyback on the parent's import map. Skips esbuild entirely — used for test-runner bundles that load individual test files on demand. |

### Module marker convention

Every native ESM source carries `/** @odoo-module native */` in its header.
The legacy `/** @odoo-module */` (without `native`) flagged files going
through a Python transform and is now absent from `web/static/src`.
**Zero** `odoo.define()` calls remain in the web module — the refactor is
complete on this side.

### Import alias resolution

`@web/...`, `@odoo/owl`, `@web/fields/...`, and similar aliases are resolved
by esbuild using `--alias` flags generated once per process from the
addon-path scan in `AssetsBundle._get_esbuild_addon_flags()`
(`assetsbundle.py:664`). The alias set is cached via
`_esbuild_addon_scan_cache`.

### `remove` and `after` directives

The manifest uses 29 `remove` tuples to strip files from parent bundles,
plus `after` directives for position-sensitive SCSS insertion. These are
load-bearing for refactors — removing a file from the manifest's `remove`
list silently re-enables it in every bundle that composes the parent.

Notable removals:
- `web.assets_backend` removes `clickbot.js`, `**/*.dark.scss`, entire
  `actions/reports/**/*` (then re-adds `.js`/`.xml` only), and
  `button_box/*.scss`
- `web.assets_frontend` removes `commands/**`, `debug_menu.js`,
  `file_viewer.dark.scss`, `emoji_data.js`, `database_manager.js`
- `web.report_assets_common` removes `utilities_custom_backend.scss` +
  `bootstrap_review_backend.scss` then uses `after` to inject
  `utilities_custom_report.scss` in their place

### Module metadata (`__manifest__.py`)

- `depends: ["base"]` — web is the root addon aside from base
- `auto_install: True` — installs automatically alongside base
- `bootstrap: True` — loaded during server bootstrap before regular addons
- `data:` — 17 XML/CSV files including `webclient_templates.xml`,
  `report_templates.xml`, `web_menus.xml`, `report_layout.xml`,
  `ir_attachment.xml`, `web_security.xml`, `ir.model.access.csv`,
  `neutralize_views.xml`, `speedscope_template.xml`, `memory_template.xml`,
  `speedscope_config_wizard.xml`, `ir_ui_view_views.xml`,
  `res_config_settings_views.xml`, `web_cwv_metric_views.xml`,
  `web_cwv_metric_data.xml`
- `external_dependencies`: none declared (vobject is imported inline in
  `res_partner.py`; server fails to load vcard export if missing)
- `demo`: no demo data

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
| `web._assets_core` | Luxon, session.js, env.js, ui/, services/, components/, core/ — bundled as native ESM via esbuild. **OWL is NOT in this bundle** — it is loaded separately via a non-deferred `<script src="@odoo/owl">` resolved through the import map before the ESM bundle evaluates (see `ir_qweb.py:4084` _get_native_module_nodes). The `module_loader.js` shim is also NOT part of this bundle; it is emitted separately by `ir.qweb._build_loader_shim_js()` as an inline `<script>`. Included only by `web.assets_backend`. |
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
| `web.assets_unit_tests` | All JS test files (except tours and legacy) |
| `web.assets_tests` | Legacy test utilities and tour definitions |
| `web.tests_assets` | **Legacy QUnit-runner aggregator** — includes `web.assets_backend` + QUnit + FullCalendar + ACE + chartjs_lib + clickbot + legacy test helpers. Distinct from the HOOT unit-test bundle chain. |
| `web.__assets_tests_call__` | Internal test-assets composition shim (do not reference directly) |
| `web.qunit_suite_tests` | Legacy QUnit test suite runner |
| `web.assets_clickbot` | Click-everywhere automated UI testing bot |

### Library Bundles

| Bundle | Library | Version |
|--------|---------|---------|
| `web.chartjs_lib` | Chart.js + chartjs-adapter-luxon | 4.5.1 + 1.3.1 |
| `web.fullcalendar_lib` | FullCalendar (Vanilla JS bundle: core + interaction + daygrid + timegrid + list + multimonth), skeleton.css, locales-all | 7.0.0-rc.3 |
| `web.ace_lib` | ACE code editor (Python, XML, QWeb, JS, SCSS, JSON modes) | 1.43.6 |

### Vendored libraries (`static/lib/`)

The version values below are extracted manually from each library's source
file (header comment, `version = "..."` literal, or filename). There are
**no `VERSION.txt` files** in `static/lib/` — when a refactor upgrades any
of these libraries, update both the table here and the version string in
the source file (and add a `VERSION.txt` if you want one to exist).

| Library | Version | Used for |
|---------|---------|----------|
| `ace` | 1.43.6 | Code editor component (ace_field, ir_ui_view ace variant) |
| `bootstrap` | 5.3.8 | SCSS framework + optional JS plugins |
| `Chart` | 4.5.1 | Chart.js — graph view, gauge/journal-dashboard fields |
| `chartjs-adapter-luxon` | 1.3.1 | Luxon date-adapter for Chart.js |
| `diff_match_patch` | forked-from-google-diff-match-patch | Text diff/merge utility |
| `dompurify` | 3.3.1 | HTML sanitization for Html fields and markup helpers |
| `fullcalendar` | 7.0.0-rc.3 | Calendar view engine |
| `hoot` | internal | Odoo's in-house JS test framework |
| `hoot-dom` | internal | DOM helpers for Hoot |
| `luxon` | 3.7.2 | DateTime library (all date/datetime field widgets) |
| `odoo_ui_icons` | 1.2 | Icon font (replaces FontAwesome for most UI icons) |
| `owl` | internal | OWL component framework (loaded non-deferred before ESM bundle via import map) |
| `pdfjs` | 4.8.69 | PDF viewer field |
| `popper` | 2.11.8 | Popover positioning (dropdown, tooltip, popover services) |
| `prismjs` | 1.30.0 | Syntax highlighting in test setup UI |
| `qunit` | 2.9.1 | Legacy test runner (`web.qunit_suite_tests` bundle) |
| `signature_pad` | 5.1.3 | Signature component |
| `stacktracejs` | 2.0-unknown | Traceback annotation in error_utils.js |
| `zxing-library` | 0.21.3 | BarcodeDetector polyfill (barcode scanner) |

> **Three "internal" entries** (`owl`, `hoot`, `hoot-dom`) mean the code is
> maintained in-tree rather than dropped from upstream. Versioning is by git
> commit rather than a released tag.
>
> **`stacktracejs` has `2.0-unknown`** — no canonical upstream release matches
> the drop. Anyone refactoring error handling should not assume `2.0-unknown`
> is a real upstream tag.
>
> **`diff_match_patch` is forked** — upstream is frozen since Google's last
> commit. Don't try to upgrade via npm; the local copy has patches.

## File Counts

| Category | Count |
|----------|-------|
| Python (controllers) | 23 (21 Controller classes + `__init__.py`, `export_writers.py`, `json_helpers.py`, `utils.py`) |
| Python (models) | 22 (21 model files + `__init__.py`) |
| Python (tests) | 39 |
| JavaScript (src) | 630 |
| JavaScript (tests) | 416 (incl. 332 `*.test.js` Hoot suites) |
| JavaScript (vendored libs) | 94 |
| SCSS/CSS | 193 (25 in `static/src/scss/` shared base; remaining 168 co-located with JS components) |
| XML (views/ + data/ + static/src OWL templates) | 275 (12 views + 3 data + 260 OWL templates) |
| i18n (.po + .pot) | 61 |
| Total | ~1,680+ |
