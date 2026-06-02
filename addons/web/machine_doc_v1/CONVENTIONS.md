# Web Module Conventions

Module-specific patterns, rules, and gotchas for working in `core/addons/web/`.

> **See also**: `doc/COMPONENT_DIAGRAM.md` — 18 audit areas with key invariants
> to verify per area. `doc/FLOW_DIAGRAM.md` — 14 end-to-end sequence diagrams.

## RPC Convention

**ORM calls from JavaScript go through two gateways:**

```
JS: orm.call(model, method, args, kwargs)
  → POST /web/dataset/call_kw/{model}/{method}
    → Python: dataset.py:DataSet.call_kw()
      → ORM method dispatch

JS: button click in views
  → POST /web/dataset/call_button/{model}/{method}
    → Python: dataset.py:DataSet.call_button()
      → ORM method dispatch + clean_action() on result
```

`call_kw` handles all standard ORM operations (`orm.read()`, `orm.write()`,
`orm.create()`, `orm.search()`, `orm.unlink()`). `call_button` is the second
path, used specifically for UI button actions — it wraps the result through
`clean_action()` before returning.

**x2Many commands from JS follow this encoding** (see `core/odoo/orm/primitives.py:187-272` `Command` IntEnum):

| Command | Tuple | Meaning |
|---------|-------|---------|
| CREATE | `[0, 0, {values}]` | Create new related record (2nd element is always `0`) |
| UPDATE | `[1, id, {values}]` | Update existing related record |
| DELETE | `[2, id, 0]` | Delete and unlink (3rd element is integer `0`, not `false`) |
| UNLINK | `[3, id, 0]` | Unlink without deleting |
| LINK | `[4, id, 0]` | Link existing record |
| CLEAR | `[5, 0, 0]` | Clear all relations |
| SET | `[6, 0, [ids]]` | Replace all with id list |

The unused slots are the **integer `0`**, not `false` — RPC payloads must send literal zeros. JS clients sometimes send `false` and the server coerces, but relying on that is undefined behaviour in a refactor context.

## Specification Pattern

The `web_read`, `web_save`, and `web_search_read` methods accept a `specification`
dict that mirrors the view's field tree. This controls which fields are fetched and
how relational fields are recursively resolved:

```python
# Example specification for a form view
specification = {
    "name": {},                           # scalar field
    "partner_id": {"fields": {            # many2one: fetch sub-fields
        "display_name": {},
        "email": {},
    }},
    "line_ids": {"fields": {              # one2many: fetch sub-fields
        "product_id": {"fields": {"display_name": {}}},
        "quantity": {},
        "price_unit": {},
    }, "limit": 40, "order": "sequence"},
}
```

When modifying view definitions, the specification must match or the frontend
will receive incomplete data.

## Controller Patterns

### Auth Types (web module)
- `auth='user'` — Requires authenticated session (most RPC endpoints)
- `auth='public'` — Works with or without session (images, assets, frontend)
- `auth='none'` — No session handling at all (health, login, database ops)
- `auth='bearer'` — Bearer token (JSON API only)

Other addons register additional auth methods via `_auth_method_*` (e.g.
`outlook` in mail_plugin, `calendar` in calendar). The web module itself
uses only the four above.

### Readonly Flag
Many routes declare `readonly=True` which routes them to a read replica if configured.
Write operations (create, write, unlink, button clicks) use `readonly=False` (default).

The `call_kw` route uses a dynamic `readonly=_call_kw_readonly` function
(`controllers/dataset.py:15-26`) that walks the target model's MRO looking
for a `_readonly` attribute on the named method (set by the `@api.readonly`
decorator). Defaults to `False` when the attribute is absent. Callers adding
new read-only ORM methods must decorate them with `@api.readonly` for the
route to route to a replica.

### JSONRPC vs HTTP
- `type='jsonrpc'` (JSONRPC): Request/response wrapped in JSON-RPC 2.0 envelope. Used for data operations.
- `type='http'` (HTTP): Standard HTTP. Used for file downloads, page renders, binary content.

> Note: Routes without `methods=[...]` accept ALL HTTP methods (GET, POST, etc.).
> Only routes with explicit `methods=['GET']` or `methods=['POST']` are method-restricted.

## JavaScript Patterns

### Service Injection
```javascript
setup() {
    this.orm = useService("orm");
    this.notification = useService("notification");
}
```

### ORM proxy idioms

The ORM exposes three composable proxy modifiers (`silent`, `cache`, `retry`)
that thread settings through to `rpc()`. Each returns a fresh
`Object.create(this)` view; the base ORM is never mutated.

```javascript
// Suppress error dialogs for a single call
await orm.silent.read("res.partner", [id], ["name"]);

// Disk-cache a fields_get with one retry on transient failure
await orm.cache({ type: "disk" }).retry(1).call(model, "fields_get", []);

// Compose all three for a boot-path read
await orm.silent.cache({ type: "disk" }).retry(1)
    .webSearchRead("res.partner", domain, {});
```

**Composition rules**:
- Order-independent: `cache(opts).retry(1)` and `retry(1).cache(opts)`
  produce identical settings.
- Reusable: store the chain in a variable to apply identical settings
  to many calls.
- `silent` is a getter; `cache(options)` and `retry(options)` are methods
  taking either a primitive (`retry(2)`) or a partial config
  (`retry({ retries: 2, baseMs: 100, maxMs: 1000 })`).

### When to use `retry`

Apply only to **idempotent reads** where transient failure (proxy hiccup,
brief 503, pool exhaustion, worker restart during deploy) cascades into
broken UX with no user recovery action. Never apply to writes — a partial
server-side mutation could be re-applied.

| Call site | Reason | Budget |
|---|---|---|
| `services/currency.js getCurrencyRates` | Cold-cache failure breaks monetary formatting page-wide | `retry: 1` |
| `services/field_service.js loadFields` | Cold-cache `fields_get` failure prevents any view from rendering for the model | `retry: 1` |
| `views/view_service.js loadViews` | Cold-cache `get_views` failure prevents any view from rendering | `retry: 1` |
| `webclient/actions/action_service.js _getAction` | Cold-cache `/web/action/load` failure breaks navigation — every menu click, button, and breadcrumb hop hits this path | `retry: 1` |

**Default budget rationale** (`retry: 1`): caps user-perceived delay on
persistent outage at one backoff interval (~200ms). Higher budgets can
chain into multi-second hangs visible as "the app feels frozen". Tune
upward (`retry: { retries: 3 }`) only when the call is on a background
path the user doesn't see directly.

### Model Coordinators

Lifecycle axes are formalized via small SignalStore-extending coordinator
classes rather than bare boolean flags. Each owns its state machine, exposes
``isActive`` / ``isLoading`` / ``status`` getters, and centralizes entry/exit
in a single ``run(fn)`` / ``enter()`` / ``exit()`` API so consumers cannot leak
the flag past the operation's lifetime.

| Coordinator | File | Replaces | Used by |
|---|---|---|---|
| `RelationalModelLoadCoordinator` | `model/relational_model/load_coordinator.js` | (none — never had a bare flag) | `model.load()` |
| `UrgentSaveCoordinator` | `model/relational_model/urgent_save_coordinator.js` | the `model._urgentSave` bool + `_withUrgentSaveScope` helper | `record.update`, `record._update`, `record.checkValidity`, `record_save.save`, `dynamic_list._askChanges`, `record.urgentSave` |
| `SampleDataCoordinator` | `model/sample_data_coordinator.js` | the `model.useSampleModel` bool (kept as backward-compat getter/setter) | pivot_controller, list_renderer, list_keyboard_nav, list_controller, list_styling, kanban renderer (read); PivotModel, GraphModel (write) |
| `FormSaveCoordinator` | `views/form/form_save_coordinator.js` | per-controller `isSaving` + `record.isDirty` plumbing | form_controller (9 entry points) |

**`multiEdit` is NOT a coordinator** — it is a config-time-only
boolean assigned once during model construction (from
`list_arch_parser.multiEdit` in `list_controller.modelParams`) and
read at 4 sites in views/list/ (`list_keyboard_edit`,
`list_styling`, `list_keyboard_nav`) for readonly evaluation. It never
mutates at runtime, so there is no state machine to formalize.

### Feature Flags

Pure-function API at `@web/services/feature_flags` for gating
behaviour without bespoke `odoo.debug` / `localStorage.getItem` /
`?debug=...` plumbing scattered across the codebase.

**Resolution cascade** — first source wins:

| # | Source | Purpose |
|---|---|---|
| 1 | URL `?features=name:value,name2,-name3` | One-off A/B / reproduction; highest priority |
| 2 | `localStorage["feature.<name>"]` | Per-device persistent override (dev / on-call) |
| 3 | `session.feature_flags[<name>]` | Server default, from `ir.config_parameter` rows with `web.feature.` prefix |
| 4 | `options.default` | Call-site fallback (defaults to `false`) |

**Usage**:

```js
import { featureFlag } from "@web/services/feature_flags";

if (featureFlag("perf_marks", { default: false })) {
    performance.mark("model:load:start");
}
```

**Server config**: set an `ir.config_parameter` row keyed
`web.feature.<flag_name>`. The value string is parsed with the same
literal set as URL / localStorage tokens (`true` / `false` / `null` /
signed integer / float / otherwise string).

**Convention**: flag names are `snake_case` without `.`, `:`, `,`, or
`;` (those are reserved for the URL parser). Names are free-form —
registration is not required — but consider documenting any
production-load-bearing flag in this section once introduced.

### Registry System
Components, views, fields, services are all registered in named registries.
The 4 most frequently-used categories are:

- `registry.category("services")` — Service definitions
- `registry.category("views")` — View type implementations
- `registry.category("fields")` — Field widget implementations
- `registry.category("actions")` — Client action components

The web module itself registers into ~30 categories total, including:
`main_components`, `systray`, `user_menuitems`, `error_handlers`,
`error_dialogs`, `error_notifications`, `dialogs`, `debug`, `debug_section`,
`command_categories`, `command_provider`, `command_setup`, `effects`,
`favoriteMenu`, `cogMenu`, `formatters`, `parsers`, `form_compilers`,
`view_widgets`, `public_components`, `public.interactions`,
`sample_server`, `shared_components`, `color_picker_tabs`,
`action_handlers`, `group_config_items`. Use
`grep -rn 'registry.category(' static/src` to see the full current set —
new categories get added without a schema change.

### Field Widgets
Field widgets live in `static/src/fields/` (top-level, organized into 7 subcategories:
`basic/`, `display/`, `media/`, `relational/`, `selection/`, `specialized/`, `temporal/`).
Each field type (char, integer, many2one, etc.) has a directory with its component,
extractors, and optional variants. There are 68 widget directories (~95 registry entries
counting view-specific variants like `list.text`, `form.phone`).
Import path: `@web/fields/*` (e.g. `@web/fields/basic/char/char_field`).

**Multi-key registrations — refactor hazard.** A single widget file often
registers under multiple keys. Renaming or moving a widget without grep-
auditing every `.add("<key>", ...)` call can silently break views. Known
multi-key registrations in the base fields:

| File | Registry keys |
|---|---|
| `basic/text/text_field.js` | `text` + `list.text` |
| `basic/url/url_field.js` | `url` + `form.url` |
| `basic/email/email_field.js` | `email` + `form.email` |
| `basic/phone/phone_field.js` | `phone` + `form.phone` |
| `media/binary/binary_field.js` | `binary` + `list.binary` |
| `relational/many2many_tags/many2many_tags_field.js` | `many2many_tags` + `calendar.one2many` + `calendar.many2many` + `form.many2many_tags` |
| `relational/many2one/many2one_field.js` | `many2one` + `res_partner_many2one` |
| `relational/x2many/x2many_field.js` | `one2many` + `many2many` (filename misleads) |
| `relational/x2many/list_x2many_field.js` | `list.one2many` + `list.many2many` |
| `specialized/ace/ace_field.js` | `ace` + `code` |
| `specialized/ir_ui_view_ace/ace_field.js` | `code_ir_ui_view` (NOT `ace`) |
| `specialized/properties/card_properties_field.js` | `kanban.properties` + `hierarchy.properties` |
| `basic/copy_clipboard/copy_clipboard_field.js` | `CopyClipboardButton` + `CopyClipboardChar` + `CopyClipboardURL` (CamelCase aliases) |
| `display/percent_pie/percent_pie_field.js` | `percentpie` (no underscore) |
| `display/stat_info/stat_info_field.js` | `statinfo` (no underscore) |
| `display/progress_bar/progress_bar_field.js` | `progressbar` (no underscore) |

Before renaming a widget file, run `grep -rn 'registerField(' addons/` to enumerate every key a file registers. Registration uses the `registerField()` helper from `@web/fields/_registry`; the older `registry.category("fields").add(...)` pattern survives in only two sites — `static/src/fields/_registry.js` and `static/src/fields/basic/html/html_field.js` — so grepping for it will miss everything else.

## Test Conventions

### Tag Structure
Every test class uses `@tagged()` with:
1. **Layer tag** (required): `web_unit`, `web_http`, `web_tour`, `web_js`, `web_perf`, `web_benchmark`
2. **Topic tag** (required): `web_health`, `web_login`, `web_image`, etc.
3. **Install phase**: `at_install` (default) or `post_install` + `-at_install`

```python
@tagged('web_http', 'web_health')           # at_install (default)
class TestHealth(HttpCase): ...

@tagged('post_install', '-at_install', 'web_tour', 'web_login')
class TestLoginTour(HttpCase): ...
```

### Test Base Classes
- `TransactionCase` — For unit tests (`web_unit`). Rolled-back transaction per test.
- `HttpCase` — For HTTP tests (`web_http`). Has `url_open()` for request testing.
- `HttpCase` + `start_tour()` — For browser tours (`web_tour`). Runs JS tour in headless browser.

### Running Tests
```bash
# Fast feedback (~30s)
--test-tags='web_unit' -u web

# Single topic
--test-tags='web_image' -u web

# All except slow JS/tours
--test-tags='/web,-web_js,-web_tour,-click_all'
```

See `machine_doc_v1/TEST_TAGS.md` for full reference.

## Model Extension Pattern

The web module extends `base` (the abstract base model) with methods that
ALL models inherit. This is how `web_read()`, `web_save()`, `onchange()`, etc.
become available on every Odoo model:

```python
class Base(models.AbstractModel):
    _inherit = 'base'

    def web_read(self, specification):
        """Available on every model because base is inherited."""
        ...
```

When adding a new web-facing method, extend `base` in the appropriate file
under `models/` (group by concern: CRUD in `web_read.py`, grouping in
`web_read_group.py`, etc.).

## File Organization Rules

### Controllers
- One controller class per file (occasionally two for export format subclasses)
- File name matches the URL namespace: `session.py` → `/web/session/*`
- Helper functions and utilities go in `controllers/utils.py`

### Models
- Grouped by concern, not by ORM model name
- `web_read.py` = CRUD, `web_read_group.py` = grouping, `web_onchange.py` = form changes
- `ir_*.py` files extend framework models (views, menus, HTTP, QWeb)
- `res_*.py` files extend user/company/partner models

### JavaScript
- `static/src/boot/` — App entry points (env, main, session, start)
- `static/src/core/` — Framework primitives: registry, utils, browser, l10n, network, py_js
- `static/src/components/` — Reusable OWL UI components (dropdown, colorpicker, etc.)
- `static/src/services/` — Data & input services (orm, hotkey, field, file_upload, etc.)
- `static/src/ui/` — UI overlay services & components (dialog, popover, tooltip, notification, effects, block)
- `static/src/fields/` — 68 widget directories in 7 subcategories (basic, display, media, relational, selection, specialized, temporal); ~95 registry entries counting view-specific variants
- `static/src/views/` — View type implementations (form, list, kanban, calendar, graph, pivot) + view utilities
- `static/src/webclient/` — App shell (navbar, menus, action container)
- `static/src/search/` — Search bar and filter components
- `static/src/model/` — Client-side relational data model (Record, StaticList, DynamicList, etc.)
- `static/src/public/` — Public (anonymous) page features

### Static Libraries (DO NOT MODIFY)
Everything under `static/lib/` is vendored third-party code.
Never edit these files. If a library needs updating, replace the entire directory.

### OWL component file convention

An OWL component is a co-located trio:

```
static/src/<layer>/<name>/
    <name>.js       # Component class (`this.static.template = "<module>.<Name>"`)
    <name>.xml      # QWeb template matching the `static.template` key
    <name>.scss     # Optional component-scoped styles
```

About 255 of the 649 JS files in `static/src/` (~39.3%) have a sibling `.xml`.
Templates are registered by the asset pipeline — the manifest's glob
patterns (e.g. `web/static/src/fields/**/*`) pull `.js`, `.xml`, `.scss`
together, and `ir.qweb` collects every `.xml` into the template registry
so OWL can resolve `static.template = "web.CharField"` to the XML file's
`<t t-name="web.CharField">`.

When refactoring a widget:
1. Move/rename the `.js`, `.xml`, and `.scss` together
2. Update `this.static.template` in the `.js` if the template name changes
3. Update the `t-name` attribute in the `.xml`
4. Search all XML files for `t-name="<oldname>"` — templates can inherit
   across file boundaries

## Gotchas

1. **`web_read` is NOT `read`** — `read()` returns raw field values. `web_read()` recursively
   resolves relational fields per specification. Frontend always uses `web_read`.

2. **`onchange` happens server-side** — The JS form view sends the entire form state to
   `onchange()` which simulates the change in a pseudo-record, computes dependents,
   and returns a diff. It does NOT save to the database.

3. **SCSS order matters; JS order mostly doesn't** — SCSS files in `__manifest__.py`
   asset lists are concatenated in order, so variable definitions must come before rules
   that reference them. JS bundles in `AssetsBundle.ESM_BUNDLES` (nearly every webclient
   bundle: `assets_web`, `assets_backend`, `assets_frontend`, report/test bundles, most
   addon asset bundles) are built by **esbuild**, which derives load order from `import`
   statements, not manifest order. Non-ESM bundles still concatenate JS in order. See
   `ESM_BUNDLES` (assetsbundle.py:676), `DYNAMIC_ESM_BUNDLES` (assetsbundle.py:688),
   and `IMPORT_MAP_INCLUDES` (assetsbundle.py:713) before relying on positional placement.

4. **`readonly=True` on routes** — This is not about user permissions. It tells the
   load balancer/proxy to route to a read replica. A `readonly=True` route that
   accidentally writes will corrupt data on replicated setups.

5. **Image URL variants** — `/web/image/` has 17 URL patterns that all resolve to
   `content_image()`. `/web/content/` has another 7. When matching or rewriting image
   URLs, account for all variants (by xmlid, by id, by model/id/field, with/without
   dimensions, with/without filename).

6. **Lazy-loaded libraries (not views)** — Graph and Pivot view code lives in the
   main `assets_backend` bundle; there is NO `assets_backend_lazy` bundle. What IS
   lazy-loaded is the *Chart.js library*: `views/graph/graph_renderer.js` calls
   `loadBundle("web.chartjs_lib")` the first time a graph renders. Pivot export has
   no analogous lazy-load (no `loadBundle` / `loadJS` in `views/pivot/` or
   `views/list/export_all/`); XLSX export is server-side via the
   `/web/pivot/export_xlsx` controller. When adding code that depends on a heavy
   library, prefer `loadBundle()` over adding the library to the main bundle.

   **`loadBundle` vs `loadJS` — which to use?** `core/assets.js` exports both;
   they are *not* alternatives. `loadBundle` fetches `/web/bundle/<name>`, parses
   the manifest's CSS/JS/ESM list, and dispatches each non-ESM JS file through
   `loadJS`. The decision is about **whether the asset belongs in the manifest at all**:

   - **Internal vendored libraries** (anything under `<addon>/static/lib/...`
     or `<addon>/static/src/.../libs/...`): declare a bundle in
     `__manifest__.py` and call `loadBundle("<addon>.assets_<lib>_lib")`.
     Benefits: asset hashing for cache-busting, integration with the asset
     pipeline's circuit breaker and observability log
     (`makeAssetLog("js")`), single source of truth in the manifest.
     Examples: `web.assets_signature_pad_lib`,
     `survey.assets_chartjs_datalabels_lib`, `web.ace_lib`, `web.chartjs_lib`,
     `web.fullcalendar_lib`.

   - **External SDKs delivered via vendor CDN** (payment processors, Maps
     APIs, video player APIs, reCAPTCHA, etc.): use `loadJS(url)` directly.
     The vendor handles caching, hashing, version updates, and licensing
     attribution. Examples: PayPal SDK, Adyen SDK, Google Maps, YouTube
     IFrame API, Vimeo player, Leaflet from unpkg.

   **Edge cases worth documenting at the call site**:

   - `delivery_mondialrelay` vendors a slim jQuery (`jquery.slim.min.js`)
     because the external Mondial Relay widget requires the global
     `window.jQuery` and the fork has otherwise removed jQuery. Loaded via
     `loadJS` of a static path — exception because the consumer is a
     third-party widget contract.

   - `im_livechat/embed/external/emoji_loader_patch` calls
     `loadJS(url("/im_livechat/emoji_bundle", undefined, {origin: livechatData.serverUrl}))`
     — cross-origin to the embedded site's livechat server, not our
     `/web/bundle/...` endpoint, so `loadBundle` cannot resolve it.

   **Don't `loadJS` something that is already eager-loaded.** A library already
   declared in `web.assets_backend` (or its ancestors) is in the page's initial
   bundle; calling `loadJS(url)` on it after page load is a no-op at best and a
   re-evaluation hazard at worst. Example:
   `mail/static/lib/selfie_segmentation/selfie_segmentation.js` ships in
   `web.assets_backend` (mail/__manifest__.py:149).

7. **`CLEAR-CACHES` on result-set removal is model-scoped on BOTH layers.** Any RPC
   whose method removes records from the model's result sets — `unlink`,
   `action_archive`, `action_unarchive` — broadcasts `CLEAR-CACHES` with
   `model: <affected model>` and
   `tables: ["web_read", "web_search_read", "web_read_group"]`.

   **RAM cache** (`rpc_cache.js:RamCache.invalidateByModel`) uses a
   per-table `model → Set<key>` reverse index populated at
   `write(table, key, value, model)` time; invalidation is O(1) lookup
   + O(matched) delete, independent of the table's total entry count.
   Entries written without a `model` argument (session_info,
   `/web/action/load`, `get_views`, …) are correctly invisible to
   `invalidateByModel` — those flows use `invalidate(table)` instead.

   **IndexedDB cache** (`indexed_db.js:invalidateByModel`) uses
   `openCursor` and checks `cursor.value.model === <model>`. The model
   name is stored plaintext alongside the encrypted ciphertext as
   `{ciphertext, iv, model}` (model names appear in the URL and are
   not secret).

   **Pre-migration IDB entries** lack the `model` property on their value, so
   `invalidateByModel` skips them. They remain reachable for `invalidate(table)`
   and get rewritten as responses come back through the cache.

   Method-set source of truth:
   `services/result_set_cache_invalidator_service.js:31`
   `RESULT_SET_REMOVING_METHODS`. Emission site:
   `services/result_set_cache_invalidator_service.js:84`. The listener
   lives in a dedicated service (not `relational_model.js`) so wiring is owned
   by env lifecycle — one subscription per page, one per Hoot test, torn down
   with the env. See `doc/FLOW_DIAGRAM.md` Flow 14 for the full invalidation chain.

   **Write/create methods are intentionally excluded.** `create` / `write`
   / `web_save` / `web_save_multi` return the updated record and let the
   model self-maintain its cache via the normal response path
   (Plan-C envelope versioning handles freshness on subsequent reads). A
   broad-mutation bridge breaks the create→back-nav stale-then-fresh display
   tested by `list_view.test.js` "cache web_search_read (onUpdate called after
   another load)". The regression guard
   (`list_view_performance.test.js` "non-removing RPC:RESPONSE does not
   emit CLEAR-CACHES") asserts every write-class method stays excluded.

8. **Session info embedded in HTML** — `session_info()` is JSON-serialized into a
   `<script>` tag during page load. It carries the `registry_hash` HMAC and, for
   internal users, the company hierarchy. Note `browser_cache_secret` is **not**
   part of `session_info()`: it is injected separately into the page context by
   `home.py` (`home.py:113-121`, whose comment notes it is added "here and not in
   session_info()"). The JS reads `odoo.__session_info__` into a local snapshot
   but **does not delete it** from the global — the test harness re-reads the same
   global (`session.js:10-20`). Never add sensitive data (passwords, API keys) to
   `session_info()` — it's visible in page source.

9. **`urgentSave` optimistic-locking parity** — Both the normal save path
   (`model/relational_model/record_save.js:150`) and the urgent (sendBeacon)
   path (`record_save.js:89`) send `kwargs.last_write_date = wd.toISO()` when
   `record._values.write_date` is present, so the server can reject concurrent
   edits in either flow. The urgent path's ~30-byte ISO-string overhead is well
   within the typical 64 KB `sendBeacon` budget.

10. **`archiveEnabled` derivations differ between form and multi-record by
    design** — `form_controller.js:591-600` checks `"active" in
    activeFields` AND `!props.fields.active.readonly`, with a fallback to
    `"x_active"` for custom no-active-field models. `multi_record_controller.js:61`
    calls `computeArchiveEnabled(this.props.fields)` which only checks
    `"active" in fields` AND `!fields.active.readonly` (no `activeFields`
    gate, no `x_active` fallback).

    **Why the form needs the stricter `activeFields` gate**: the form
    conditions archive vs unarchive on `model.root.isActive`
    (`form_controller.js:547,556`). If `active` is not in `activeFields`,
    the view never loads it, so `record.data.active` is `undefined` and
    `record.isActive` is falsy. Without the gate, `archiveEnabled` would still
    be true and the form would show "Unarchive" on a record whose active state
    it cannot read.

    **Why multi-record can skip the gate**: list/kanban shows both archive
    AND unarchive simultaneously (multiple selected records, mixed states).
    It does not condition on any single record's state, so the weaker check
    is sufficient.

    Shared known limitation: neither controller checks view-level readonly attrs
    (`<field readonly="..."/>`); both rely on model-level `props.fields[*].readonly`.

11. **Registry schema validation runs in production with a soft warning** —
    `core/registry.js:validateSchema` runs the OWL `validate()` call in every
    environment. In debug mode it throws (fail fast for developers); in production
    it emits a `console.warn` prefixed `[registry]` so a single malformed
    registration cannot crash the page while still surfacing schema mismatches.
    Schema coverage is **32 of 32 web-module categories**. The `debug` registry IS
    schemable despite being "parent-only": its entries are sub-Registry instances
    created by `category()`, so `entry instanceof Registry` catches accidental
    direct `.add()` calls. Pattern to follow when adding a new registry or
    schema-ing an existing one:

    - Co-locate the `addValidation` call with the **canonical consumer**
      of the registry, not in a central bootstrap file (`env.js` for services,
      `fields/field.js` for fields, `webclient/navbar/navbar.js` for systray) —
      the schema is discoverable when someone changes that consumer.
    - Two schema forms are accepted by `core/registry.js:validateSchema`:
      object form (passed to OWL's `validate()`) for entries shaped like
      `{ key: spec }`, and predicate form (`(entry) => boolean`) for
      entries that are bare callables/classes.
    - When entries forward extra fields to downstream addons, include
      `"*": true` in object schemas so private fields don't trip the
      validator. The contract is "here's what *we* read"; the rest is forwarded.
    - Translated strings (`_t(...)`) return `LazyTranslatedString`
      objects, not plain strings. Any schema field that may hold a
      `_t()` value must accept `[String, Object]`, not `String` alone.
      Affected: `command_categories.name`,
      `command_setup.{emptyMessage,name,placeholder}`,
      `error_notifications.{title,message}`,
      `group_config_items.label`, `color_picker_tabs.name`.
    - When validating "must be a Component class", check
      `entry?.prototype instanceof Component` if `Component` is already
      imported; otherwise fall back to `typeof entry === "function"`
      (class definitions are functions) to avoid a new import.
    - When the canonical consumer carries a typed shape in
      `@types/registries/*.d.ts`, **the runtime schema must match the
      declared shape**.

12. **`FormSaveCoordinator` owns the form save lifecycle** —
    `views/form/form_save_coordinator.js`. Every save / discard / urgent-save entry
    point in `form_controller.js` (lines 477, 500, 510, 522, 605, 655, 672,
    698, 721) calls `this.saveCoordinator.requestSave({...})` /
    `requestUrgentSave()` / `requestDiscard()` with named options.

    The hook signature is `onSaveError(error, callbacks: { discard, retry })`;
    the coordinator dispatches between *render error dialog*, *rethrow*, and
    *swallow* via the named option `errorMode: "dialog" | "rethrow" | "silent"`
    (not a positional boolean). It also exposes `status: "clean" | "dirty" |
    "saving" | "error"` and `isSaving` as a single observable surface so external
    readers (form status indicator, route guards) don't reverse-engineer state
    from `record.dirty` plus scattered `isSaving` flags.

13. **`patch()` targets prototypes and plain objects, never namespace
    imports** — `core/utils/patch.js:79`. Native ES module namespaces
    (`import * as X from "..."`) are **frozen by the ECMAScript spec**:
    properties are non-configurable, so `Object.defineProperty()` (which
    `patch()` uses internally at line 119) throws `TypeError`. Use one of:

    - **Class methods / instance behavior** → `patch(MyClass.prototype, {...})`
    - **Static methods** → `patch(MyClass, {...})` (the constructor object
      is configurable; only its `prototype` property is read-only)
    - **Services, env, plain config objects** → `patch(env, {...})`,
      `patch(services, {...})` — the object is mutable so this works directly

    What does NOT work and will throw at module load:

    ```js
    // ❌ WRONG — namespace is frozen
    import * as urlUtils from "@html_editor/utils/url";
    patch(urlUtils, { isAbsoluteURLInCurrentDomain(url) { ... } });
    ```
