# State Management — the JS `Store` / `Record` framework

> The `mail` module ships its **own client-side reactive ORM** in
> `static/src/model/`. It is the heart of the Discuss / messaging client: server data is
> upserted into a graph of `Record` instances that OWL components render reactively. This
> doc is the reference for that framework — the mail analogue of web's
> `STATE_MANAGEMENT.md`.

> **See also**: `ARCHITECTURE.md` (where the store sits in the request flow),
> `MODEL_MAP.md` (the Python models these JS records mirror), `ROUTE_MAP.md` (the
> `/mail/data` ↔ `/mail/action` endpoints that feed the store).

## Why a second ORM?

The webclient's `RelationalModel` (`web/static/src/model/`) is view-scoped: one model per
open view, discarded on navigation. Discuss needs a **single long-lived, cross-view graph**
— the same `Message`, `Thread`, `ResPartner` records are shared by the Discuss app, every
chat window, the chatter, and the messaging-menu systray, and are mutated live by bus
notifications. So mail maintains its own store: one `Store` singleton holding a normalized,
reactive, id-keyed record graph.

## The `model/` package

| File | Exports | Role |
|------|---------|------|
| `record.js` | `class Record` | Base class for all models; insert/get/register statics + instance CRUD |
| `store.js` | `class Store extends Record`, `storeInsertFns` | The store record; owns the `MAKE_UPDATE` cycle + queue flushing + `insert()` |
| `record_list.js` | `class RecordList extends Array`, `RecordListInternal` | A relational field value — an `Array` subclass over a `data: string[]` of localIds |
| `record_uses.js` | `class RecordUses` | Reverse-relation tracker: `Map<Record, Map<fieldName, count>>` of who points at a record |
| `model_internal.js` | `class ModelInternal` | Per-**Model** field metadata (Maps: Attr/One/Many/Compute/Sort/Inverse/OnAdd/OnDelete/OnUpdate/TargetModel/Type/Default, `idFields`) |
| `record_internal.js` | `class RecordInternal` | Per-**record** engine: `prepareField`, `requestCompute`, `requestSort`, `compute`, `sort`, `onUpdate`, `downgradeProxy` |
| `store_internal.js` | `class StoreInternal extends RecordInternal` | The 8 flush queues + the `UPDATE` counter |
| `make_store.js` | `makeStore(env, {localRegistry})` | Factory: builds reactive Model objects + proxy Classes from `modelRegistry`, wires inverses, bootstraps the Store |
| `misc.js` | `modelRegistry`, `fields`, `AND`, `OR`, type guards | Registry, field factory, id-expression helpers |
| `export.js` | `export *` from `make_store.js`, `record.js`, `store.js` + `{AND, fields, OR}` from `misc.js` | Public entry point (the `*_internal`, `record_list`, `record_uses` modules are imported directly, not re-exported here) |

## Defining a model

Every model is a class `extends Record` with a `static id`, field declarations, and a
trailing `<Class>.register()`. There are **38 model classes** across `static/src/`
(enumerated in `ARCHITECTURE.md` and `DIRECTORY_MAP.md`).

```javascript
// core/common/message_model.js (shape)
import { Record, fields } from "@mail/core/common/record";

export class Message extends Record {
    static _name = "mail.message";        // python model name (falls back to class name)
    static id = "id";                     // identity field, or AND(...) / OR(...)

    author_id = fields.One("res.partner");
    attachment_ids = fields.Many("ir.attachment", { inverse: "message" });
    reactions = fields.Many("MessageReactions", { inverse: "message" });
    // ...
}
Message.register();                        // adds to modelRegistry (category "discuss.model")
```

- **`static _name`** — the python model name used when routing server data. If omitted,
  `getName()` falls back to the JS class name (`"Composer"`, `"ChatHub"`, `"Failure"`,
  `"DataResponse"` are JS-only, no python model).
- **`static id`** — the identity key. A field name (`"id"`), or a composite/alternate
  expression: `Thread` uses `static id = AND("model", "id")`.
- **`register()`** — `Record.register()` adds the class to `modelRegistry`
  (`registry.category("discuss.model")` in `misc.js`). Distinct from
  `discussComponentRegistry` (`registry.category("discuss.component")` in
  `core/common/discuss_component_registry.js`) used for overridable UI — see ARCHITECTURE.md.

### Field factory (`misc.js` `fields`)

| Call | Field kind | Notable options |
|------|-----------|-----------------|
| `fields.Attr(default, {compute, onUpdate, sort, type})` | scalar | `type: "date"｜"datetime"` auto-(de)serializes to luxon |
| `fields.One(TargetModel, {compute, inverse, onAdd, onDelete, onUpdate})` | x2one | stored internally as a single-entry `RecordList` |
| `fields.Many(TargetModel, {compute, inverse, onAdd, onDelete, onUpdate, sort})` | x2many | auto-sorted when `sort` is set |
| `fields.Html(default, {...})` | scalar | markup-aware (`markup()` ↔ `["markup", str]` tuple) |
| `fields.Date({...})` / `fields.Datetime({...})` | scalar | luxon `DateTime` values |
| `AND(...)` / `OR(...)` | id expression | used in `static id` |

`ModelInternal.prepareField` reads these into the per-model metadata Maps. **Relational
writes accept command tuples**: `["ADD", …]`, `["DELETE", …]`, `["ADD.noinv", …]`,
`["DELETE.noinv", …]` (the `.noinv` variants skip inverse maintenance; validated by
`isCommand`).

## Insert / upsert — the idempotent entry point

`Record.insert(data)` (and `Store.insert(dataByModel)`) is an **upsert**: existing record
updated, missing record created, always keyed by `static id`. This is the single write path
for both initial payloads and live bus pushes — calling it twice with the same data is a
no-op beyond the first.

```
Record.insert(data, options)
  → MAKE_UPDATE(...)                         // wrap in the update cycle
    → _insert → preinsert (get() ?? new())   // create just enough for the localId
             → update(data)                  // batched field writes
```

- `Record.get(data)` — lookup by id-data → `this.records[localId]` (or `undefined`).
- `Record.localId(data)` / `_localId` — computes the `"<Model>,<id>"` localId string.
- `record.update(data)` — batched field write via `store._.updateFields`.
- `record.delete()` — enqueues a soft delete → hard delete.
- `record.eq/notEq/in/notIn` — identity comparison on `_raw`.
- `record.toData()` — serialize the record graph back to store-insertable data.

## The reactivity triad

Every record and every `RecordList` exists as three linked objects (`store.js` header,
`make_store.js`):

| Layer | What | Reactive? |
|-------|------|-----------|
| `_raw` | plain instance, raw values | No — internal work |
| `_proxyInternal` | `Proxy` implementing field get/set semantics + commands | writes notify, reads don't subscribe |
| `_proxy` | `reactive(_proxyInternal)` (OWL `reactive`) | Yes — handed to components/business code |

Getters **downgrade** a `_proxy` receiver back to `_proxyInternal`
(`RecordInternal.downgradeProxy` / `RecordListInternal.downgradeProxy`) so internal reads
stay subscription-free while component reads (through `_proxy`) subscribe normally.

### The `MAKE_UPDATE` cycle

All mutations funnel through `Store.MAKE_UPDATE(fn)`, which increments `_.UPDATE` and — only
at the **outermost** call — flushes 8 queues in a fixed order, repeated to a fixpoint
(iteration cap 1000):

```
FC  computes    →  FS  sorts       →  FA  onAdd      →  FD  onDelete
→  FU  onUpdate  →  RO  onChange    →  RD  record deletes  →  RHD  hard deletes
```

Errors are collected in `_.ERRORS` and rethrown at flush end (or `console.warn` when
`warnErrors`). **Computes and sorts are always eager** — queued at record creation and on any
dependency change, observed or not; there is no per-field `eager` opt-in and no `markEager`
symbol. `store.env` holds the `OdooEnv`.

### `RecordUses` and `RecordList`

- **`RecordUses`** (`record._.uses`) — reverse-relation bookkeeping: `Map<Record, Map<field,
  count>>` keyed **by reference** (not localId, to survive delete+reinsert aliasing).
  `add`/`delete` adjust the count for a list's `owner` + `name`; the `RD` flush uses it to
  detach a deleted record from everyone pointing at it.
- **`RecordList`** (`extends Array`) — backing store is `data: string[]` (localIds). Read
  methods (`map/filter/find/some/forEach/reduce/slice/at/includes/…`) are reimplemented over
  `data` + `store.recordByLocalId` to avoid materializing proxy arrays. Mutators
  (`push/pop/splice/sort/add/delete/clear/…`) run inside `MAKE_UPDATE`, maintain inverses +
  `uses`, and queue `onAdd`/`onDelete`. `reverse`/`fill`/`copyWithin` throw (in-place reorder
  unsupported).

## The `store` service and server-data flow

`core/common/store_service.js` defines `class Store extends BaseStore` (the `model/store.js`
`Store`), calls `Store.register()`, and registers the service:

```javascript
export const storeService = {
    dependencies: ["bus_service", "im_status", "ui", "popover"],
    start(env, services) { /* makeStore(env) → seed → subscribe → onStarted */ },
};
registry.category("services").add("mail.store", storeService);
```

`start()` runs `makeStore(env)`, seeds with `store.insert(session.storeData)`, sets
`self_guest`/`settings` defaults, subscribes to `BUS:RECONNECT`, and calls `store.onStarted()`.
The `init_messaging` fetch (`initialize()`) is **not** eager — it is fired by the WebClient
patch (backend) or the public-page boot. Components read the store with
`this.store = useService("mail.store")` — the returned `_proxy` is already reactive, so no
extra `useState` wrapping is needed.

### Fetching server data

| Method (`store_service.js`) | Role |
|------|------|
| `fetchStoreData(name, params, {readonly, …})` | Queue a fetch param + a `DataResponse` request record (debounced) |
| `_fetchStoreDataDebounced()` | Batch queued params → `_fetchStoreDataRpc` → `this.insert(data)` → resolve each `DataResponse` |
| `_fetchStoreDataRpc(fetchParams)` | `rpc(readonly ? "/mail/data" : "/mail/action", { fetch_params, context })` |
| `initialize()` | `await fetchStoreData("init_messaging")` |
| `Store.insert(dataByModelName)` (`model/store.js`) | Iterate model → rows, map py→js model name, handle per-row `_DELETE`, then `store[modelName].insert(rows)` |

Python → JS model-name mapping lives in `pyToJsModels`
(`{"discuss.channel": "Thread", "mail.thread": "Thread"}`) and `addFieldsByPyModel`
(`{"discuss.channel": {model: "discuss.channel"}}`), wired via `patch(storeInsertFns, {...})`.
There is **no** function literally named `insertModelData`; ingestion is
`Store.insert` → per-model `Record.insert`. Initial payloads: `session.storeData` (backend
HTML) and `odoo.discuss_data` (public-page boot).

### Bus notifications → store

Services subscribe with `this.busService.subscribe(type, cb)` in `setup()`. The generic
server-push channel is **`mail.record/insert`** → `this.store.insert(payload)`.

| Service | File | Subscribed notification types |
|---------|------|-------------------------------|
| `mail.core.common` | `core/common/mail_core_common_service.js` | `mail.record/insert`, `mail.message/delete`, `mail.message/toggle_star`, `ir.attachment/delete`, `res.users.settings` |
| `discuss.core.common` | `discuss/core/common/discuss_core_common_service.js` | `discuss.channel/new_message`, `discuss.channel/delete`, `discuss.channel/transient_message`, `discuss.channel.member/fetched`, … |

Python emits these via `record._bus_send("<model>/<verb>", payload)` (see CONVENTIONS.md on
the bus convention).

## Model registries — two, don't confuse them

| Registry (export name) | Category string | Holds | Populated by |
|------------------------|-----------------|-------|--------------|
| `modelRegistry` | `discuss.model` | Model **classes** (`Record` subclasses) | `Record.register()` at each model file's end |
| `discussComponentRegistry` | `discuss.component` | Overridable **OWL components** (message actions, action lists, avatar cards, call dropdowns) | explicit `.add()` in the component files |

`makeStore` reads `modelRegistry`, builds a reactive Model object + proxy Class per entry,
and wires inverse relations before returning the bootstrapped `Store` proxy.
