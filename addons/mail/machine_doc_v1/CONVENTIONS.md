# Mail Module Conventions

Module-specific patterns, rules, and gotchas for working in `addons/mail`.

> **See also**: `MODEL_MAP.md` (the `mixin.mail.thread` API these conventions reference),
> `STATE_MANAGEMENT.md` (the JS store framework), `ASSET_LAYERS.md` (the layer import rule),
> `ARCHITECTURE.md` (the two data planes).

## Python conventions

### 1. Mail-enable a model with `_inherit`, never re-implement

A business model becomes mail-enabled by inheriting the mixins — do **not** reimplement
messaging:

```python
class MyModel(models.Model):
    _name = "my.model"
    _inherit = ["mixin.mail.thread", "mixin.mail.activity"]
```

It then has `message_ids`, `message_follower_ids`, `activity_ids`, tracking, and the email
gateway. Class-level knobs on `mixin.mail.thread` tune behavior:

| Attribute | Default | Effect |
|-----------|---------|--------|
| `_mail_post_access` | `"write"` | Access level required to post on the record |
| `_mail_flat_thread` | `True` | Link orphan messages to the first message instead of threading |
| `_mail_thread_customer` | `False` | Treat the record's partner as the customer for notifications |
| `_primary_email` | `"email"` | Field used when the gateway creates a record from an alias |

### 2. `message_post` is the canonical posting API

All posting — chatter UI, templates, gateway, programmatic — funnels through
`self.message_post(**kwargs)` (`mixin_mail_thread.py`). **Never `create()` a `mail.message`
directly**: you would bypass follower notification, tracking subtypes, the
`_message_post_after_hook`, and the bus push. Related entry points:
`message_post_with_source` (render a view/template), `message_mail_with_source` (email only,
no thread message), `message_notify` (notification not stored as a thread message),
`_message_log` (internal note, no notification).

### 3. Suggested-recipients / partner-resolution helpers live on `base`, not `mixin.mail.thread`

`_message_get_suggested_recipients_sources`, `_message_get_suggested_recipients`,
`_mail_get_partners`, `_mail_get_customer`, `_partner_find_from_emails`, `_notify_get_reply_to`
and `_mail_track` are defined on the `base` inherit (`models/base.py`), so **every** Odoo
model has them — not only mail-threaded ones. When overriding suggested recipients, override on
your model (they resolve through the MRO); `mixin.mail.thread.cc` is a precedent
(`_message_get_suggested_recipients_sources`).

> **The hook is `_message_get_suggested_recipients_sources`, not
> `_message_add_suggested_recipients`.** The `_add_`-named pair built a mapping and returned
> it, so both are `_message_get_*_sources` now; only the one that genuinely mutates in place
> kept the verb (`_message_add_suggested_recipients_from_replies`). An override still written
> against the old name is **silently inert** — it overrides nothing and raises nothing.
> See MODEL_MAP.md.

### 4. Field tracking is declarative + hook-driven

Add `tracking=True` to a field and `write()` posts a tracking message. The pipeline is
`_track_prepare` → `_message_track` (diffs, creates `mail.tracking.value` rows) →
`_track_subtype(initial_values)` (chooses the subtype) → `_track_template(changes)` (optional
template) → `_track_finalize`. Override `_track_subtype` to route a specific change to a
specific `mail.message.subtype`. `mixin.mail.tracking.duration` builds on top to compute
time-in-stage and "rotting".

### 5. The email gateway two-hook contract

Incoming email routed to a model calls exactly one of two hooks:
- `message_new(msg_dict, custom_values=None)` — create a new record from the email.
- `message_update(msg_dict, update_vals=None)` — append the email to an existing thread.
Override these (not `message_process`/`message_route`, which are framework routing) to
customize gateway behavior. `mixin.mail.thread.cc` overrides both to track `email_cc`.

### 6. `mixin.template.reset` for module-shipped records

`mail.template` (and other `mixin.template.reset` models) can be reset to their XML source via
`reset_template()`. When editing a shipped template's XML, remember users may have customized
their copy; the reset wizard is the sanctioned way back to source.

## JavaScript conventions

### 7. Define a model with `class extends Record` + `<Class>.register()`

Every JS model is a `Record` subclass with a `static id`, `fields.*` declarations, and a
trailing `.register()` (see `STATE_MANAGEMENT.md`). There are **39** such classes (counted
by `.register()` call sites, not by grepping `extends Record` — see `ARCHITECTURE.md`). When
adding one:
1. `static _name = "<python.model>"` (omit only for JS-only models like `Composer`, `ChatHub`).
2. Declare relations with `fields.One(Target)` / `fields.Many(Target)`, and add
   `{inverse: "<field>"}` **only when the target model declares the reciprocal relation** —
   that is what keeps the two directions in sync. **49 of the 176 relations declare one**;
   the other 127 have no reciprocal field (`res.country`, `res.groups.privilege`,
   `mail.canned.response`, …) and must omit it. `make_store` validates the pair while
   building the store and throws
   `Field X.y declares inverse "z", but Target has no fields.One()/fields.Many() named "z"`
   (`model/make_store.js`), so naming an inverse that does not exist takes the whole client
   down at boot rather than degrading quietly — there is no gate to add, the store itself is
   the gate and every HOOT suite boots it.

   > `RecordUses` does **not** depend on `inverse`, contrary to what this list said until
   > 2026-08-17. It is maintained from the `RecordList` itself — `record._.uses.add(recordList)`
   > in `model/record_list.js`, called unconditionally — while `inverse` is only ever read
   > inside `if (inverse)` guards. Omitting `inverse` cannot make `RecordUses` inconsistent.
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
`mixin.bus.listener`); JS services subscribe by the exact string. Established types:
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

2. **The service worker is not bundled.** `static/src/service_worker.js` appears in **no**
   manifest bundle — it is served as **raw text** and never compiled in (its own header is
   `/** @odoo-module native */`, which is irrelevant here: nothing includes it). Its pure-logic
   helpers live in `service_worker_utils.js`, which **is** added to `web.assets_unit_tests` so
   HOOT can test them. `webmanifest.py` injects push-notification code into the worker for
   internal users by overriding `_get_service_worker_content` (it declares **no** routes).

3. **`selfie_segmentation.js` is eager — don't `loadJS` it.** It ships in `web.assets_backend`
   (and `mail.assets_public`). Calling `loadJS` on it after page load re-evaluates an already
   loaded library — the exact hazard web's `CONVENTIONS.md` warns about. The truly lazy libs
   are `lame.js` and `odoo_sfu.js` (declared as `dynamic_children` for `import()`).

4. **15 of the 40 registered models have no `static _name`** and are keyed by class name:
   `ChatHub`, `ChatWindow`, `Composer`, `DataResponse`, `DiscussApp`, `DiscussAppCategory`,
   `Failure`, `MessageReactions`, `MessagingMenu`, `Record`, `Rtc`, `Settings`, `Store`,
   `Thread`, `Volume`. (The other 25 declare one.) Their `getName()` falls back to the class name, so a server
   payload keyed by a python model cannot address them.

   **"No `static _name`" does not mean "no python counterpart"** — that is the trap:
   - `Thread` is the one exception to the rule above: python payloads *do* reach it, because
     `pyToJsModels` maps `discuss.channel` and `mixin.mail.thread` onto it (gotcha 6).
   - `Settings` mirrors `res.users.settings`, but is fed by the dedicated
     `res.users.settings` **bus type** (`res_users_settings.py` → `_bus_send`), not by
     model-keyed insertion.

   Only `Composer`, `ChatHub`, `ChatWindow`, `Failure` and `DataResponse` are truly
   client-side-only state with no server model behind them at all.

5. **Persona = `res.partner` ∪ `mail.guest`.** There is no single `Persona` model. `store.self`
   resolves to `self_partner || self_guest`. Author of a message may be `author_id`
   (`res.partner`) **or** `author_guest_id` (`mail.guest`) — handle both.

6. **`Thread` is keyed by `AND("model", "id")`, not `id` alone.** A thread can be a
   `discuss.channel`, a `mixin.mail.thread` document, or a mailbox — its identity is the
   (model, id) pair. `pyToJsModels` maps both `"discuss.channel"` and `"mixin.mail.thread"` to the
   `Thread` JS class.

7. **The internal-subtype filter covers followers only — explicit recipients are
   notified regardless, and that is intended.** In
   `mail.followers._get_recipient_data`, the JOIN drops share partners from an
   `internal = True` subtype (e.g. `mail.mt_note`), but it keys off each
   *follower's* own subscription; the `pids` branch of the UNION hardcodes
   `internal = FALSE`, so a partner named in `partner_ids` is always notified.
   That is deliberate — `test_mail`'s `TestServerActionsEmail.test_action_message_post`
   asserts a share partner receives a `mail.mt_note` post — so **do not "fix" it**
   by filtering share partners on the subtype: every contact without a user has
   `partner_share = True`, so such a guard silences ordinary customer
   notifications and breaks ~7 `test_mail` tests.

   Know the consequence, though: log-note mode still ships @mentions as
   `partner_ids` (`static/src/core/common/message_post.js`), so @mentioning a
   *portal user* in a Log Note e-mails them the note body while
   `mail.message._get_forbidden_access` denies them read access to that same
   message (its share-user branch forbids `subtype.internal` before the
   "notified" exemption is considered). The notification side legitimately
   out-reaches the read ACL here; any change to that is a product decision, not a
   bug fix.

8. **Restricted ("static") rendering resolves an expression's declared root.**
   `mail_allowed_qweb_expressions` (`models/base.py`) is the security boundary for
   non-`group_mail_template_editor` users. `_resolve_static_expression`
   (`models/mixin_mail_render.py`) honours the root the expression names — `object`
   or `user` — and raises `SyntaxError` on any other; an unknown root is refused,
   not guessed. Do not go back to `expr.split(".")[1:]` against the record — that
   made the allow-list and the evaluator disagree about what is being read.

   **It is no longer a regex, and that matters.** The safety check
   (`_is_static_expression` → `ir.qweb._is_expression_allowed`) and the renderer
   (`_render_template_qweb_static` / `_render_template_inline_template_static`) now
   walk the **same parsed tree**. They used to disagree: the check walked the
   element tree while the renderer ran a regex over a normalised source string, and
   lxml exposes no element for text inside a comment, `<script>` or `<style>` — so a
   directive written there was called safe, handed to the regex renderer, and raised
   a bare `SyntaxError` that reached the user as "Oops! We couldn't save your
   template". If you are looking for `_render_regex_resolve`, that is the name it
   had before the two were made one walk.

9. **The round-numbered hardening suites are gone — do not add another.**
   `test_mail_hardening_v2..v13` and `test_mail_audit_v6*` were AgroMarin regression
   suites accumulated one audit round at a time; all twenty-one were deleted in
   `e4df7f5569b`. A version number is not a subject: the suites overlapped, nothing
   said which round owned a behaviour, and a defect they covered was findable only by
   reading all of them. **A regression test goes in the suite named after what it
   tests** — `test_mail_message.py`, `test_mail_activity.py`,
   `test_mail_message_access_parity.py` — and the invariant that survived the deletion
   is the parity pin, which asserts the access rule's two spellings agree rather than
   re-asserting one round's findings. Upstream is still the baseline, not the ceiling;
   only the filing changed. See `TEST_TAGS.md`.
