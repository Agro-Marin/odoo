# Design: State-Machine Write Validation for `sale.order`

- **Date:** 2026-07-04
- **Module:** `addons/sale` (reference implementation; later graduates to `order.mixin` / mirrored in `purchase`)
- **File touched:** `addons/sale/models/sale_order.py`
- **Status:** Approved design, pre-implementation

## 1. Purpose

Replace the crude one-liner `sale.order.write()` guard with a **best-in-class,
declarative, extensible** state-machine write-validation mechanism that becomes
the reference pattern for state management across fork models.

Current code (`sale_order.py:651`):

```python
def write(self, vals):
    if "pricelist_id" in vals and any(so.state == "done" for so in self):
        raise UserError(_("You cannot change the pricelist of a confirmed order !"))
    return super().write(vals)
```

Problems: hardcoded, single-purpose, not extensible, no transition validation,
and — critically — **not the pattern the fork already uses on order lines**. The
order *line* mixin (`base_order/models/order_line_fields_mixin.py`) already has a
mature validator-registry (`_validate_write_vals` / `_get_validate_write_vals_methods`
/ `_get_protected_fields`), but the order *header* has none of it. This design
lifts that proven line-level pattern up to the header and extends it.

## 2. Scope

In scope (all enforced on `write`):

1. **Locked finalization guard** — whitelist (strictest): a locked order freezes
   all user-editable business fields except an explicit allow-list.
2. **Per-state frozen fields** — blacklist: named fields frozen in a given state
   (preserves today's `pricelist_id`-in-`done` rule, now declarative).
3. **Transition guard** — declarative state→state graph; rejects illegal jumps
   from RPC/import that bypass the `action_*` methods.

Out of scope:

- Create-side validation. Orders are always created in `draft` by the sequence
  logic; transitions need a prior state. Matches the line mixin (write-only).
- Migrating the mechanism into `order.mixin` / purchase. Deliberately deferred;
  `base_order` is the eventual shared home, but this lands in `sale` first as a
  self-contained reference.
- Refactoring the `locked` field's other responsibilities (cancel guard,
  invoicing rules). `locked` is a legitimate cross-cutting "finalized" flag.

## 3. Context / prior art

State-dependent mutability is a solved problem outside Odoo. This design is a
pragmatic, ORM-appropriate synthesis of the industry approaches:

- **Declarative transition graph** (Spring Statemachine, XState, django-fsm) →
  `_STATE_TRANSITIONS`.
- **Declarative constraint matrix** (SAP status management, Salesforce validation
  rules keyed on `ISCHANGED` + `PRIORVALUE` + status) → the per-state frozen map.
  The `write()` override is chosen precisely because it — like Salesforce's
  `ISCHANGED`/`PRIORVALUE` — has access to *the delta* (`vals`) and *the prior
  state* (`self.state`), which `@api.constrains` structurally lacks.
- **Whitelist finalization** (SAP "allowed transactions", DDD aggregates) → the
  locked guard. This is **stricter than Odoo's own strictest model**
  (`account.move` uses blacklist + `skip_readonly_check` bypass for posted moves).

Type-state / DDD "make illegal states unrepresentable" is the theoretical ideal
but impossible in a dynamically-typed mutable ORM, so it is intentionally not
pursued.

## 4. Architecture — validator registry

Mirrors `order_line_fields_mixin` exactly, giving header and line one shared shape:

```python
def write(self, vals):
    self._validate_write_vals(vals)
    return super().write(vals)

def _validate_write_vals(self, vals):
    for name in self._get_validate_write_vals_methods():
        getattr(self, name)(vals)

def _get_validate_write_vals_methods(self):
    return [
        "_validate_write_locked_order",
        "_validate_write_state_frozen_fields",
        "_validate_write_state_transition",
    ]
```

- **Ordering:** locked → state-freeze → transition (most restrictive first).
- **Fail-fast between validators**; **report all offending fields within** a
  validator.
- Child models extend by appending validator names to the registry list.

## 5. Validators

### 5.1 `_validate_write_locked_order` — whitelist

```python
_LOCKED_WRITABLE_FIELDS = {"locked", "priority"}

def _validate_write_locked_order(self, vals):
    if self.env.context.get("bypass_locked_check"):
        return
    locked = self.filtered("locked")
    if not locked:
        return
    forbidden = (set(vals) & locked._get_user_editable_fields()) - self._LOCKED_WRITABLE_FIELDS
    if forbidden:
        raise UserError(_(
            "This order is locked and cannot be modified. "
            "Unlock it first to change: %s", <human labels>))

def _get_user_editable_fields(self):
    """User-settable business fields — excludes computed, related, readonly,
    mail/activity and magic columns so framework writes are never blocked."""
    return {
        name for name, f in self._fields.items()
        if f.store and not f.related and not f.readonly
        and name not in models.MAGIC_COLUMNS
    }
```

Note: `not f.readonly` already excludes display-only computed fields (which are
readonly). Editable computed fields (compute + inverse, `readonly=False`) are
genuine user-settable business fields and remain in the universe by design.

Design notes:

- **Universe scoping** is what makes a whitelist ORM-safe: `write()` fires for
  framework operations (chatter `message_ids`, `activity_ids`, stored-computed
  recomputation). Those fields are computed/readonly/related and thus excluded
  from `_get_user_editable_fields()`, so they pass untouched. Only genuine
  business fields are subject to the whitelist.
- **Allow-list `{locked, priority}`:** `locked` so the order can be unlocked;
  `priority` because it is meant to stay adjustable (purchase's `action_lock`
  writes `{"locked": True, "priority": "0"}`).
- **Locking is never self-blocked:** at the moment `action_lock` writes
  `{"locked": True}`, `self.locked` is still `False` (pre-write), so
  `self.filtered("locked")` is empty and the guard passes. Unlocking passes via
  the allow-list.
- **`bypass_locked_check`** context key — escape hatch for migrations / data
  fixes, mirroring `account.move`'s `skip_readonly_check`.

### 5.2 `_validate_write_state_frozen_fields` — blacklist per state

```python
def _get_state_frozen_fields(self):
    return {"done": {"pricelist_id"}}   # preserves current behavior; extensible

def _validate_write_state_frozen_fields(self, vals):
    frozen_map = self._get_state_frozen_fields()
    changed = set(vals)
    for order in self:
        frozen = frozen_map.get(order.state, set()) & changed
        if frozen:
            raise UserError(_(
                "You cannot modify %(fields)s on a %(state)s order.",
                fields=<labels>, state=order.state))
```

Replaces the hardcoded `pricelist_id`/`done` one-liner with the identical rule,
now declarative and per-model overridable.

### 5.3 `_validate_write_state_transition` — transition graph

```python
_STATE_TRANSITIONS = {
    "draft":  {"done", "cancel"},
    "done":   {"cancel"},
    "cancel": {"draft"},
}

def _validate_write_state_transition(self, vals):
    if "state" not in vals:
        return
    target = vals["state"]
    for order in self:
        if order.state == target:
            continue                       # no-op self-write allowed
        if target not in self._STATE_TRANSITIONS.get(order.state, set()):
            raise UserError(_(
                "Cannot move order %(name)s from %(src)s to %(dst)s.",
                name=order.display_name, src=order.state, dst=target))
```

Graph matches the real action methods: `action_confirm` (`draft→done`),
`action_cancel` (`draft/done→cancel`), `action_draft` (`cancel→draft`).

## 6. Error UX

- Human-readable field labels resolved via `ir.model.fields` (as the line
  mixin's `_validate_write_locked_order` already does), for message consistency
  across header and line.
- `UserError` for all three (business-rule violations, not data-integrity
  constraints).

## 7. Known boundaries (documented, not addressed here)

- Raw-writing `state="cancel"` on a **locked** order bypasses
  `_can_cancel_except_locked` (which lives in `action_cancel`), because `state`
  is `readonly` and therefore outside the locked whitelist universe. This gap
  exists in the current code too. Future extension: a `_can_transition(src, dst)`
  hook consulted by the transition validator. Not expanded now (YAGNI).

## 8. Test plan

Per validator (Odoo `TransactionCase`):

- **locked:**
  - frozen business field on a locked order raises `UserError`
  - `locked` / `priority` writable while locked
  - unlock (`locked=False`) succeeds
  - `action_lock` and `action_confirm` (auto-lock) are not self-blocked
  - a framework write on a locked order (post a chatter message / trigger a
    stored-compute) does **not** raise
  - `with_context(bypass_locked_check=True).write(...)` writes through
- **state-freeze:**
  - `pricelist_id` change while `done` raises
  - `pricelist_id` change while `draft` succeeds
  - `action_confirm` unaffected
- **transition:**
  - every legal edge passes (`draft→done`, `draft→cancel`, `done→cancel`,
    `cancel→draft`)
  - illegal edges raise (`cancel→done`, `done→draft`, `draft→draft` is a
    permitted no-op)
  - all three `action_*` methods still succeed end-to-end

## 9. Homogenization follow-ups (tracked, not in this change)

- Graduate the mechanism into `order.mixin` so `purchase.order` inherits it.
- Purchase's richer state set (`draft`/`sent`?/`to approve`/`purchase`/`done`/
  `cancel`) will define its own `_STATE_TRANSITIONS` and `_get_state_frozen_fields`.
- Align header and line `_get_validate_write_vals_methods` naming once shared.
