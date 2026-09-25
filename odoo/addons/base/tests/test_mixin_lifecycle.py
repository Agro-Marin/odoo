from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestLifecycleLock(TransactionCase):
    def test_a_locked_record_refuses_a_state_write(self):
        Lifecycle = self.env["mixin.lifecycle"]
        record = Lifecycle.new({"locked": True})
        with (
            patch.object(
                type(Lifecycle), "_is_locked_field_changed", return_value=True
            ),
            patch.object(type(Lifecycle), "_get_field_labels", return_value="Status"),
            self.assertRaises(UserError),
        ):
            record._check_write_locked_order({"state": "cancel"})

    def test_the_cancel_action_writes_through_the_lock(self):
        Lifecycle = self.env["mixin.lifecycle"]
        record = Lifecycle.new({"locked": True})
        writes = []

        def write(self, vals):
            writes.append((vals, self.env.context.get("bypass_locked_check")))
            return True

        with patch.object(type(Lifecycle), "write", write):
            record._action_cancel()
        self.assertEqual(writes, [({"state": "cancel"}, True)])
