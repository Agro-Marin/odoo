# State Management Patterns

> Decision tree and reference for choosing the right state pattern in `web/static/src/`.

## Canonical primitives

Translation between industry vocabulary and the OWL primitives in this codebase:

| Concept | OWL-native spelling | Industry analog |
|---------|---------------------|-----------------|
| Component-local signal | `useState({ ... })` | React `useState` / Vue `ref` / Solid `createSignal` (component-scoped) |
| Shared signal | `reactive({ ... })` returned from a service's `start()` | Vue 3 `reactive` / Solid store / Svelte 5 `$state` in module scope |
| Shared signal class | `class extends SignalStore` | Mobx observable class / Vue `reactive` on `this` / Pinia store class |
| Component-scoped effect | `useEffect` (from `@odoo/owl`) — fires only while owning component is mounted | React `useEffect` / Solid `createEffect` inside a component |
| Process-scoped effect | `effect(cb, deps)` (from `@web/core/utils/reactive`) — fires until garbage-collected; used by services and record observers | Solid `createEffect` at module scope / Vue 3 `watchEffect` / Svelte 5 `$effect` |
| Computed / derived value (on a class) | Plain JS getter reading signals (OWL is Proxy-based — getters track automatically) | Solid `createMemo` accessed via class field / Vue `computed` ref on `this` |
| Computed / derived value (free-standing) | `derived(() => …)` (from `@web/core/utils/reactive`) — read via `.value` | Solid `createMemo` / Vue `computed` / Svelte 5 `$derived` |

The two effect rows reflect a real distinction: a component using
`useEffect` cleans up automatically on unmount, while a service-level
`effect(cb, deps)` survives as long as the captured `deps` proxy
survives. Don't substitute one for the other.

The two derived rows reflect the API shape choice: a class getter is
ergonomic when the derived value naturally belongs to an instance
(``record.dirty``, ``coordinator.isSaving``); `derived(fn)` is the
right tool when the computation spans multiple sources or wants to be
passed around as a value object — same shape as Vue's `ref` (`.value`
read) but for read-only derivations. Neither is memoized; OWL's
scheduler batches renders within a tick.

**SignalStore.**  ``SignalStore`` is the canonical class name.  Only
`SignalStore` is exported; the `Reactive` alias was removed.  Attempting
`import { Reactive } from "@web/core/utils/reactive"` fails at module-load
with a native "no such export" error.  All 26 production sites use
``extends SignalStore``.

## Decision Tree

```
Where does this state live?
│
├─ Single component only?
│  └─ useState({ ... })
│     Examples: pager_indicator.js, signature_dialog.js, file_input.js
│
├─ Shared across features (via service)?
│  └─ reactive({}) in service start()
│     Examples: notification_service.js, file_upload_service.js,
│               frequent_emoji_service.js
│
├─ ORM entity (record, list, group)?
│  └─ class extends SignalStore
│     Examples: datapoint.js, record.js, static_list.js, group.js
│
├─ Stateful UI behavior with computed logic?
│  ├─ Derivation naturally belongs to an instance?
│  │  └─ Express it as a getter on a SignalStore / shared reactive({})
│  │     — the Proxy tracks dependencies automatically, no explicit
│  │     computed primitive needed.
│  │     Avoid ``reactive({ get x(){}, set x(v){…mutate other state…} })``
│  │     with side-effecting setters — that's an effect masquerading
│  │     as state.  Use useEffect / effect instead.
│  └─ Derivation spans multiple sources or wants to be passed around?
│     └─ derived(() => …) from @web/core/utils/reactive — read via
│        ``.value``. Aligned with Vue 3 ``computed`` / Svelte 5
│        ``$derived``. Lazy, not memoized.
│
└─ >3 named states with guards?
   └─ State machine (document first, implement only if bug motivates it)
      See: Form Save State Diagram below
```

## Pattern 1: `useState()` — Component-Local State

Wraps a plain object in OWL reactivity. Mutations trigger re-renders of the
owning component only. This is the default choice.

```javascript
setup() {
    this.state = useState({ count: 0, loading: false });
}
// Mutate directly:
this.state.count++;
this.state.loading = true;
```

**When to use**: State that belongs to one component and doesn't need to be
shared. Form field values, toggle flags, pagination state, loading indicators.

**Files**: ~74 occurrences across components/, views/, webclient/.

## Pattern 2: `reactive()` — Service-Level Shared State

Creates a reactive object in a service's `start()` method. Returned as part of
the service API so any component can `useService()` and read/write it.

```javascript
// In service:
const uploads = reactive({});
return { uploads, add(file) { uploads[id] = file; } };

// In component:
const fileUpload = useService("file_upload");
// fileUpload.uploads is reactive — reads trigger subscriptions
```

**When to use**: State shared across multiple unrelated components. Notifications,
file uploads, emoji frequency, currency rates, user preferences.

**Key files**:
- `services/file_upload_service.js` — reactive upload tracking with progress
- `ui/notification/notification_service.js` — reactive notification dict
- `services/frequent_emoji_service.js` — reactive usage counters with localStorage sync

## Pattern 3: `SignalStore` Base Class — Model Entities

Classes extending `SignalStore` (`core/utils/reactive.js`) auto-wrap
`this` in `reactive()` during construction.  Used for ORM data
structures where any property mutation must propagate to the UI.

```javascript
class DataPoint extends SignalStore {
    constructor(model, config, data) {
        super();           // returns reactive(this)
        markRaw(config);   // exclude heavy config from reactivity
        this.setup(config, data);
    }
}
```

Only `SignalStore` is exported; the `Reactive` alias was removed.

**Inheritance chain** (actual class names in code):

```
SignalStore
    └── DataPoint
          ├── RelationalRecord        (record.js — exported as `RelationalRecord`, not `Record`)
          ├── StaticList
          ├── Group
          └── DynamicList
                ├── DynamicRecordList
                └── DynamicGroupList
```

`DataPoint` `extends SignalStore` directly.

**Critical detail**: Use `markRaw()` on large objects that don't need reactivity
(field definitions, active fields, configs). Without it, OWL deep-wraps every
nested property, causing massive overhead.

**Key files**:
- `core/utils/reactive.js` — `SignalStore` base class (3 lines of behavior)
- `model/relational_model/datapoint.js` — `DataPoint extends SignalStore`
- `model/relational_model/record.js` — `RelationalRecord extends DataPoint` (exported as `RelationalRecord`, NOT `Record`)
- `components/dropdown/dropdown_hooks.js` — `DropdownState extends SignalStore`

## Pattern 4 (discouraged): `reactive()` with side-effecting setters

The codebase historically uses `reactive({})` with JS getters/setters
where the setter triggers side effects on other reactive state:

```javascript
this.quickCreateState = reactive({
    _groupId: null,
    get groupId() { return this._groupId; },
    set groupId(id) {
        if (self.model.useSampleModel) {
            self.model.removeSampleDataInGroups();  // side effect
        }
        this._groupId = id;
    },
});
```

**Why this is a smell.**  The setter is an *effect* pretending to be
part of the *state*.  Conflating the two makes the dependency graph
opaque (readers can't see that mutating `groupId` clears sample data),
harder to test (every setter call has hidden downstream mutations),
and awkward to compose (side effects don't chain like data flows).

**Preferred alternative.**  Keep the state plain and express the side
effect with `useEffect` watching a signal dependency:

```javascript
this.quickCreateState = reactive({ groupId: null });
useEffect(
    () => {
        if (self.model.useSampleModel) {
            self.model.removeSampleDataInGroups();
        }
    },
    () => [this.quickCreateState.groupId],
);
```

The one legitimate surviving use case is *caching* inside the getter
(memoize an expensive derivation) — that's not a state mutation and
remains fine on a `SignalStore` getter.

> **Pattern 4 sites.** Every surviving setter has a documented constraint
> that defeats the `useEffect` rewrite; **zero are open refactor targets**:
>
> | Site | Verdict |
> |---|---|
> | `views/kanban/kanban_controller.js` (`set groupId`) | ⛔ Canonical exception to Pattern 4. The setter MUST clear sample data synchronously on the same microtask as the `groupId` mutation — see the comment block above the setter. A previous `useEffect` migration (commit `19fb5d01bb81`) was reverted because deferred cleanup broke 3 sample-data integration tests in `kanban_view.test.js` ("empty grouped kanban with sample data and click quick create" and siblings). The eslint-disable comment is explicit: *"synchronous timing contract; see comment above."* **Keep as-is.** |
> | `components/transition.js` (`set shouldMount`) | ⚠ Pattern 4 by syntax, but the setter implements a deliberate state-machine timing contract (`clearTimeout`, `prevState` tracking, `onNextPatch` scheduling). A `useEffect` rewrite changes observable timing. **Leave**. |
> | `components/transition.js` (`set shouldMount`, disabled-config branch) | ✗ Not Pattern 4. Pure passthrough `state.shouldMount = val`. |
> | `components/emoji_picker/emoji_picker.js` (`set searchTerm`) | ✗ Not Pattern 4. Delegation between `props.state` and `this.state`. |
> | `components/dropdown/_behaviours/dropdown_nesting.js` (`set isOpen`) | ⚠ Edge case — fires `BUS.trigger("dropdown-opened", this)` (fire-once-on-edge signal, not state mutation). `useEffect` rewrite would either fire too often or require a `prev`-tracking dance uglier than the setter. **Leave**. |
>
> Pattern 4 is a *vocabulary check* for new code review, not a backlog. When a new
> setter introduces cross-state side effects, the reviewer's question is:
> "is this the canonical synchronous-timing exception (kanban quick-create
> kind), the state-machine timing kind (transition kind), or genuinely an
> effect masquerading as state?" Only the third is a refactor.

## Model → renderer subscription: `useReactiveModel`

`model/model.js` gives view models a reactive re-render path that replaces
the legacy "deep render on every `ModelEvent.UPDATE`" bus listener:

- `Model` extends `SignalStore` and owns `_updateEpoch`, a counter bumped by
  every `notify()` (`model.js` — `this._updateEpoch++` right before the bus
  trigger; the bus event is kept for legacy/cross-addon consumers but is no
  longer load-bearing for local re-renders).
- `useReactiveModel(model)` (exported from `model/model.js`) wraps the model
  in `useState()` and reads `_updateEpoch` in `onWillRender`, so the calling
  component subscribes to the epoch: every `model.notify()` re-renders it
  directly — no parent deep render required. Use it in renderers that
  snapshot derived state from the model (e.g. PivotRenderer's `getTable()`).
- A model class whose whole view tree is on this pattern opts out of the
  legacy listener with `static reactiveRenderers = true` (checked in
  `useModelWithSampleData`; pivot and graph are opted out).

**CAUTION before opting a model out**: the legacy deep-render listener IS
load-bearing for any renderer that (a) receives the model as a stable prop
(OWL props-equality skips it on reactive controller renders) and (b)
snapshots derived state in `onWillUpdateProps` / `useEffect` deps. Still
depending on it: calendar, plus enterprise `web_map`, `web_cohort`,
`web_grid`, `web_gantt`, `social`. Audit the full renderer tree against
(a)+(b) first.

## Record State Architecture

Records maintain a three-layer state model:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  _values    │    │  _changes   │    │  data       │
│  (server)   │ +  │  (user)     │ =  │  (merged)   │
│             │    │  markRaw()  │    │  read by UI │
└─────────────┘    └─────────────┘    └─────────────┘
```

| Property | Source | Reactive? | Purpose |
|----------|--------|-----------|---------|
| `_values` | Server (read/write RPC) | No (markRaw) | Last-known server state |
| `_changes` | User edits | No (markRaw) | Accumulated unsaved changes |
| `data` | `{..._values, ..._changes}` | Yes | Merged view consumed by UI |
| `dirty` | Imperative plain field (set in `_applyChanges`, `discard`, `_load`) | Yes (reactive) | Whether record has unsaved edits. NOT computed from `_changes` — `dirty=true` can coexist with an empty `_changes` briefly during flow transitions. |
| `_invalidFields` | Validation | Yes (Set) | Fields that failed validation |

**Save flow**: `_changes` → RPC write → server returns new `_values` → `_changes` cleared → `data` rebuilt.
**Discard flow**: `_changes` cleared → `data` rebuilt from `_values` only → `dirty = false`.

**Scoped re-validation on commit**: committing changes re-checks
unset-required status only for fields whose status could actually have
changed. `computeRevalidationScope(changedFieldNames, activeFields)`
(`model/relational_model/record_utils.js`) returns the changed fields
plus every field whose `invisible` / `required` / `readonly` modifier
expression references one of them (a per-`activeFields` memoized dependency
map), plus fields with an unparseable modifier (always re-validated as a
fallback — fails safe). The scope is passed as `scopedFields` to
`_checkValidity({ removeInvalidOnly: true, scopedFields })`
(`record.js`; orchestration lives in
`model/relational_model/record_validator.js`), so a keystroke does not
re-evaluate the modifier expressions of every field in a large form.

## Form Save State Diagram

The form controller manages save/discard transitions through the model's mutex
for serialization. This is not implemented as a formal state machine but
follows this implicit state graph:

```
                    ┌──────────┐
                    │  CLEAN   │ ◄───────────────────────┐
                    │ dirty=F  │                         │
                    └────┬─────┘                         │
                         │ user edit                     │
                         ▼                               │
                    ┌──────────┐     discard()      ┌────┴─────┐
                    │  DIRTY   │ ──────────────────►│ DISCARD  │
                    │ dirty=T  │                    │ revert   │
                    └────┬─────┘                    └──────────┘
                         │ save()
                         ▼
                    ┌──────────┐
                    │ VALIDATING│
                    │ checkValidity
                    └────┬──┬──┘
                  valid  │  │ invalid
                         ▼  ▼
                    ┌─────────┐  ┌──────────┐
                    │ SAVING  │  │  ERROR   │
                    │ RPC     │  │ invalid  │
                    │ write() │  │ fields   │
                    └────┬────┘  └────┬─────┘
                         │            │ user fixes
                         │            └──► DIRTY
                         ▼
                    ┌──────────┐
                    │ RELOADING│
                    │ read()   │
                    └────┬─────┘
                         │
                         ▼
                       CLEAN
```

**Serialization**: All transitions go through `model.mutex.exec()`, ensuring
only one save/discard/load runs at a time.

**Urgent save**: On page unload (`beforeunload`), `urgentSave()` uses
`navigator.sendBeacon()` to fire-and-forget unsaved changes. This bypasses
the mutex and normal flow.

> **Optimistic-locking parity — field-scoped baseline values**: both paths
> send `kwargs.known_values`, a `{field: originally-loaded value}` map built
> once per save (`concurrencyBaseline`, `record_save.js`) from
> `record._values` for the fields being written — skipping uncomparable types
> (x2many, binary, html, date/datetime, json, properties, reference) and
> jsonb-backed `translate` / `company_dependent` fields. The urgent
> (sendBeacon) path attaches it via `urgentKwargs`
> (`record_save.js`); the normal path via `kwargs.known_values`
> (`record_save.js`); both only for existing records (`resId`
> truthy). Server side, `models/web_read.py:_check_concurrent_field_changes`
> rejects only genuine per-field conflicts, ignores concurrent writes to
> other fields, and **fails open** for fields with no baseline (an empty
> baseline means no check — correct on tab close, where the user's work must
> never be dropped). The client no longer sends the whole-record
> `last_write_date`; the server keeps that kwarg only as a legacy fallback,
> consulted when `known_values` is absent.

**Key files**:
- `views/form/form_controller.js` — `save()` entry point
- `views/form/form_controller.js` — `discard()` entry point
- `views/form/form_controller.js` — `beforeLeave()` auto-save
- `model/relational_model/record.js` — `_applyChanges()` (dirty tracking)
- `model/relational_model/record.js` — `discard()` (mutex-wrapped)
- `services/result_set_cache_invalidator_service.js` — `CLEAR-CACHES` emission (unlink + action_archive + action_unarchive; method set defined by `RESULT_SET_REMOVING_METHODS`; model-scoped on BOTH layers: RAM via reverse index, IndexedDB via cursor filter on the stored `model` — see Flow 14).

**All 6 CLEAR-CACHES emission sites in the web module:**

| File:Line | Trigger | Scope |
|---|---|---|
| `services/result_set_cache_invalidator_service.js` | `unlink` / `action_archive` / `action_unarchive` RPC response (set defined by `RESULT_SET_REMOVING_METHODS`) | tables: web_read, web_search_read, web_read_group; model-scoped in RAM only |
| `services/result_set_cache_invalidator_service.js` | `base.language.install` `lang_install` RPC response (a new language invalidates virtually everything cached) | all |
| `search/search_query_mutations.js` | `ir.filters` write/unlink (saved-favorite mutations) | `"get_views"` table |
| `webclient/actions/action_cache_invalidation.js` | `ir.actions.act_window` write/unlink | `"/web/action/load"` table |
| `views/view_service.js` | `ir.ui.view` / `ir.filters` write/unlink | `"get_views"` table |
| `webclient/webclient.js` | Post-service-worker-registration on hard refresh | all |

Plus **one listener** at `core/network/rpc.js` that routes the event to `rpc_cache.js` for cache invalidation.

## Model Load Lifecycle

> **`RelationalModelLoadCoordinator` was REMOVED** (commit `b906a0295d6` —
> "Dead code: load_coordinator (inlined)"). No component or service ever
> read its `status`, so the narration layer was deleted and
> `model/relational_model/load_coordinator.js` no longer exists. Do not
> cite it.

The load lifecycle is now carried by three primitives on
`RelationalModel` plus one observable flag:

| Primitive | Lives | Role |
|---|---|---|
| `model.keepLast` | `relational_model.js` (`markRaw(new KeepLast())`) | Cancellation: `load()` wraps `_loadData` in `keepLast.add(...)` (`relational_model.js`) so an in-flight load is dropped when a newer one starts. |
| `model.mutex` | RelationalModel | Per-record save/discard serialization. Used across `RelationalRecord.save` / `.discard` / `.delete` / `.update`. |
| `model.urgentSave` (`UrgentSaveCoordinator`) | `model/relational_model/urgent_save_coordinator.js` | Cross-cutting urgent-save mode, orthogonal to loading. |
| `model.isReady` | `model.js` / `relational_model.js` | Reactive "first load done" flag. Before the first load resolves, `load()` installs an **empty root** (`_createEmptyRoot`) so the control panel renders immediately; `isReady = true` is promoted in the same synchronous block as the real-root + config writes so OWL batches them into a single render. |

## Typed Events

Global events are defined in `core/events.js` and exported from `@web/core`.

| Constant | String Value | Bus | Purpose |
|----------|-------------|-----|---------|
| `AppEvent.SERVICES_LOADED` | `SERVICES-LOADED` | env.bus | All services ready |
| `AppEvent.WEB_CLIENT_READY` | `WEB_CLIENT_READY` | env.bus | WebClient mounted |
| `AppEvent.ACTION_MANAGER_UPDATE` | `ACTION_MANAGER:UPDATE` | env.bus | Controller changed |
| `AppEvent.ACTION_MANAGER_UI_UPDATED` | `ACTION_MANAGER:UI-UPDATED` | env.bus | UI render done |
| `AppEvent.WEBCLIENT_LOAD_DEFAULT_APP` | `WEBCLIENT:LOAD_DEFAULT_APP` | env.bus | Load home |
| `AppEvent.CLEAR_UNCOMMITTED_CHANGES` | `CLEAR-UNCOMMITTED-CHANGES` | env.bus | Save/discard all |
| `AppEvent.MENUS_APP_CHANGED` | `MENUS:APP-CHANGED` | env.bus | App switched |
| `AppEvent.BLOCK` / `UNBLOCK` | `BLOCK` / `UNBLOCK` | env.bus | UI blocking |
| `AppEvent.ACTIVE_ELEMENT_CHANGED` | `active-element-changed` | env.bus | Dialog focus |
| `AppEvent.RESIZE` | `resize` | env.bus | Window resize |
| `RpcEvent.REQUEST` / `RESPONSE` | `RPC:REQUEST` / `RPC:RESPONSE` | rpcBus | RPC lifecycle |
| `RpcEvent.CLEAR_CACHES` | `CLEAR-CACHES` | rpcBus | Invalidate caches |
| `RouterEvent.ROUTE_CHANGE` | `ROUTE_CHANGE` | routerBus | URL changed |
| `SearchModelEvent.UPDATE` | `update` | env.searchModel | Search state changed |
| `SearchModelEvent.FOCUS_VIEW` | `focus-view` | env.searchModel | Focus the view |
| `SearchModelEvent.FOCUS_SEARCH` | `focus-search` | env.searchModel | Focus the search bar |
| `SearchModelEvent.DIRECT_EXPORT_DATA` | `direct-export-data` | env.searchModel | Export all records |

## Server-side `__version` stamp for cached endpoints

`update: "always"` consumers ask the cache to revalidate against the server on
every read; the cache calls back with `(value, hasChanged)`.

Opted-in endpoints inject a `__version` field (sha256 of
canonical JSON) into their dict return value.  The cache compares versions
when both sides carry one (O(1), ~2,000× faster on the bench than the
`JSON.stringify` comparison), falls back to
`jsonEqual` otherwise.  Backward-compatible in both directions: old server +
new client → fallback path; new server + old client → unknown field ignored.

| Surface | File | Role |
|---|---|---|
| Decorator | `addons/odoo/odoo/tools/cache_version.py` `versioned` / `versioned_envelope` | Stamps `__version = sha256(json.dumps(result, sort_keys=True, default=str, separators=(",", ":")))` on dict returns (`versioned`); or stashes hash on `http.request._response_version` for non-dict returns (`versioned_envelope`). Located under `odoo.tools` so any addon can import without manifest dependency gymnastics. |
| Consumer | `addons/odoo/addons/web/static/src/core/network/rpc_cache.js` `payloadChanged` | Replaces direct `jsonEqual(prev, curr)` in the `hasChanged` computation. Prefers `__version === __version` when both sides have it. |

**Currently opted-in endpoints** (Phases 1 + 2 + 3 + 4a):
- `search_panel_select_range` / `search_panel_select_multi_range` — Phase 1, `@versioned`
- `web_search_read` (`models/web_read.py`) — Phase 2, `@versioned`, hot path
- `web_read_group` (`models/web_read_group.py`) — Phase 2, `@versioned`, hot path
- `web_read` (`models/web_read.py`) — Phase 3, `@versioned_envelope`, hot path (list return)
- `project.project.get_template_tasks` (`addons/project/models/project_project.py`) — Phase 4a, `@versioned_envelope`, consumed by `project_task_template_dropdown.js` and `fsm_task_template_dropdown.js`

**Pending follow-up endpoints** (also `update: "always"` consumers):
- m2o special data (`fields/relational/special_data.js`) — generic ORM proxy; per-`loadFn` identification needed before decorating the backing methods
- `project.project` template list (`project_template_dropdown.js` uses raw `searchRead`) — switch the JS to a custom `@versioned_envelope` server method, e.g. `get_project_templates`, when the perf win is profiled to matter

### Two decorator forms

| Form | When | Mechanism | Survives JSON round-trip? |
|---|---|---|---|
| `@versioned` | Method returns a `dict` | Mutates the dict in-place: `result["__version"] = sha256(...)` | Yes — `__version` is a JSON key |
| `@versioned_envelope` | Method returns a `list`, scalar, or anything non-dict | Stashes hash on `http.request._response_version`; dispatcher (`core/odoo/http/dispatcher.py` `_response`) lifts it as `version` sibling-of-`result` in the JSON-RPC envelope; `rpc.js` re-attaches as `result.__version` for objects/arrays | RAM: yes (`structuredClone` preserves array own-props). IndexedDB: no (`JSON.stringify` drops array own-props on encrypt); self-heals on next refresh |

The client-side `payloadChanged` reads `result[VERSION_FIELD]` uniformly — agnostic
to which decorator the server used.

The hash uses `sort_keys=True` so the digest is invariant under Python dict
insertion order — two interpreter runs over the same query can yield
different insertion orders and the version must stay stable across them.

### Comparison cascade (cheap → expensive)

When `update: "always"` fires, `payloadChanged(prev, curr)` walks four layers,
returning at the first that produces an answer:

| # | Layer | Cost | Wins when |
|---|---|---|---|
| 1 | `prev === curr` | O(1) | The same reference is passed twice (rare) |
| 2 | `prev.__version !== curr.__version` | O(1) | Both sides have a version stamp |
| 3 | `shapeDiffers(prev, curr)` — array/object length, type mismatch | O(1) | Row appended/removed; type changed |
| 4 | `!jsonEqual(prev, curr)` — full deep compare | O(n) | Same shape, possibly same content |

Layer 3 makes the version-less fallback path (still used by `web_read`,
template dropdowns, m2o special data) much cheaper for the common
append/remove case — benchmarked at ~400× speedup over the layer-4 fallback
for a 200-record list when length differs by one, with ~1 ns/call overhead
when shapes match and the call falls through.
