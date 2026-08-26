from odoo.exceptions import UserError
from odoo.fields import Command
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

    def test_writing_an_unchanged_value_on_a_locked_order_is_allowed(self):
        """A guard that refuses a no-op write is refusing the wrong thing.

        Over JSON-RPC and through `load()` a datetime cannot survive as
        anything but a string, so the guard has to compare through the field
        rather than across the ORM/vals type boundary. It used to compare raw,
        which made every re-import and every external write-back of an
        untouched date fail with "this order is locked".
        """
        order = self._make_order()
        order.write({"state": "done", "locked": True})
        unchanged = order.date_order

        order.write({"date_order": unchanged.strftime("%Y-%m-%d %H:%M:%S")})

        self.assertEqual(order.date_order, unchanged)

    def test_writing_an_unchanged_datetime_object_is_allowed(self):
        order = self._make_order()
        order.write({"state": "done", "locked": True})
        unchanged = order.date_order

        order.write({"date_order": unchanged})

        self.assertEqual(order.date_order, unchanged)

    def test_writing_an_unchanged_x2many_on_a_locked_order_is_allowed(self):
        order = self._make_order()
        line = self._make_line(order=order)
        order.write({"state": "done", "locked": True})

        order.write({"line_ids": [Command.set(order.line_ids.ids)]})

        self.assertEqual(order.line_ids, line)

    def test_a_real_change_on_a_locked_order_is_still_refused(self):
        order = self._make_order()
        order.write({"state": "done", "locked": True})

        with self.assertRaises(UserError):
            order.write({"date_order": "2020-01-01 00:00:00"})

    def test_a_real_x2many_change_on_a_locked_order_is_still_refused(self):
        order = self._make_order()
        self._make_line(order=order)
        order.write({"state": "done", "locked": True})

        with self.assertRaises(UserError):
            order.write({"line_ids": [Command.clear()]})

    def test_a_misspelled_write_guard_raises_rather_than_being_skipped(self):
        """The registry is the only record that a guard was meant to run."""
        order = self._make_order()
        model = type(self.env["base.order.test"])
        original = model._get_check_write_guards
        model._get_check_write_guards = lambda self: ["_check_write_guard_typo"]
        try:
            with self.assertRaises(AttributeError):
                order.write({"partner_ref": "X"})
        finally:
            model._get_check_write_guards = original
