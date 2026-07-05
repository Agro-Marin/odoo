# Purchase Order Write State-Machine Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port sale's declarative write-validation state machine (`_validate_write_vals` + `_STATE_TRANSITIONS` + `_LOCKED_WRITABLE_FIELDS` + validators) into `purchase.order`, reaching exact parity with `sale.order`.

**Architecture:** Add a `write()` override to `purchase.order` that runs a registry of validators before `super().write()`. Three validators — locked-order whitelist, per-state frozen fields (empty hook for now), and a declarative transition graph — mirror `sale.order` verbatim. No changes to `sale`, and no changes to either order-line model.

**Tech Stack:** Odoo 19 (Python 3.14), `TransactionCase` via `AccountTestInvoicingCommon`, `ruff` for lint.

## Global Constraints

- **Faithful port:** copy `sale_order.py:662–768` verbatim; the ONLY intentional divergence is `_get_state_frozen_fields` returning `{}` instead of `{"done": {"pricelist_id"}}`.
- **Sale is untouched.** Both order-line models are untouched.
- **Dispatch is unconditional** (`getattr(self, name)(vals)`), matching `sale.order`.
- **State graph** (identical to sale): `{"draft": {"done", "cancel"}, "done": {"cancel"}, "cancel": {"draft"}}`.
- **Locked-writable set** (identical to sale): `{"locked", "priority"}`.
- Message strings kept identical to sale (they read "...order...", valid for purchase).
- Follow `doc/coding_guidelines.rst`; new Python must pass `ruff check`.

**Reference source:** the canonical block to copy lives at `addons/sale/models/sale_order.py`, methods `write` (654) and `_validate_write_vals`…`_get_field_labels` (662–768).

---

## File Structure

- **Modify** `addons/purchase/models/purchase_order.py` — add import, class constants, `write()`, and the WRITE VALIDATION section.
- **Create** `addons/purchase/tests/test_purchase_order_write_validation.py` — the test suite.
- **Modify** `addons/purchase/tests/__init__.py` — register the new test module.

---

## Task 1: Port the mechanism + transition-guard tests

**Files:**
- Modify: `addons/purchase/models/purchase_order.py` (import ~line 11; constants after `_order` line 38; `write()` + WRITE VALIDATION section after `_unlink_except_draft_or_cancel`, before the `# COMPUTE METHODS` banner at line 475)
- Create: `addons/purchase/tests/test_purchase_order_write_validation.py`
- Modify: `addons/purchase/tests/__init__.py`

**Interfaces:**
- Produces: `PurchaseOrder.write(self, vals)`; `_validate_write_vals(self, vals)`; `_get_validate_write_vals_methods(self) -> list[str]`; `_get_state_frozen_fields(self) -> dict`; `_validate_write_locked_order(self, vals)`; `_get_user_editable_fields(self) -> set[str]`; `_validate_write_state_frozen_fields(self, vals)`; `_validate_write_state_transition(self, vals)`; `_get_field_labels(self, field_names) -> str`; class attrs `_STATE_TRANSITIONS`, `_LOCKED_WRITABLE_FIELDS`.
- Consumes (in tests): `purchase.order` API `action_confirm()`, `action_cancel()`, `action_draft()`, `action_lock()`, `action_unlock()`; fixtures `partner_a`, `product_a` from `AccountTestInvoicingCommon`; PO lines field is `line_ids`; line qty field is `product_qty`.

- [ ] **Step 1: Register the test module**

Edit `addons/purchase/tests/__init__.py`, append after the last `from . import` line:

```python
from . import test_purchase_order_write_validation
```

- [ ] **Step 2: Write the failing transition test file**

Create `addons/purchase/tests/test_purchase_order_write_validation.py`:

```python
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseOrderWriteValidation(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.PurchaseOrder = cls.env["purchase.order"]

    def _new_po(self):
        """A fresh draft PO with one confirmable line."""
        return self.PurchaseOrder.create({
            "partner_id": self.partner_a.id,
            "line_ids": [
                Command.create({
                    "product_id": self.product_a.id,
                    "product_qty": 1.0,
                    "price_unit": 100.0,
                }),
            ],
        })

    # --- transition guard ---

    def test_legal_transitions_via_actions(self):
        # draft -> done
        po = self._new_po()
        self.assertEqual(po.state, "draft")
        po.action_confirm()
        self.assertEqual(po.state, "done")
        # done -> cancel
        po.action_cancel()
        self.assertEqual(po.state, "cancel")
        # cancel -> draft
        po.action_draft()
        self.assertEqual(po.state, "draft")
        # draft -> cancel
        po.action_cancel()
        self.assertEqual(po.state, "cancel")

    def test_illegal_transition_done_to_draft_raises(self):
        po = self._new_po()
        po.action_confirm()
        po.action_unlock()  # ensure locked guard is not what raises
        with self.assertRaises(UserError):
            po.write({"state": "draft"})

    def test_illegal_transition_cancel_to_done_raises(self):
        po = self._new_po()
        po.action_cancel()
        with self.assertRaises(UserError):
            po.write({"state": "done"})

    def test_noop_self_write_allowed(self):
        po = self._new_po()
        po.write({"state": "draft"})  # must not raise
        self.assertEqual(po.state, "draft")
```

- [ ] **Step 3: Run the test, verify it fails**

Run (drops/recreates a disposable DB from the template; if `purchase` is not present in the template, swap `-u purchase` for `-i purchase`):

```bash
TMPDB=disp_powtest_$$
createdb -h /var/run/postgresql -T disp_basefull_13702 "$TMPDB"
/home/marin/Odoo/venv/p314o19m/bin/python /home/marin/Odoo/addons/odoo/odoo-bin \
  -d "$TMPDB" \
  --addons-path=/home/marin/Odoo/addons/odoo/odoo/addons,/home/marin/Odoo/addons/odoo/addons \
  --db_host=/var/run/postgresql \
  --data-dir=/tmp/claude-1000/-home-marin-Odoo/e1125c68-8618-4e44-90fc-330a61aa3550/scratchpad/odoo-data \
  -u purchase --test-enable --stop-after-init \
  --test-tags '/purchase:TestPurchaseOrderWriteValidation' \
  --http-port=8971 --gevent-port=8972 --log-level=test 2>&1 | tail -40
dropdb -h /var/run/postgresql "$TMPDB"
```

Expected: FAIL/ERROR — `test_illegal_transition_*` do not raise (no `write()` override yet), so `assertRaises` fails.

- [ ] **Step 4: Add the import**

In `addons/purchase/models/purchase_order.py`, immediately after the line `from odoo.fields import Command, Domain` (line 11), add:

```python
from odoo.orm.primitives import MAGIC_COLUMNS
```

- [ ] **Step 5: Add the class constants**

Immediately after `_order = "priority desc, id desc"` (line 38), add:

```python

    _STATE_TRANSITIONS = {
        "draft": {"done", "cancel"},
        "done": {"cancel"},
        "cancel": {"draft"},
    }
    _LOCKED_WRITABLE_FIELDS = {"locked", "priority"}
```

- [ ] **Step 6: Add `write()` and the WRITE VALIDATION section**

In the CRUD section, immediately after the end of `_unlink_except_draft_or_cancel` (the closing `)` on line 473) and before the `# ------` `# COMPUTE METHODS` banner (line 475), insert:

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
            "_validate_write_locked_order",
            "_validate_write_state_frozen_fields",
            "_validate_write_state_transition",
        ]

    def _get_state_frozen_fields(self):
        """Map of ``{state: {field names frozen in that state}}``.

        Empty for purchase: unlike ``sale.order`` (which freezes ``pricelist_id``
        in ``done``), purchase has no per-state frozen-field rule and no
        ``pricelist_id`` analog. Kept as an extensible hook; confirmed and locked
        orders are already frozen by ``_validate_write_locked_order``.
        """
        return {}

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

- [ ] **Step 7: Run the transition tests, verify they pass**

Run the same command as Step 3. Expected: the 4 `test_*` methods PASS — look for `odoo.tests.result: 0 failed, 0 error(s)`.

- [ ] **Step 8: Lint**

```bash
cd /home/marin/Odoo/addons/odoo && /home/marin/Odoo/venv/p314o19m/bin/python -m ruff check addons/purchase/models/purchase_order.py addons/purchase/tests/test_purchase_order_write_validation.py
```

Expected: `All checks passed!` (or no findings on the changed lines).

- [ ] **Step 9: Commit**

```bash
cd /home/marin/Odoo/addons/odoo
git add addons/purchase/models/purchase_order.py addons/purchase/tests/test_purchase_order_write_validation.py addons/purchase/tests/__init__.py
git commit -m "$(cat <<'EOF'
feat(purchase): add write state-machine validation to purchase.order

Port sale.order's _validate_write_vals registry, _STATE_TRANSITIONS and
_LOCKED_WRITABLE_FIELDS pattern to purchase.order for cross-module parity.
Adds transition-guard tests. Frozen-fields map is empty (no purchase rule).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Locked-guard tests

**Files:**
- Modify: `addons/purchase/tests/test_purchase_order_write_validation.py`

**Interfaces:**
- Consumes: everything produced in Task 1; `action_lock()` writes `{"locked": True, "priority": "0"}`; `action_unlock()` writes `{"locked": False}`; `message_post` for the framework-write check; `res.company.order_lock_po` (default `"edit"`, set to `"lock"` to force auto-lock on confirm).

- [ ] **Step 1: Add the locked-guard tests**

Append these methods to `TestPurchaseOrderWriteValidation` in `addons/purchase/tests/test_purchase_order_write_validation.py`:

```python
    # --- locked-order whitelist guard ---

    def test_locked_blocks_business_field(self):
        po = self._new_po()
        po.action_lock()
        self.assertTrue(po.locked)
        with self.assertRaises(UserError):
            po.write({"date_order": "2026-01-01 00:00:00"})

    def test_locked_allows_whitelisted_fields(self):
        po = self._new_po()
        po.action_lock()
        po.write({"priority": "1"})  # priority is whitelisted
        self.assertEqual(po.priority, "1")
        po.write({"locked": False})  # unlocking is always allowed
        self.assertFalse(po.locked)

    def test_locked_bypass_context(self):
        po = self._new_po()
        po.action_lock()
        po.with_context(bypass_locked_check=True).write(
            {"date_order": "2026-01-01 00:00:00"},
        )  # must not raise

    def test_locked_allows_framework_write(self):
        po = self._new_po()
        po.action_lock()
        # Posting chatter writes computed/non-editable fields only -> not blocked.
        po.message_post(body="hello")  # must not raise

    def test_action_lock_not_self_blocked(self):
        po = self._new_po()
        po.action_lock()  # locking an unlocked order must not raise
        self.assertTrue(po.locked)

    def test_auto_lock_on_confirm_not_self_blocked(self):
        self.env.company.order_lock_po = "lock"
        po = self._new_po()
        po.action_confirm()  # auto-locks via _should_be_locked; must not raise
        self.assertEqual(po.state, "done")
        self.assertTrue(po.locked)
```

- [ ] **Step 2: Run the locked-guard tests, verify they pass**

Use the Step 3 command from Task 1. Expected: `0 failed, 0 error(s)` across all `TestPurchaseOrderWriteValidation` methods.

- [ ] **Step 3: Lint**

```bash
cd /home/marin/Odoo/addons/odoo && /home/marin/Odoo/venv/p314o19m/bin/python -m ruff check addons/purchase/tests/test_purchase_order_write_validation.py
```

Expected: no new findings.

- [ ] **Step 4: Commit**

```bash
cd /home/marin/Odoo/addons/odoo
git add addons/purchase/tests/test_purchase_order_write_validation.py
git commit -m "$(cat <<'EOF'
test(purchase): cover locked-order write guard on purchase.order

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Frozen-map no-op test + full regression verification

**Files:**
- Modify: `addons/purchase/tests/test_purchase_order_write_validation.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2. `order_lock_po` default is `"edit"`, so `action_confirm` leaves the PO unlocked and the frozen-map guard is testable in isolation.

- [ ] **Step 1: Add the frozen-map no-op test**

Append to `TestPurchaseOrderWriteValidation`:

```python
    # --- per-state frozen fields (empty map: no false positives) ---

    def test_frozen_fields_empty_map_allows_done_write(self):
        po = self._new_po()
        po.action_confirm()  # order_lock_po defaults to "edit" -> stays unlocked
        self.assertEqual(po.state, "done")
        self.assertFalse(po.locked)
        # No field is frozen in 'done' for purchase -> a normal write succeeds.
        po.write({"date_order": "2026-01-01 00:00:00"})  # must not raise
        self.assertEqual(str(po.date_order), "2026-01-01 00:00:00")
```

- [ ] **Step 2: Run the full new test class, verify all pass**

Use the Task 1 Step 3 command. Expected: `0 failed, 0 error(s) of 11 tests` for `TestPurchaseOrderWriteValidation`.

- [ ] **Step 3: Run the broader purchase regression suite**

Confirms the new `write()` override does not break existing flows (confirm/cancel/lock/draft):

```bash
TMPDB=disp_powreg_$$
createdb -h /var/run/postgresql -T disp_basefull_13702 "$TMPDB"
/home/marin/Odoo/venv/p314o19m/bin/python /home/marin/Odoo/addons/odoo/odoo-bin \
  -d "$TMPDB" \
  --addons-path=/home/marin/Odoo/addons/odoo/odoo/addons,/home/marin/Odoo/addons/odoo/addons \
  --db_host=/var/run/postgresql \
  --data-dir=/tmp/claude-1000/-home-marin-Odoo/e1125c68-8618-4e44-90fc-330a61aa3550/scratchpad/odoo-data \
  -u purchase --test-enable --stop-after-init \
  --test-tags '/purchase' \
  --http-port=8971 --gevent-port=8972 --log-level=test 2>&1 | tail -60
dropdb -h /var/run/postgresql "$TMPDB"
```

Expected: `0 failed, 0 error(s)`. If a pre-existing test now writes an illegal `state` transition or mutates a locked order directly, investigate whether it's a real behavior conflict (surface it — do NOT weaken the validators without discussion).

- [ ] **Step 4: Final lint**

```bash
cd /home/marin/Odoo/addons/odoo && /home/marin/Odoo/venv/p314o19m/bin/python -m ruff check addons/purchase/models/purchase_order.py addons/purchase/tests/test_purchase_order_write_validation.py
```

Expected: `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
cd /home/marin/Odoo/addons/odoo
git add addons/purchase/tests/test_purchase_order_write_validation.py
git commit -m "$(cat <<'EOF'
test(purchase): assert empty frozen-fields map is a no-op on done orders

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review notes

- **Spec coverage:** §6.1(a) import → T1S4; §6.1(b) constants → T1S5; §6.1(c) `write()` + §6.1(d) all 8 methods → T1S6; §6.2 tests → T1 (transition), T2 (locked), T3 (frozen no-op) + regression. All spec sections mapped.
- **Out-of-scope honored:** no task touches `sale`, `purchase_order_line`, or `sale_order_line`.
- **Type/name consistency:** validator names in `_get_validate_write_vals_methods` exactly match the defined methods; `line_ids` / `product_qty` / `action_*` names verified against existing purchase code and tests.
