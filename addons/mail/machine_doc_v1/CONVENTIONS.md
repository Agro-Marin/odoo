# Mail Module Conventions

Module-specific patterns, rules, and gotchas for working in `addons/odoo/addons/mail`.

> **See also**: `MODEL_MAP.md` (the `mail.thread` API these conventions reference),
> `STATE_MANAGEMENT.md` (the JS store framework), `ASSET_LAYERS.md` (the layer import rule),
> `ARCHITECTURE.md` (the two data planes).

## Python conventions

### 1. Mail-enable a model with `_inherit`, never re-implement

A business model becomes mail-enabled by inheriting the mixins — do **not** reimplement
messaging:

```python
class MyModel(models.Model):
    _name = "my.model"
    _inherit = ["mail.thread", "mail.activity.mixin"]
```

It then has `message_ids`, `message_follower_ids`, `activity_ids`, tracking, and the email
gateway. Class-level knobs on `mail.thread` tune behavior:

| Attribute | Default | Effect |
|-----------|---------|--------|
| `_mail_post_access` | `"write"` | Access level required to post on the record |
| `_mail_flat_thread` | `True` | Link orphan messages to the first message instead of threading |
| `_mail_thread_customer` | `False` | Treat the record's partner as the customer for notifications |
| `_primary_email` | `"email"` | Field used when the gateway creates a record from an alias |

### 2. `message_post` is the canonical posting API

All posting — chatter UI, templates, gateway, programmatic — funnels through
`self.message_post(**kwargs)` (`mail_thread.py`). **Never `create()` a `mail.message`
directly**: you would bypass follower notification, tracking subtypes, the
`_message_post_after_hook`, and the bus push. Related entry points:
`message_post_with_source` (render a view/template), `message_mail_with_source` (email only,
no thread message), `message_notify` (notification not stored as a thread message),
`_message_log` (internal note, no notification).

### 3. Suggested-recipients / partner-resolution helpers live on `base`, not `mail.thread`

`_message_add_suggested_recipients`, `_message_get_suggested_recipients`,
`_mail_get_partners`, `_mail_get_customer`, `_partner_find_from_emails`, `_notify_get_reply_to`
and `_mail_track` are defined on the `base` inherit (`models/base.py`), so **every** Odoo
model has them — not only mail-threaded ones. When overriding suggested recipients, override on
your model (they resolve through the MRO); `mail.thread.cc` is a precedent
(`_message_add_suggested_recipients`).

### 4. Field tracking is declarative + hook-driven

Add `tracking=True` to a field and `write()` posts a tracking message. The pipeline is
`_track_prepare` → `_message_track` (diffs, creates `mail.tracking.value` rows) →
`_track_subtype(initial_values)` (chooses the subtype) → `_track_template(changes)` (optional
template) → `_track_finalize`. Override `_track_subtype` to route a specific change to a
specific `mail.message.subtype`. `mail.tracking.duration.mixin` builds on top to compute
time-in-stage and "rotting".

### 5. The email gateway two-hook contract

Incoming email routed to a model calls exactly one of two hooks:
- `message_new(msg_dict, custom_values=None)` — create a new record from the email.
- `message_update(msg_dict, update_vals=None)` — append the email to an existing thread.
Override these (not `message_process`/`message_route`, which are framework routing) to
customize gateway behavior. `mail.thread.cc` overrides both to track `email_cc`.

### 6. `template.reset.mixin` for module-shipped records

`mail.template` (and other `template.reset.mixin` models) can be reset to their XML source via
`reset_template()`. When editing a shipped template's XML, remember users may have customized
their copy; the reset wizard is the sanctioned way back to source.

## JavaScript conventions

### 7. Define a model with `class extends Record` + `<Class>.register()`

Every JS model is a `Record` subclass with a `static id`, `fields.*` declarations, and a
trailing `.register()` (see `STATE_MANAGEMENT.md`). There are **38** such classes. When
adding one:
1. `static _name = "<python.model>"` (omit only for JS-only models like `Composer`, `ChatHub`).
2. Declare relations with `fields.One(Target, {inverse})` / `fields.Many(Target, {inverse})` —
   always set `inverse` so the reverse relation and `RecordUses` stay consistent.
3. `<Class>.register();` at the file's end — this adds it to `modelRegistry`
   (`registry.category("discuss.model")`). Forgetting it means the model never exists at runtime.

### 8. `store.insert()` is the single, idempotent write path

Server data — initial payload, `/mail/data` fetch, or a `mail.record/insert` bus push — is
merged with `store.insert(dataByModel)` (upsert keyed by `static id`). Consequences:
- Always insert by **python model name** (`this["res.partner"].insert(...)`,
  `this["mail.message"].insert(...)`); `Store.insert` maps py→js names via `pyToJsModels`.
- Inserting is safe to repeat — the second call with the same id is a no-op beyond field
  updates. Never mutate the record graph outside an `update()`/`insert()`/RecordList mutator
  (those wrap `MAKE_UPDATE`; bare writes skip the compute/sort/onChange flush).

### 9. Layer import rule — `common/` imports downward only

Every `static/src/` file lives in a layer (`common` / `web` / `public_web` / `web_portal` /
`public`; see `ASSET_LAYERS.md`). **`common/` must never import from a higher layer** — it
ships on the anonymous public page, where `web/`, `web_portal/` are absent, so such an import
would be `undefined` at runtime. Higher layers import downward (`web` → `public_web` →
`common`). To extend a lower-layer component from a higher layer, use `patch(...)` on its
prototype in a `*_patch.js` file, not a cross-layer import.

> Note: the manifest keeps discuss in a deterministic remove-then-re-add block. Per the
> manifest comment, this is **no longer for JS import order** (the historical core→discuss
> inversion was fixed) — it survives only for the **SCSS cascade** (discuss overrides core)
> and the **relative order of side-effect modules** (patches, registry additions with no
> import edge). Don't reorder it assuming it's load-bearing for imports.

### 10. Bus notification naming: `"<model>/<verb>"`

Python pushes updates with `record._bus_send("<model>/<verb>", payload)` (base method from
`bus.listener.mixin`); JS services subscribe by the exact string. Established types:
`mail.record/insert` (the generic upsert channel), `mail.message/delete`,
`mail.message/toggle_star`, `res.users.settings`, `discuss.channel/new_message`,
`discuss.channel/delete`, `discuss.channel/transient_message`,
`discuss.channel.member/fetched`. When adding a notification, follow the `model/verb`
convention and subscribe in the matching `*_service.js` (`mail.core.common` for mail-core
types, `discuss.core.common` for channel types).

### 11. Two similarly-named registries — don't confuse them

Their names look alike (`discuss.model` vs `discuss.component`) but they are separate
registries holding different things:

- `modelRegistry` (`model/misc.js`) → `registry.category("discuss.model")` holds **model
  classes**; populated by `<Class>.register()`.
- `discussComponentRegistry` (`core/common/discuss_component_registry.js`) →
  `registry.category("discuss.component")` holds **overridable OWL components** (message
  actions, action lists, avatar cards, call dropdowns); populated by explicit `.add()`.
Extending message actions or the avatar card means adding to
`discussComponentRegistry` (category `discuss.component`), not `modelRegistry`.

## Controller / auth conventions

### 12. Guest access via `@add_guest_to_context`, not a custom auth method

Mail registers **no** `_auth_method_*`. Public + guest routes use `auth="public"` and the
`@add_guest_to_context` decorator (`tools/discuss.py`), which resolves the `dgid` cookie
(`"<guest_id>|<access_token>"`) into `context["guest"]` via
`mail.guest._get_guest_from_token` (constant-time `consteq`). Handlers read the guest with
`_get_guest_from_context()`. New public discuss routes should follow this exact pattern (see
`ROUTE_MAP.md` "Guest auth flow"). Websocket auth reuses the same cookie.

### 13. Backend data goes through `/mail/data` (read) or `/mail/action` (write)

Prefer adding a **fetch param** dispatched inside `WebclientController` /
`DiscussChannelWebclientController._process_request_*` over minting a new controller route —
that keeps the request batched into the store's single round-trip and cache-friendly. Only add
a dedicated route for genuinely separate operations (uploads, RTC signaling, worklet serving).

## Gotchas

1. **`except A, B:` is valid here (Py 3.14 / PEP 758).** Several controllers use the
   bracketless `except TypeError, ValueError:` form. This is **correct** — Python 3.14 allows
   it when there is no `as` clause, and this fork's ruff config enforces the bracketless form.
   Do **not** "fix" it to `except (A, B):` — that causes a lint loop (see workspace CLAUDE.md).

2. **The service worker is not bundled.** `static/src/service_worker.js` is served as **raw
   text** (`@odoo-module ignore` semantics), not compiled into a bundle. Its pure-logic
   helpers live in `service_worker_utils.js`, which **is** added to `web.assets_unit_tests` so
   HOOT can test them. `webmanifest.py` injects push-notification code into the worker for
   internal users by overriding `_get_service_worker_content` (it declares **no** routes).

3. **`selfie_segmentation.js` is eager — don't `loadJS` it.** It ships in `web.assets_backend`
   (and `mail.assets_public`). Calling `loadJS` on it after page load re-evaluates an already
   loaded library — the exact hazard web's `CONVENTIONS.md` warns about. The truly lazy libs
   are `lame.js` and `odoo_sfu.js` (declared as `dynamic_children` for `import()`).

4. **`Composer`, `ChatHub`, `ChatWindow`, `Failure`, `DataResponse` are JS-only models** — no
   `static _name`, no python counterpart. Their `getName()` falls back to the class name.
   Don't try to `store.insert` them from a server payload keyed by a python model.

5. **Persona = `res.partner` ∪ `mail.guest`.** There is no single `Persona` model. `store.self`
   resolves to `self_partner || self_guest`. Author of a message may be `author_id`
   (`res.partner`) **or** `author_guest_id` (`mail.guest`) — handle both.

6. **`Thread` is keyed by `AND("model", "id")`, not `id` alone.** A thread can be a
   `discuss.channel`, a `mail.thread` document, or a mailbox — its identity is the
   (model, id) pair. `pyToJsModels` maps both `"discuss.channel"` and `"mail.thread"` to the
   `Thread` JS class.

7. **Fork hardening suites are real tests, not scaffolding.** `test_mail_hardening_v2..v8` and
   `test_mail_audit_v6*` are AgroMarin-added regression suites (upstream is the baseline, not
   the ceiling). Keep them green; `_v6`/`_v7`/`_v8` carry dedicated tags, the earlier ones run
   under the `-u mail` filter. See `TEST_TAGS.md`.
