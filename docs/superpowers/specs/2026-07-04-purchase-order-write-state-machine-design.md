# Design: State-Machine Write Validation for `purchase.order`

- **Date:** 2026-07-04
- **Module:** `addons/purchase`
- **Files touched:** `addons/purchase/models/purchase_order.py`,
  `addons/purchase/tests/` (new test), `addons/purchase/tests/__init__.py`
- **Status:** Approved design, pre-implementation
- **Sibling spec:** `2026-07-04-sale-order-write-state-machine-design.md`
  (the reference implementation this ports from)

## 1. Purpose

Bring `purchase.order` to parity with the state-machine write-validation
mechanism sale just adopted. Today `purchase.order` has **no `write()` override at
all** — raw RPC/import writes can perform illegal `state` jumps or mutate a locked
order with nothing to stop them. This design lifts sale's proven header pattern
into purchase verbatim, homogenizing the two order headers.

This is the first concrete unit of an ongoing method-by-method homogenization of
`sale` and `purchase`.

## 2. Decisions (locked in during brainstorming)

- **Approach A — faithful port.** Mirror `sale_order.py` exactly. **No changes to
  `sale`. No changes to either line model.** The order-vs-line dispatch-style
  split (order = unconditional, line = `hasattr`-guarded) already exists
  identically in both modules and is preserved.
- **Empty frozen-fields map.** `_get_state_frozen_fields()` returns `{}`.
  Purchase has no `pricelist_id` (sale's only frozen field), and no concrete
  purchase freeze-rule has been identified. The hook is kept for structural
  parity and future extension, but invents no new business rule. Confirmed +
  locked POs are already fully frozen by the locked guard.
- **Dispatch style — unconditional.** The new order-level `_validate_write_vals`
  calls validators unconditionally (`getattr(self, name)(vals)`), matching
  `sale.order`. Purchase's line model keeps its existing `hasattr` guard (which
  already matches `sale`'s line model).

## 3. Correction to the sale spec's follow-up

`2026-07-04-sale-order-write-state-machine-design.md` §9 assumes purchase has a
"richer state set (`draft`/`sent?`/`to approve`/`purchase`/`done`/`cancel`)". That
is **not** the case in this fork. `purchase/const.py::ORDER_STATE` is:

```python
ORDER_STATE = [("draft", "RFQ"), ("done", "Purchase Order"), ("cancel", "Cancelled")]
```

— identical in shape to `sale/const.py::ORDER_STATE`. Therefore purchase reuses
sale's transition graph and locked-writable set **unchanged**, with no
purchase-specific transition modeling required.

## 4. Scope

In scope (all enforced on `write`):

1. **Locked finalization guard** (whitelist) — a locked order freezes all
   user-editable business fields except `_LOCKED_WRITABLE_FIELDS`.
2. **Per-state frozen fields** (blacklist) — hook present, currently empty.
3. **Transition guard** — declarative `state→state` graph rejecting illegal jumps
   from RPC/import that bypass the `action_*` methods.

Out of scope:

- Create-side validation. POs are always created in `draft` by the sequence
  logic; matches sale (write-only).
- Any change to `sale`, to `purchase_order_line`, or to `sale_order_line`.
- The shared-mixin refactor (extracting the machinery into a common
  `order.mixin` / `base_order` home so all four classes inherit it). This is the
  correct eventual direction and is deferred to a later homogenization session.

## 5. Verification of the transition graph against real actions

Confirmed by reading purchase's action methods and view:

| Edge | Source |
| --- | --- |
| `draft → done` | `action_confirm` → `_prepare_confirmation_values()` returns `{"state": "done", ...}` |
| `draft → cancel` | `action_cancel` (button `invisible="state not in ['draft','done']"`) |
| `done → cancel` | `action_cancel` (same) |
| `cancel → draft` | `action_draft` (button `invisible="state != 'cancel'"`) |

No purchase code performs any other raw `state` write, so the graph below blocks
nothing legitimate.

## 6. Implementation

### 6.1 `purchase/models/purchase_order.py`

**(a) Import** alongside the existing `odoo` imports:

```python
from odoo.orm.primitives import MAGIC_COLUMNS
```

**(b) Class constants**, after `_order` (currently line 38):

```python
_STATE_TRANSITIONS = {
    "draft":  {"done", "cancel"},
    "done":   {"cancel"},
    "cancel": {"draft"},
}
_LOCKED_WRITABLE_FIELDS = {"locked", "priority"}
```

`{locked, priority}` verified: `action_lock` writes
`{"locked": True, "priority": "0"}` and `action_unlock` writes `{"locked": False}`,
so both must remain writable while locked.

**(c) `write()` override** in the CRUD section (after `create`/`copy`/ondelete):

```python
def write(self, vals):
    self._validate_write_vals(vals)
    return super().write(vals)
```

**(d) New "WRITE VALIDATION" section**, copied verbatim from
`sale_order.py:3652–3742` plus `_get_field_labels` (`sale_order.py:754`), with the
single intentional divergence that `_get_state_frozen_fields` returns `{}`:

- `_validate_write_vals(self, vals)` — unconditional dispatch
- `_get_validate_write_vals_methods` →
  `["_validate_write_locked_order", "_validate_write_state_frozen_fields", "_validate_write_state_transition"]`
- `_get_state_frozen_fields` → `return {}` (extensible hook; no rule invented)
- `_validate_write_locked_order` — whitelist freeze on `locked` orders, honoring
  the `bypass_locked_check` context key
- `_get_user_editable_fields` — stored, non-related, non-readonly, non-`MAGIC_COLUMNS`
- `_validate_write_state_frozen_fields` — no-op while the map is empty
- `_validate_write_state_transition` — rejects illegal `state` moves; permits
  `state == target` no-op self-writes
- `_get_field_labels` — human labels via `ir.model.fields` for error messages

Message strings are kept identical to sale ("...order...") for cross-module
consistency.

### 6.2 `purchase/tests/test_purchase_order_write_validation.py` (new)

Sale currently has **no** tests for this pattern, so purchase gets fresh coverage
(a genuine improvement, and a template to backfill sale later). Registered in
`purchase/tests/__init__.py`. Odoo `TransactionCase`:

- **locked guard:**
  - writing a frozen business field on a locked PO raises `UserError`
  - `locked` / `priority` writable while locked
  - unlock (`locked=False`) succeeds
  - `action_lock` / `action_confirm` (auto-lock path) are not self-blocked
  - a framework write on a locked PO (e.g. post a chatter message / trigger a
    stored compute) does **not** raise
  - `with_context(bypass_locked_check=True).write(...)` writes through
- **state-freeze:**
  - with the empty map, writing any field on a `done` PO is **not** blocked by
    this validator (guards against false positives; locked guard tested
    separately)
- **transition:**
  - every legal edge passes (`draft→done`, `draft→cancel`, `done→cancel`,
    `cancel→draft`)
  - illegal edges raise (`cancel→done`, `done→draft`); `draft→draft` no-op passes
  - `action_confirm` / `action_cancel` / `action_draft` still succeed end-to-end

## 7. Known boundaries (inherited from sale, documented not addressed)

- Raw-writing `state="cancel"` on a **locked** PO bypasses the locked cancel guard
  in `action_cancel`, because `state` is `readonly` and thus outside the locked
  whitelist universe. This mirrors the identical boundary in `sale.order`; a
  future `_can_transition(src, dst)` hook is the eventual fix (YAGNI now).

## 8. Homogenization follow-ups (tracked, not in this change)

- Extract the shared machinery into a common mixin so `sale.order`,
  `purchase.order`, and both line models inherit one copy (Approach C).
- Backfill the sale side with the tests written here.
- Once a concrete purchase freeze-rule surfaces, populate
  `_get_state_frozen_fields`.
