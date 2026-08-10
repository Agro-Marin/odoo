from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestWriteValidation(BaseOrderTestCase):
    def test_locked_business_field_write_blocked_when_locked(self):
        order = self._make_order()
        order.write({"state": "done"})
        order.write({"locked": True})

        with self.assertRaises(UserError):
            order.write({"partner_ref": "REF-123"})

    def test_locked_writable_field_allowed_when_locked(self):
        order = self._make_order()
        order.write({"state": "done", "locked": True})

        order.write({"priority": "1"})

        self.assertEqual(order.priority, "1")

    def test_illegal_state_transition_blocked(self):
        order = self._make_order()
        order.write({"state": "done"})  # draft -> done is legal

        with self.assertRaises(UserError):
            order.write({"state": "draft"})  # done -> draft is illegal

    def test_legal_state_transition_allowed(self):
        order = self._make_order()

        order.write({"state": "done"})

        self.assertEqual(order.state, "done")
