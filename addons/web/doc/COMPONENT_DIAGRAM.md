# Web Module — Component Diagram

> **Purpose**: Map every major subsystem so correctness audits can target
> specific areas without losing context on the full module.
>
> Each section below corresponds to an **audit area** — a cohesive group of
> files that can be reviewed together in one session.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BROWSER                                        │
│                                                                             │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────────────────────┐   │
│  │   BOOT      │  │   WEBCLIENT      │  │   MAIN COMPONENTS             │   │
│  │   SEQUENCE  │──▶   SHELL          │──▶   CONTAINER                   │   │
│  │             │  │                  │  │  (Dialog, Notification, ...)  │   │
│  └─────────────┘  └──────┬───────────┘  └───────────────────────────────┘   │
│                          │                                                  │
│           ┌──────────────┼───────────────────────┐                          │
│           ▼              ▼                       ▼                          │
│  ┌──────────────┐ ┌─────────────┐  ┌─────────────────────┐                  │
│  │   NAVBAR     │ │   ACTION    │  │   SEARCH SYSTEM     │                  │
│  │   + MENUS    │ │   SERVICE   │  │   (SearchModel,     │                  │
│  │   + SYSTRAY  │ │   + STACK   │  │    ControlPanel,    │                  │
│  └──────────────┘ └──────┬──────┘  │    SearchPanel)     │                  │
│                          │         └──────────┬──────────┘                  │
│                          ▼                    │                             │
│              ┌───────────────────────┐        │                             │
│              │   VIEW LAYER          │◀───────┘                             │
│              │  ┌──────┬──────┐      │                                      │
│              │  │ Form │ List │ ...  │                                      │
│              │  └──┬───┴──┬───┘      │                                      │
│              └─────┼──────┼──────────┘                                      │
│                    │      │                                                 │
│           ┌────────┘      └────────┐                                        │
│           ▼                        ▼                                        │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────────────┐  │
│  │   FIELD WIDGETS  │  │   DATA MODEL      │  │   UI SYSTEM              │  │
│  │  (67 types)      │  │  (RelationalModel │  │  (Dialog, Notification,  │  │
│  │                  │  │   Record, Lists)  │  │   Popover, Tooltip,      │  │
│  └──────────────────┘  └────────┬──────────┘  │   Overlay, Effects)      │  │
│                                 │             └──────────────────────────┘  │
│                                 ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │   CORE SERVICES                                                      │   │
│  │  ┌─────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌──────┐ ┌────────────────┐    │   │
│  │  │ ORM │ │ HTTP │ │ User │ │ Hotkey │ │ Menu │ │ Localization   │    │   │
│  │  └──┬──┘ └──┬───┘ └──────┘ └────────┘ └──────┘ └────────────────┘    │   │
│  └─────┼───────┼────────────────────────────────────────────────────────┘   │
│        │       │                                                            │
│  ┌─────┴───────┴────────────────────────────────────────────────────────┐   │
│  │   CORE INFRASTRUCTURE                                                │   │
│  │  ┌──────────┐ ┌────────┐ ┌───────┐ ┌────────┐ ┌──────────────────┐   │   │
│  │  │ Registry │ │ Router │ │ RPC   │ │ py_js  │ │ Utils            │   │   │
│  │  │          │ │        │ │ Cache │ │ (Eval) │ │ (hooks, timing)  │   │   │
│  │  └──────────┘ └────────┘ └───┬───┘ └────────┘ └──────────────────┘   │   │
│  └──────────────────────────────┼───────────────────────────────────────┘   │
│                                 │                                           │
└─────────────────────────────────┼───────────────────────────────────────────┘
                                  │ JSON-RPC 2.0
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SERVER (Python)                                │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │   CONTROLLERS (HTTP Routing)                                         │   │
│  │  ┌──────────┐ ┌─────────┐ ┌────────┐ ┌────────┐ ┌───────────────┐    │   │
│  │  │ dataset  │ │ session │ │ home   │ │ binary │ │ webclient     │    │   │
│  │  │ (RPC GW) │ │ (Auth)  │ │ (Boot) │ │ (Files)│ │ (Assets/i18n) │    │   │
│  │  └────┬─────┘ └────┬────┘ └────┬───┘ └────┬───┘ └───────────────┘    │   │
│  │       │            │           │          │                          │   │
│  │  ┌────┴─────┐ ┌────┴────┐ ┌────┴───┐ ┌────┴───┐ ┌───────────────┐    │   │
│  │  │ action   │ │ export  │ │ report │ │ domain │ │ json (API)    │    │   │
│  │  │ (Load)   │ │ (CSV/XL)│ │ (PDF)  │ │ (Valid)│ │ (Bearer)      │    │   │
│  │  └──────────┘ └─────────┘ └────────┘ └────────┘ └───────────────┘    │   │
│  │  ┌──────────┐ ┌─────────┐ ┌────────┐ ┌─────────────────────────┐     │   │
│  │  │ database │ │ pivot   │ │ vcard  │ │ profiling, webmanifest  │     │   │
│  │  │ (DB Mgmt)│ │ (XLSX)  │ │        │ │ settings, model, view   │     │   │
│  │  └──────────┘ └─────────┘ └────────┘ └─────────────────────────┘     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                 │                                           │
│  ┌──────────────────────────────┼───────────────────────────────────────┐   │
│  │   MODELS (ORM Extensions)    │                                       │   │
│  │                              ▼                                       │   │
│  │  ┌──────────────────────────────────────────────┐                    │   │
│  │  │  WEB DATA ACCESS (extends 'base')            │                    │   │
│  │  │  ┌──────────┐ ┌──────────────┐ ┌───────────┐ │                    │   │
│  │  │  │ web_read │ │web_read_group│ │web_onchange│ │                   │   │
│  │  │  │ web_save │ │read_progress │ │  snapshot  │ │                   │   │
│  │  │  │ web_sread│ │  _bar        │ │            │ │                   │   │
│  │  │  └──────────┘ └──────────────┘ └───────────┘ │                    │   │
│  │  │  ┌───────────────┐ ┌──────────────────────┐  │                    │   │
│  │  │  │web_search_panel│ │ record_snapshot      │  │                   │   │
│  │  │  └───────────────┘ └──────────────────────┘  │                    │   │
│  │  └──────────────────────────────────────────────┘                    │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────┐                    │   │
│  │  │  FRAMEWORK EXTENSIONS                        │                    │   │
│  │  │  ┌────────┐ ┌──────────┐ ┌────────────────┐  │                    │   │
│  │  │  │ ir_http│ │ir_ui_menu│ │ ir_ui_view     │  │                    │   │
│  │  │  │(session│ │(load_web │ │ (get_view_info)│  │                    │   │
│  │  │  │ _info) │ │ _menus)  │ │                │  │                    │   │
│  │  │  └────────┘ └──────────┘ └────────────────┘  │                    │   │
│  │  │  ┌──────────┐ ┌───────────────────────────┐  │                    │   │
│  │  │  │ ir_model │ │ ir_qweb_fields            │  │                    │   │
│  │  │  │(_get_def)│ │ (image rendering)         │  │                    │   │
│  │  │  └──────────┘ └───────────────────────────┘  │                    │   │
│  │  └──────────────────────────────────────────────┘                    │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────┐                    │   │
│  │  │  BUSINESS MODELS                             │                    │   │
│  │  │  ┌───────────┐ ┌─────────────────┐           │                    │   │
│  │  │  │ res_users  │ │res_users_settings│         │                    │   │
│  │  │  │ (captcha,  │ │(density, embedded│         │                    │   │
│  │  │  │  bootstrap)│ │ actions)         │         │                    │   │
│  │  │  └───────────┘ └─────────────────┘           │                    │   │
│  │  │  ┌──────────────┐ ┌────────────────────────┐ │                    │   │
│  │  │  │ res_company  │ │ base_document_layout   │ │                    │   │
│  │  │  │ res_partner  │ │ res_config_settings    │ │                    │   │
│  │  │  │ properties   │ │                        │ │                    │   │
│  │  │  └──────────────┘ └────────────────────────┘ │                    │   │
│  │  └──────────────────────────────────────────────┘                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                 │                                           │
│                                 ▼                                           │
│                         ┌──────────────┐                                    │
│                         │  PostgreSQL  │                                    │
│                         │  (+ PostGIS) │                                    │
│                         └──────────────┘                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Audit Areas — Detailed Breakdown

Each area below is self-contained enough for a focused correctness audit.
Files are listed with approximate line counts.

---

### AREA 1: Boot Sequence & Environment Setup

**Risk**: Incorrect initialization order, race conditions, missing services.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| JS | `static/src/boot/main.js` | ~10 | Entry point — imports WebClient, calls start |
| JS | `static/src/boot/start.js` | ~60 | `startWebClient()` — RPC cache, mount, SW |
| JS | `static/src/env.js` | ~280 | `makeEnv()`, `startServices()`, `mountComponent()`, `customDirectives`, `globalValues` |
| JS | `static/src/session.js` | ~2 | Capture and delete `__session_info__` from HTML at module load |
| JS | `static/src/module_loader.js` | ~200 | ES module loader / dynamic imports |
| PY | `controllers/home.py` | ~295 | `/`, `/web`, `/odoo`, `/web/webclient/load_menus`, `/web/login`, `/web/login_successful`, `/web/become`, `/web/health`, `/robots.txt` |
| PY | `models/ir_http.py` | ~280 | `session_info()`, `webclient_rendering_context()` |
| XML | `views/webclient_templates.xml` | ~300 | HTML shell, `t-call-assets`, inline session JSON |

**Key invariants to check**:
- Service dependency order is acyclic
- `session_info()` never leaks sensitive data to public users
- `ensure_db()` correctly redirects when no DB selected
- RPC cache secret tied to correct session

---

### AREA 2: Authentication & Session Management

**Risk**: Session fixation, auth bypass, cookie handling bugs.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/session.py` | ~110 | `get_session_info`, `authenticate`, `get_lang_list`, `modules`, `check`, `account`, `destroy`, `logout` |
| PY | `controllers/home.py:web_login` | ~60 | Login form + CAPTCHA |
| PY | `models/res_users.py` | ~140 | `_should_captcha_login()`, `_on_webclient_bootstrap()` |
| PY | `models/ir_http.py` | ~280 | `_handle_debug()`, `_sanitize_cookies()`, `session_info()` |
| JS | `static/src/webclient/session_service.js` | ~50 | Client-side session |
| JS | `static/src/public/login.js` | ~40 | Login form component |

**Key invariants to check**:
- `authenticate()` never returns session_info for invalid credentials
- Session cookies have correct flags (HttpOnly, Secure, SameSite)
- `_sanitize_cookies()` removes stale company IDs correctly
- CAPTCHA check cannot be bypassed by omitting parameter
- Debug mode restricted to internal users

---

### AREA 3: RPC Gateway (dataset.py + call_kw)

**Risk**: Method access bypass, readonly mismatch, injection via model/method names.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/dataset.py` | ~55 | `call_kw()`, `call_button()`, readonly detection |
| PY | `controllers/utils.py` | ~285 | `clean_action()`, `ensure_db()`, `generate_views()`, `get_action()`, `get_action_triples()`, `_get_login_redirect_url()`, `is_user_internal()`, `_local_web_translations()` |
| JS | `static/src/services/orm_service.js` | ~395 | `ORM.call()`, `read()`, `write()`, etc. |
| JS | `static/src/core/network/rpc.js` | ~180 | JSON-RPC envelope, error handling |
| JS | `static/src/core/network/rpc_cache.js` | ~310 | Dual-layer (RAM + IndexedDB) RPC cache with AES-GCM encryption and pending-request deduplication |

**Key invariants to check**:
- `_call_kw_readonly()` correctly inspects `_readonly` attribute
- `call_button()` always passes result through `clean_action()`
- Model/method names validated before dispatch
- RPC cache invalidation triggered on write/unlink/create
- JSON-RPC error envelope never exposes stack traces in production

---

### AREA 4: Web Data Access (web_read / web_save / web_search_read)

**Risk**: N+1 queries, specification traversal bugs, ACL bypass in nested reads.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `models/web_read.py` | ~525 | `web_read()`, `web_save()`, `web_search_read()`, `web_name_search()`, `web_resequence()` |
| PY | `models/web_read_group.py` | ~775 | `web_read_group()`, `formatted_read_group()`, `formatted_read_grouping_sets()`, `read_progress_bar()` |
| PY | `models/web_read_group_helpers.py` | ~555 | Temporal fill, formatters |
| PY | `models/web_search_panel.py` | ~430 | `search_panel_select_range/multi_range` |
| PY | `models/web_search_panel_helpers.py` | ~280 | Panel filter formatters |

**Key invariants to check**:
- `web_read()` respects ACLs on nested relational traversals
- Specification `limit` on x2many is enforced
- `web_search_read()` count_limit prevents full table scans
- `web_read_group()` temporal fill doesn't create phantom groups
- `read_progress_bar()` domain composition is correct

---

### AREA 5: Form Onchange & Record Snapshot

**Risk**: State diff errors, x2many command generation bugs, side effects in simulation.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `models/web_onchange.py` | ~280 | `onchange()`, `web_override_translations()` |
| PY | `models/record_snapshot.py` | ~100 | `RecordSnapshot` — before/after diff |

**Key invariants to check**:
- `onchange()` never persists data (pure simulation)
- Snapshot diff correctly handles x2many CREATE/UPDATE/DELETE commands
- NewId records handled correctly in onchange context
- `web_override_translations()` validates field is translatable

---

### AREA 6: Action Service & Navigation

**Risk**: Action injection, breadcrumb corruption, controller stack leaks.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/action.py` | ~165 | `/web/action/load`, `/run`, `/load_breadcrumbs` |
| JS | `static/src/webclient/actions/action_service.js` | ~1250 | `doAction()`, controller stack |
| JS | `static/src/webclient/actions/action_container.js` | ~45 | Render current action |
| JS | `static/src/webclient/actions/action_dialog.js` | ~40 | Action in modal |
| JS | `static/src/webclient/actions/action_state.js` | ~190 | Serialize/deserialize URL state |
| JS | `static/src/webclient/actions/action_info_builders.js` | ~235 | Build view props from action |
| JS | `static/src/webclient/actions/action_button_executor.js` | ~205 | Button action dispatch |
| JS | `static/src/webclient/actions/breadcrumb_manager.js` | ~210 | Breadcrumb trail logic |

**Key invariants to check**:
- `load()` validates action type before returning
- Server actions (`/run`) check execution permissions
- Breadcrumb restore doesn't replay stale actions
- Controller stack properly cleaned on navigation
- `clean_action()` strips all internal fields

---

### AREA 7: View System (Form, List, Kanban, Calendar)

**Risk**: Arch compilation bugs, field binding errors, event handler misrouting.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| JS | `static/src/views/view.js` | ~525 | Base View component + arch loading |
| JS | `static/src/views/view_compiler.js` | ~480 | XML arch → OWL template |
| JS | `static/src/views/form/` | ~15 files | Form controller, renderer, compiler |
| JS | `static/src/views/list/` | ~15 files | List controller, renderer, group |
| JS | `static/src/views/kanban/` | ~12 files | Kanban controller, renderer, column |
| JS | `static/src/views/calendar/` | ~10 files | Calendar view (FullCalendar) |
| JS | `static/src/views/graph/` | ~8 files | Graph/chart view (lazy-loaded) |
| JS | `static/src/views/pivot/` | ~8 files | Pivot table view (lazy-loaded) |

**Key invariants to check**:
- Arch compiler handles all XML node types (field, button, group, notebook, page)
- `attrs` evaluation correctly resolves modifiers (invisible, readonly, required)
- List view selection state consistent across page navigation
- Kanban drag-drop correctly generates resequence commands
- Calendar event creation maps dates correctly to record fields

---

### AREA 8: Field Widgets (67 types)

**Risk**: Parser/formatter mismatches, type coercion bugs, relational field binding.

| Layer | Directory | Files | Types |
|-------|-----------|-------|-------|
| JS | `static/src/fields/basic/` | 21 | boolean, char, float, html, integer, text, url, ... |
| JS | `static/src/fields/display/` | 8 | badge, gauge, handle, progress_bar, statusbar |
| JS | `static/src/fields/media/` | 7 | binary, image, pdf_viewer, signature |
| JS | `static/src/fields/relational/` | 11 | many2one, many2many_tags, x2many, reference |
| JS | `static/src/fields/selection/` | 7 | selection, radio, priority, state_selection |
| JS | `static/src/fields/specialized/` | 10 | domain, properties, ace, color_picker |
| JS | `static/src/fields/temporal/` | 3 | datetime, remaining_days, timezone_mismatch |
| JS | `static/src/fields/formatters.js` | ~300 | All value → display formatters |
| JS | `static/src/fields/parsers.js` | ~200 | All input → value parsers |

**Key invariants to check**:
- `formatters.js` ↔ `parsers.js` are true inverses (round-trip correctness)
- Monetary fields respect currency decimal places
- Many2one correctly handles NewId references
- x2many generates correct ORM commands for all operations
- HTML field sanitizes content (XSS prevention)

---

### AREA 9: Search System

**Risk**: Domain composition errors, facet state inconsistency, saved filter corruption.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| JS | `static/src/search/search_model.js` | ~1050 | Core search state machine |
| JS | `static/src/search/search_arch_parser.js` | ~200 | Parse search view XML |
| JS | `static/src/search/search_domain.js` | ~100 | Domain from facets |
| JS | `static/src/search/search_group_by.js` | ~80 | GroupBy from selections |
| JS | `static/src/search/search_context.js` | ~60 | Context dict builder |
| JS | `static/src/search/search_favorites.js` | ~150 | Save/load filters |
| JS | `static/src/search/control_panel/` | ~5 files | ControlPanel component |
| JS | `static/src/search/search_bar/` | ~3 files | Search input + suggestions |
| JS | `static/src/search/search_panel/` | ~3 files | Sidebar filter panel |

**Key invariants to check**:
- Domain ANDs/ORs nest correctly with multiple active facets
- GroupBy + comparison mode composes correctly
- Saved favorites restore full state (domain + groupby + context)
- Date range facets respect user timezone
- Search panel category filters produce valid domains

---

### AREA 10: Data Model Layer (Client-side)

**Risk**: Cache stale reads, relational traversal errors, record lifecycle bugs.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| JS | `static/src/model/model.js` | ~290 | Base Model class |
| JS | `static/src/model/relational_model/relational_model.js` | ~935 | Core data model — coordinates all sub-components |
| JS | `static/src/model/relational_model/record.js` | ~1045 | Single record lifecycle, dirty tracking, save |
| JS | `static/src/model/relational_model/dynamic_list.js` | ~585 | Paginated, sortable record list |
| JS | `static/src/model/relational_model/dynamic_group_list.js` | ~430 | Grouped record list (kanban/list group-by) |
| JS | `static/src/model/relational_model/dynamic_record_list.js` | ~200 | Flat filtered record list |
| JS | `static/src/model/relational_model/static_list.js` | ~870 | Immutable x2many snapshot |
| JS | `static/src/model/relational_model/static_list_command_engine.js` | ~275 | ORM command generation for x2many edits |
| JS | `static/src/model/relational_model/static_list_sort.js` | ~135 | Client-side sort for static lists |
| JS | `static/src/model/relational_model/static_list_utils.js` | ~150 | Shared static list helpers |
| JS | `static/src/model/relational_model/group.js` | ~150 | Single group wrapper |
| JS | `static/src/model/relational_model/datapoint.js` | ~65 | Base class for record/group/list |
| JS | `static/src/model/relational_model/field_metadata.js` | ~320 | Field descriptor resolution |
| JS | `static/src/model/relational_model/field_values.js` | ~325 | Typed field value containers |
| JS | `static/src/model/relational_model/field_spec.js` | ~120 | Specification tree builder |
| JS | `static/src/model/relational_model/field_context.js` | ~90 | Per-field context computation |
| JS | `static/src/model/relational_model/record_save.js` | ~195 | Save orchestration (new/edit/delete) |
| JS | `static/src/model/relational_model/record_preprocessors.js` | ~230 | Incoming data normalisation |
| JS | `static/src/model/relational_model/record_value_transforms.js` | ~180 | Field value coercion before save |
| JS | `static/src/model/relational_model/record_validator.js` | ~100 | Required/constraint validation |
| JS | `static/src/model/relational_model/record_utils.js` | ~150 | Shared record helpers |
| JS | `static/src/model/relational_model/record_hooks.js` | ~10 | OWL hooks for record reactivity |
| JS | `static/src/model/relational_model/command_builder.js` | ~170 | Write command construction |
| JS | `static/src/model/relational_model/commands.js` | ~55 | ORM command constants |
| JS | `static/src/model/relational_model/operation.js` | ~35 | Pending-operation queue |
| JS | `static/src/model/relational_model/onchange_coalescer.js` | ~105 | Debounce/merge onchange calls |
| JS | `static/src/model/relational_model/resequence.js` | ~105 | Handle field resequencing |
| JS | `static/src/model/relational_model/errors.js` | ~40 | Model-specific error classes |
| JS | `static/src/model/relational_model/utils.js` | ~35 | Internal utility functions |
| JS | `static/src/model/sample_server.js` | ~755 | Mock ORM for demos |

**Key invariants to check**:
- Record dirty state tracked correctly across relational edits
- x2many record ordering preserved across save/reload
- `rpcBus.trigger("CLEAR-CACHES")` truly clears all stale data in `rpc_cache.js`
- `onchange_coalescer` debounce does not swallow concurrent field changes
- `static_list_command_engine` generates minimal correct ORM commands (no spurious UPDATE)
- Sample server mock responses match real ORM structure

---

### AREA 11: Binary & Asset Serving

**Risk**: Path traversal, access token bypass, cache poisoning, image resize DoS.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/binary.py` | ~455 | `/web/image`, `/web/content`, `/web/assets`, upload |
| PY | `controllers/report.py` | ~200 | `/report/<format>/<name>`, barcode generation |
| PY | `controllers/pivot.py` | ~100 | `/web/pivot/export_xlsx` |

**Key invariants to check**:
- `/web/image` validates model/field before serving (no arbitrary field reads)
- Access tokens validated before serving private attachments
- Image resize dimensions bounded (no 99999x99999 requests)
- `/web/filestore` always returns 404 (nginx handles it)
- Asset unique hash prevents cache serving stale bundles
- Report converter validated (only html/pdf/text)

---

### AREA 12: Export System

**Risk**: Memory exhaustion on large exports, formula injection in CSV/XLSX.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/export.py` | ~540 | CSV/XLSX export, field enumeration |
| PY | `controllers/export_writers.py` | ~400 | XLSX formatting, grouped export |

**Key invariants to check**:
- Export respects `ir.rule` security domains
- CSV values escaped to prevent formula injection (`=`, `+`, `-`, `@`)
- Field nesting depth bounded (prevent infinite recursion on circular relations)
- XLSX writer handles special characters in sheet/cell names
- Grouped export tree structure terminates correctly

---

### AREA 13: Database Management

**Risk**: Privilege escalation, backup disclosure, master password bypass.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/database.py` | ~290 | Create, drop, backup, restore, change_password |

**Key invariants to check**:
- Master password validated on every destructive operation
- `list_db` config respected (no listing when disabled)
- Backup format validated before restore
- CSRF protection (currently disabled with `csrf=false` — intentional?)
- Database names sanitized (no SQL injection in createdb)

---

### AREA 14: JSON API (Bearer Token)

**Risk**: Auth bypass, over-permissive data exposure, action eval injection.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/json.py` | ~275 | `/json/1/<subpath>` REST-like API |
| PY | `controllers/json_helpers.py` | ~200 | View/domain resolution helpers |

**Key invariants to check**:
- Bearer token auth correctly validates API keys
- Route only active in demo mode or with config param
- Action evaluation context doesn't allow arbitrary code execution
- Domain filtering cannot be bypassed via URL manipulation
- Response doesn't leak fields user has no access to

---

### AREA 15: UI System (Overlays)

**Risk**: Z-index stacking bugs, scroll lock leaks, XSS in notifications.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| JS | `static/src/ui/dialog/` | ~5 files | Modal dialog service |
| JS | `static/src/ui/notification/` | ~3 files | Toast notification service |
| JS | `static/src/ui/overlay/` | ~3 files | Overlay layer manager |
| JS | `static/src/ui/popover/` | ~3 files | Positioned popover |
| JS | `static/src/ui/tooltip/` | ~3 files | Data-attribute tooltip |
| JS | `static/src/ui/block/` | ~2 files | Block UI overlay |
| JS | `static/src/ui/effects/` | ~2 files | Visual effects |
| JS | `static/src/ui/bottom_sheet/` | ~2 files | Mobile bottom sheet |

**Key invariants to check**:
- Dialog close always unblocks UI (no phantom overlays)
- Notification content sanitized (no HTML injection)
- Popover positioning accounts for viewport boundaries
- Scroll lock released on all dialog close paths (including errors)

---

### AREA 16: Core Infrastructure (Registry, Router, py_js)

**Risk**: Registry pollution, route hijacking, Python eval injection in domains.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| JS | `static/src/core/registry.js` | ~290 | Central plugin registry |
| JS | `static/src/core/browser/router.js` | ~435 | URL ↔ state management |
| JS | `static/src/core/py_js/` | ~8 files | Python expression evaluator |
| JS | `static/src/core/utils/` | ~15 files | Hooks, timing, DOM, collections |
| JS | `static/src/core/l10n/` | ~5 files | Localization, date/number formats |

**Key invariants to check**:
- `py_js` evaluator sandboxed (no access to `window`, `document`, `fetch`)
- Registry `add()` with `force: true` required to overwrite existing entries
- Router state serialization doesn't allow prototype pollution
- `useService()` returns same instance across component lifecycle

---

### AREA 17: PWA & Service Worker

**Risk**: Cache serving stale content, offline mode data leaks.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/webmanifest.py` | ~250 | Manifest, service worker, offline page |
| JS | `static/src/service_worker.js` | ~215 | SW caching strategy |
| JS | `static/src/services/pwa/` | ~3 files | PWA install prompt |

**Key invariants to check**:
- Service worker doesn't cache authenticated responses
- Manifest `start_url` validated against allowed origins
- Scoped app icon generation doesn't allow arbitrary image processing
- Offline page doesn't expose session data

---

### AREA 18: Profiling & Debug

**Risk**: Information disclosure, debug mode persistence.

| Layer | File | Lines | Role |
|-------|------|-------|------|
| PY | `controllers/profiling.py` | ~150 | Enable/disable profiling, speedscope |
| JS | `static/src/webclient/debug/` | ~5 files | Debug menu, providers |

**Key invariants to check**:
- Profiling restricted to users with `base.group_system`
- Speedscope profiles don't contain credentials or session tokens
- Debug mode cannot be enabled by non-internal users

---

## Cross-Cutting Concerns (Check Across All Areas)

| Concern | What to Look For |
|---------|-----------------|
| **ACL enforcement** | Every data access path goes through `check_access_rights` |
| **SQL injection** | All `cr.execute()` use `%s` parameterization |
| **XSS** | All user content rendered through OWL (auto-escaped) or sanitized |
| **CSRF** | All state-changing routes use `type='jsonrpc'` (implicit CSRF) |
| **Cache coherence** | Write operations trigger `CLEAR-CACHES` appropriately |
| **Error handling** | Errors don't leak stack traces in production |
| **Readonly routing** | `readonly=True` matches actual read-only behavior |
| **Timezone handling** | Dates converted consistently between UTC and user TZ |
| **Concurrency** | `write()` checks `write_date` for optimistic locking |
