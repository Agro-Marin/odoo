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
        return self.PurchaseOrder.create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "product_qty": 1.0,
                            "price_unit": 100.0,
                        }
                    ),
                ],
            }
        )

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

    # --- per-state frozen fields (empty map: no false positives) ---

    def test_frozen_fields_empty_map_allows_done_write(self):
        po = self._new_po()
        po.action_confirm()  # order_lock_po defaults to "edit" -> stays unlocked
        self.assertEqual(po.state, "done")
        self.assertFalse(po.locked)
        # No field is frozen in 'done' for purchase -> a normal write succeeds.
        po.write({"date_order": "2026-01-01 00:00:00"})  # must not raise
        self.assertEqual(str(po.date_order), "2026-01-01 00:00:00")
