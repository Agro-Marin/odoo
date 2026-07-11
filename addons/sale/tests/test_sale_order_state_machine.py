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
