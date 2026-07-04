# Sale Order State-Machine Write Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `sale.order.write()`'s hardcoded pricelist guard with a declarative, extensible validator-registry enforcing locked-finalization, per-state frozen fields, and legal state transitions.

**Architecture:** A `write()` override calls `_validate_write_vals(vals)`, which iterates method names from `_get_validate_write_vals_methods()` — mirroring the existing `order_line_fields_mixin` pattern so header and line share one shape. Three validators: a whitelist locked guard (scoped over introspected user-editable fields so framework writes pass), a per-state frozen-fields blacklist, and a transition graph.

**Tech Stack:** Odoo 19 (fork), Python, Odoo `TransactionCase` test framework.

## Global Constraints

- Target file: `addons/sale/models/sale_order.py` only (self-contained reference; graduation to `order.mixin` is a later, separate change).
- Follow `doc/coding_guidelines.rst`; new Python must pass `ruff check`.
- State values for `sale.order`: `draft`, `done`, `cancel` (fork renamed upstream `sale` → `done`; `sent` is a boolean, not a state).
- Confirmed state is `"done"` (NOT `"sale"`).
- Locked allow-list: `{"locked", "priority"}`.
- Locked bypass context key: `bypass_locked_check`.
- `MAGIC_COLUMNS` import path: `from odoo.orm.primitives import MAGIC_COLUMNS` (not re-exported from `odoo.models`).
- Errors are `UserError`.
- Tests: class `TestSaleOrderStateMachine(SaleCommon)`, decorated `@tagged("post_install", "-at_install")`, in `addons/sale/tests/test_sale_order_state_machine.py`, registered in `addons/sale/tests/__init__.py`.
- Run tests with:
  `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale:TestSaleOrderStateMachine --stop-after-init`
  (substitute a scratch DB name for `<db>`).

## Fixtures available from `SaleCommon`

- `self.sale_order` — a draft SO with one product line, confirmable via `action_confirm()` (→ `state == "done"`).
- `self.empty_order` — a draft SO with no lines.
- `self.partner`, `self.product`, `self.env["product.pricelist"]` (pricelists enabled).

---

## Task 1: Registry scaffolding + per-state frozen fields

Establishes the validator registry and replaces the existing hardcoded `write()` guard with the declarative `_validate_write_state_frozen_fields`, preserving today's behavior (pricelist frozen in `done`).

**Files:**
- Modify: `addons/sale/models/sale_order.py` (replace `write` at lines ~651-654)
- Create: `addons/sale/tests/test_sale_order_state_machine.py`
- Modify: `addons/sale/tests/__init__.py` (add import)

**Interfaces:**
- Produces:
  - `write(self, vals)` — overridden; calls `_validate_write_vals(vals)` then `super().write(vals)`.
  - `_validate_write_vals(self, vals) -> None` — iterates registry, calls each validator.
  - `_get_validate_write_vals_methods(self) -> list[str]` — returns validator method names.
  - `_get_state_frozen_fields(self) -> dict[str, set[str]]` — `{state: {field names}}`.
  - `_validate_write_state_frozen_fields(self, vals) -> None` — raises `UserError` if a frozen field is written in that state.
  - `_get_field_labels(self, field_names) -> str` — comma-joined human labels via `ir.model.fields`.

- [ ] **Step 1: Register the new test module**

In `addons/sale/tests/__init__.py`, add (keep alphabetical if the file is ordered):

```python
from . import test_sale_order_state_machine
```

- [ ] **Step 2: Write the failing test**

Create `addons/sale/tests/test_sale_order_state_machine.py`:

```python
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestSaleOrderStateMachine(SaleCommon):

    def _other_pricelist(self):
        return self.env["product.pricelist"].create({"name": "Other PL"})

    # --- per-state frozen fields ---

    def test_pricelist_frozen_when_done(self):
        self.sale_order.action_confirm()
        self.assertEqual(self.sale_order.state, "done")
        with self.assertRaises(UserError):
            self.sale_order.pricelist_id = self._other_pricelist()

    def test_pricelist_writable_when_draft(self):
        self.assertEqual(self.sale_order.state, "draft")
        pricelist = self._other_pricelist()
        self.sale_order.pricelist_id = pricelist
        self.assertEqual(self.sale_order.pricelist_id, pricelist)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale:TestSaleOrderStateMachine.test_pricelist_frozen_when_done --stop-after-init`
Expected: FAIL — `test_pricelist_writable_when_draft` passes but `test_pricelist_frozen_when_done` currently passes too via the old guard; the point of this task is to keep it green while swapping the implementation. Run the full class; both tests must pass after Step 4. (If the module wasn't loaded, expect an ImportError until Step 1 is applied.)

- [ ] **Step 4: Replace the `write` guard with the registry**

In `addons/sale/models/sale_order.py`, replace the existing method:

```python
def write(self, vals):
    if "pricelist_id" in vals and any(so.state == "done" for so in self):
        raise UserError(_("You cannot change the pricelist of a confirmed order !"))
    return super().write(vals)
```

with:

```python
def write(self, vals):
    self._validate_write_vals(vals)
    return super().write(vals)

# ------------------------------------------------------------
# WRITE VALIDATION
# ------------------------------------------------------------

def _validate_write_vals(self, vals):
    """Run all registered write validators before persisting ``vals``."""
    for method_name in self._get_validate_write_vals_methods():
        getattr(self, method_name)(vals)

def _get_validate_write_vals_methods(self):
    """Validator method names for write. Override to extend."""
    return [
        "_validate_write_state_frozen_fields",
    ]

def _get_state_frozen_fields(self):
    """Map of ``{state: {field names frozen in that state}}``."""
    return {
        "done": {"pricelist_id"},
    }

def _validate_write_state_frozen_fields(self, vals):
    """Reject writes to fields frozen in the record's current state."""
    frozen_map = self._get_state_frozen_fields()
    changed = set(vals)
    for order in self:
        frozen = frozen_map.get(order.state, set()) & changed
        if frozen:
            raise UserError(
                _(
                    "You cannot modify %(fields)s on a %(state)s order.",
                    fields=order._get_field_labels(frozen),
                    state=order.state,
                ),
            )

def _get_field_labels(self, field_names):
    """Comma-joined human field labels for ``field_names`` on this model."""
    fields_info = (
        self.env["ir.model.fields"]
        .sudo()
        .search(
            [
                ("name", "in", list(field_names)),
                ("model", "=", self._name),
            ],
        )
    )
    return ", ".join(fields_info.mapped("field_description")) or ", ".join(
        sorted(field_names),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale:TestSaleOrderStateMachine --stop-after-init`
Expected: PASS (both tests).

- [ ] **Step 6: Lint**

Run: `ruff check addons/sale/models/sale_order.py addons/sale/tests/test_sale_order_state_machine.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add addons/sale/models/sale_order.py addons/sale/tests/test_sale_order_state_machine.py addons/sale/tests/__init__.py
git commit -m "refactor(sale): declarative write-validation registry for sale.order

Replace the hardcoded pricelist/done guard in write() with a validator
registry mirroring order_line_fields_mixin, plus a declarative per-state
frozen-fields map. Preserves existing pricelist-in-done behavior.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: State-transition guard

Adds a declarative transition graph and rejects illegal `state` jumps from raw writes (RPC/import) that bypass the `action_*` methods.

**Files:**
- Modify: `addons/sale/models/sale_order.py` (add validator + class constant; extend registry)
- Modify: `addons/sale/tests/test_sale_order_state_machine.py` (add tests)

**Interfaces:**
- Consumes: `_get_validate_write_vals_methods` (Task 1), `_get_field_labels` (Task 1).
- Produces:
  - `_STATE_TRANSITIONS: dict[str, set[str]]` — class attribute.
  - `_validate_write_state_transition(self, vals) -> None` — raises `UserError` on an illegal `state` change.

- [ ] **Step 1: Write the failing tests**

Append to `TestSaleOrderStateMachine`:

```python
    # --- transitions ---

    def test_legal_transition_draft_to_done(self):
        self.sale_order.write({"state": "done"})
        self.assertEqual(self.sale_order.state, "done")

    def test_legal_transition_done_to_cancel(self):
        self.sale_order.write({"state": "done"})
        self.sale_order.write({"state": "cancel"})
        self.assertEqual(self.sale_order.state, "cancel")

    def test_legal_transition_cancel_to_draft(self):
        self.sale_order.write({"state": "cancel"})
        self.sale_order.write({"state": "draft"})
        self.assertEqual(self.sale_order.state, "draft")

    def test_illegal_transition_cancel_to_done(self):
        self.sale_order.write({"state": "cancel"})
        with self.assertRaises(UserError):
            self.sale_order.write({"state": "done"})

    def test_illegal_transition_done_to_draft(self):
        self.sale_order.write({"state": "done"})
        with self.assertRaises(UserError):
            self.sale_order.write({"state": "draft"})

    def test_noop_state_write_allowed(self):
        self.assertEqual(self.sale_order.state, "draft")
        self.sale_order.write({"state": "draft"})  # no-op, must not raise
        self.assertEqual(self.sale_order.state, "draft")

    def test_action_methods_still_work(self):
        self.sale_order.action_confirm()
        self.assertEqual(self.sale_order.state, "done")
        self.sale_order.action_cancel()
        self.assertEqual(self.sale_order.state, "cancel")
        self.sale_order.action_draft()
        self.assertEqual(self.sale_order.state, "draft")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale:TestSaleOrderStateMachine --stop-after-init`
Expected: FAIL on `test_illegal_transition_*` (illegal writes currently succeed).

- [ ] **Step 3: Add the transition validator**

In `addons/sale/models/sale_order.py`, add the class constant near the top of the model body (with other class attributes, before field definitions):

```python
_STATE_TRANSITIONS = {
    "draft": {"done", "cancel"},
    "done": {"cancel"},
    "cancel": {"draft"},
}
```

Extend the registry:

```python
def _get_validate_write_vals_methods(self):
    """Validator method names for write. Override to extend."""
    return [
        "_validate_write_state_frozen_fields",
        "_validate_write_state_transition",
    ]
```

Add the validator (below `_validate_write_state_frozen_fields`):

```python
def _validate_write_state_transition(self, vals):
    """Reject illegal ``state`` transitions on raw writes."""
    if "state" not in vals:
        return
    target = vals["state"]
    for order in self:
        if order.state == target:
            continue  # no-op self-write
        if target not in self._STATE_TRANSITIONS.get(order.state, set()):
            raise UserError(
                _(
                    "Cannot move order %(name)s from %(src)s to %(dst)s.",
                    name=order.display_name,
                    src=order.state,
                    dst=target,
                ),
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale:TestSaleOrderStateMachine --stop-after-init`
Expected: PASS (all tests).

- [ ] **Step 5: Lint**

Run: `ruff check addons/sale/models/sale_order.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add addons/sale/models/sale_order.py addons/sale/tests/test_sale_order_state_machine.py
git commit -m "feat(sale): declarative state-transition guard on sale.order write

Add _STATE_TRANSITIONS graph (draft->done/cancel, done->cancel,
cancel->draft) enforced in write(), rejecting illegal jumps from
raw RPC/import writes that bypass the action_* methods.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Locked finalization guard (whitelist)

Adds the strictest guard: a locked order freezes every user-editable business field except the allow-list, scoped over introspected fields so framework/computed/mail writes pass. Includes the `bypass_locked_check` escape hatch.

**Files:**
- Modify: `addons/sale/models/sale_order.py` (add import, validator, allow-list, universe helper; extend registry)
- Modify: `addons/sale/tests/test_sale_order_state_machine.py` (add tests)

**Interfaces:**
- Consumes: `_get_validate_write_vals_methods` (Task 1), `_get_field_labels` (Task 1).
- Produces:
  - `_LOCKED_WRITABLE_FIELDS: set[str]` — class attribute `{"locked", "priority"}`.
  - `_get_user_editable_fields(self) -> set[str]` — introspected business-field universe.
  - `_validate_write_locked_order(self, vals) -> None` — raises `UserError` for a frozen write on a locked order.

- [ ] **Step 1: Write the failing tests**

Append to `TestSaleOrderStateMachine`:

```python
    # --- locked guard ---

    def _lock(self, order):
        order.action_confirm()
        order.action_lock()
        self.assertTrue(order.locked)

    def test_locked_freezes_business_field(self):
        self._lock(self.sale_order)
        with self.assertRaises(UserError):
            self.sale_order.date_order = "2020-01-01 00:00:00"

    def test_locked_allows_priority(self):
        self._lock(self.sale_order)
        self.sale_order.priority = "1"  # allow-listed, must not raise
        self.assertEqual(self.sale_order.priority, "1")

    def test_locked_allows_unlock(self):
        self._lock(self.sale_order)
        self.sale_order.action_unlock()  # writes locked=False
        self.assertFalse(self.sale_order.locked)

    def test_locked_allows_framework_write(self):
        self._lock(self.sale_order)
        # posting a chatter message writes message-related fields; must not raise
        self.sale_order.message_post(body="hello on a locked order")

    def test_locked_bypass_context(self):
        self._lock(self.sale_order)
        self.sale_order.with_context(bypass_locked_check=True).write(
            {"date_order": "2020-01-01 00:00:00"},
        )
        self.assertEqual(str(self.sale_order.date_order), "2020-01-01 00:00:00")

    def test_action_lock_not_self_blocked(self):
        self.sale_order.action_confirm()
        self.sale_order.action_lock()  # writing locked=True must not raise
        self.assertTrue(self.sale_order.locked)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale:TestSaleOrderStateMachine --stop-after-init`
Expected: FAIL on `test_locked_freezes_business_field` and `test_locked_bypass_context` (no locked guard yet); the allow/framework/unlock tests pass trivially.

- [ ] **Step 3: Add the import**

In `addons/sale/models/sale_order.py`, add near the other `odoo` imports (after line 9):

```python
from odoo.orm.primitives import MAGIC_COLUMNS
```

- [ ] **Step 4: Add the locked guard**

Add the class attribute near `_STATE_TRANSITIONS`:

```python
_LOCKED_WRITABLE_FIELDS = {"locked", "priority"}
```

Extend the registry (locked first — most restrictive):

```python
def _get_validate_write_vals_methods(self):
    """Validator method names for write. Override to extend."""
    return [
        "_validate_write_locked_order",
        "_validate_write_state_frozen_fields",
        "_validate_write_state_transition",
    ]
```

Add the validator and universe helper:

```python
def _validate_write_locked_order(self, vals):
    """Freeze all user-editable business fields on locked orders.

    Whitelist model: only ``_LOCKED_WRITABLE_FIELDS`` may change while
    locked. Scoped over ``_get_user_editable_fields`` so framework writes
    (chatter, activities, stored-compute) are never blocked. Bypassable
    via the ``bypass_locked_check`` context key.
    """
    if self.env.context.get("bypass_locked_check"):
        return
    locked = self.filtered("locked")
    if not locked:
        return
    forbidden = (
        set(vals) & locked._get_user_editable_fields()
    ) - self._LOCKED_WRITABLE_FIELDS
    if forbidden:
        raise UserError(
            _(
                "This order is locked and cannot be modified. "
                "Unlock it first to change: %s",
                locked._get_field_labels(forbidden),
            ),
        )

def _get_user_editable_fields(self):
    """User-settable business fields.

    Excludes computed/display (readonly), related, and magic columns, so
    framework and computed writes fall outside the locked whitelist.
    """
    return {
        name
        for name, field in self._fields.items()
        if field.store
        and not field.related
        and not field.readonly
        and name not in MAGIC_COLUMNS
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale:TestSaleOrderStateMachine --stop-after-init`
Expected: PASS (all tests).

- [ ] **Step 6: Lint**

Run: `ruff check addons/sale/models/sale_order.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add addons/sale/models/sale_order.py addons/sale/tests/test_sale_order_state_machine.py
git commit -m "feat(sale): whitelist locked-order write guard on sale.order

Locked orders freeze every user-editable business field except an
explicit allow-list ({locked, priority}), scoped over introspected
fields so framework writes pass. Adds bypass_locked_check escape hatch.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Full-suite regression check

Ensure the new guards don't break existing sale flows.

**Files:** none (verification only)

- [ ] **Step 1: Run the sale module test suite**

Run: `./odoo-bin -d <db> -u sale --test-enable --test-tags /sale --stop-after-init`
Expected: no new failures attributable to `sale_order.py` write validation. Investigate any failure that references `state`, `locked`, `pricelist_id`, or `write`.

- [ ] **Step 2: Run adjacent suites that confirm/lock/cancel sale orders**

Run: `./odoo-bin -d <db> -u sale_stock,sale_management --test-enable --test-tags /sale_stock,/sale_management --stop-after-init`
Expected: PASS. These exercise `action_confirm`/`action_lock`/`action_cancel` end-to-end; a transition-map or locked-universe mistake surfaces here.

- [ ] **Step 3: Record results**

If green, note in the final message which suites ran and passed. If red, do not mark the plan complete — capture the failing test names and the offending validator.

---

## Self-Review Notes

- **Spec coverage:** Task 1 → §5.2 (per-state frozen) + §4 (registry) + §6 (labels); Task 2 → §5.3 (transitions); Task 3 → §5.1 (locked whitelist, universe scoping, allow-list, bypass); Task 4 → §8 test plan regression. §7 known boundary (raw `state=cancel` on locked) is intentionally not implemented — documented only.
- **Deferred (not in this plan):** §9 graduation to `order.mixin` / purchase mirroring.
- **Type consistency:** `_get_field_labels`, `_get_validate_write_vals_methods`, `_get_state_frozen_fields`, `_get_user_editable_fields`, `_STATE_TRANSITIONS`, `_LOCKED_WRITABLE_FIELDS` used with identical names/signatures across tasks.
