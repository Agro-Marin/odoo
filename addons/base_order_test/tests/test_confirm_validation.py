from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BaseOrderTestCase

# order.mixin guards confirmation through a registry: _can_confirm walks the
# names _get_can_confirm_validation_methods returns. Nothing exercised any of
# it — the validators are all-or-nothing error paths, so a broken one is silent
# until an order that should have been refused goes through.


@tagged("post_install", "-at_install")
class TestConfirmValidation(BaseOrderTestCase):
    def _confirmable_order(self):
        order = self._make_order()
        self._make_line(order=order, product_qty=1.0)
        return order

    # --- the registry itself ---

    def test_registry_lists_the_validators(self):
        order = self._make_order()

        methods = order._get_can_confirm_validation_methods()

        self.assertEqual(
            methods,
            [
                "_can_confirm_proper_state",
                "_can_confirm_has_lines",
                "_can_confirm_lines_have_product",
                "_can_confirm_analytic_distribution",
            ],
        )

    def test_registry_entries_all_exist(self):
        """A name in the registry with no method behind it fails only at
        confirmation time, on a getattr."""
        order = self._make_order()

        for name in order._get_can_confirm_validation_methods():
            self.assertTrue(
                hasattr(order, name),
                f"{name} is registered but not implemented",
            )

    def test_confirm_passes_on_a_valid_order(self):
        order = self._confirmable_order()

        order._can_confirm()  # must not raise

    # --- _can_confirm_proper_state ---

    def test_confirmed_order_cannot_be_confirmed_again(self):
        order = self._confirmable_order()
        order.state = "done"

        with self.assertRaises(UserError) as err:
            order._can_confirm_proper_state()
        self.assertIn("Already confirmed", str(err.exception))

    def test_cancelled_order_cannot_be_confirmed(self):
        order = self._confirmable_order()
        order.state = "cancel"

        with self.assertRaises(UserError) as err:
            order._can_confirm_proper_state()
        self.assertIn("Cancelled", str(err.exception))

    def test_state_error_separates_confirmed_from_cancelled(self):
        """A mixed batch reports both groups, each under its own heading."""
        confirmed = self._confirmable_order()
        confirmed.state = "done"
        cancelled = self._confirmable_order()
        cancelled.state = "cancel"

        with self.assertRaises(UserError) as err:
            (confirmed + cancelled)._can_confirm_proper_state()

        message = str(err.exception)
        self.assertIn("Already confirmed", message)
        self.assertIn("Cancelled", message)
        self.assertIn(confirmed.display_name, message)
        self.assertIn(cancelled.display_name, message)

    def test_draft_order_passes_the_state_check(self):
        order = self._confirmable_order()

        order._can_confirm_proper_state()  # must not raise

    # --- _can_confirm_has_lines ---

    def test_order_without_lines_cannot_be_confirmed(self):
        order = self._make_order()

        with self.assertRaises(UserError) as err:
            order._can_confirm_has_lines()
        self.assertIn(order.display_name, str(err.exception))

    # --- _can_confirm_lines_have_product ---

    def test_line_without_product_blocks_confirmation(self):
        order = self._make_order()
        self._make_line(order=order, product_id=False, product_qty=1.0)

        with self.assertRaises(UserError) as err:
            order._can_confirm_lines_have_product()

        message = str(err.exception)
        self.assertIn(order.display_name, message)
        self.assertIn("1 line(s) without products", message)

    def test_display_lines_need_no_product(self):
        """Sections and notes carry no product by definition."""
        order = self._confirmable_order()
        self._make_line(
            order=order,
            product_id=False,
            display_type="line_section",
            name="A section",
        )

        order._can_confirm_lines_have_product()  # must not raise

    def test_downpayment_lines_need_no_product(self):
        order = self._confirmable_order()
        self._make_line(order=order, product_id=False, is_downpayment=True)

        order._can_confirm_lines_have_product()  # must not raise

    def test_product_error_counts_each_offending_line(self):
        order = self._make_order()
        for _i in range(3):
            self._make_line(order=order, product_id=False, product_qty=1.0)

        with self.assertRaises(UserError) as err:
            order._can_confirm_lines_have_product()
        self.assertIn("3 line(s) without products", str(err.exception))
