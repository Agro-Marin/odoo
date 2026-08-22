from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BaseOrderTestCase

# mixin.order.line.fields guards line writes through _check_write_guards, which
# walks the same kind of registry mixin.order uses for confirmation. The two
# validators behind it — the display_type freeze and the locked-order protected
# fields — had no tests, and neither did _get_line_identifier, which builds the
# text those refusals show the user.


@tagged("post_install", "-at_install")
class TestLineWriteGuards(BaseOrderTestCase):
    # --- _check_write_display_type ---

    def test_display_type_cannot_change_on_an_existing_line(self):
        line = self._make_line(product_qty=1.0)

        with self.assertRaises(UserError) as err:
            line.write({"display_type": "line_section"})
        self.assertIn("cannot change the type", str(err.exception))

    def test_display_type_error_names_the_line(self):
        line = self._make_line(product_qty=1.0)

        with self.assertRaises(UserError) as err:
            line._check_write_display_type({"display_type": "line_section"})
        self.assertIn(self.product.display_name, str(err.exception))

    def test_display_type_error_lists_at_most_five_then_counts_the_rest(self):
        order = self._make_order()
        lines = self.env["base.order.test.line"]
        for index in range(7):
            lines |= self._make_line(
                order=order, name=f"Line {index}", product_id=False
            )

        with self.assertRaises(UserError) as err:
            lines._check_write_display_type({"display_type": "line_section"})

        message = str(err.exception)
        self.assertIn("7", message, "the total should be reported")
        self.assertIn("and 2 more", message, "only five are listed by name")

    def test_write_without_display_type_is_not_guarded(self):
        line = self._make_line(product_qty=1.0)

        line._check_write_display_type({"product_qty": 5.0})  # must not raise

    def test_allowed_transition_is_let_through(self):
        """The hook exists so sale can promote a subsection to a section."""
        line = self._make_line(product_qty=1.0)

        with patch.object(
            type(line),
            "_is_display_type_change_allowed",
            lambda self, line, new_type: True,
        ):
            line._check_write_display_type({"display_type": "line_section"})

    def test_setting_the_same_display_type_is_a_no_op(self):
        line = self._make_line(product_id=False, display_type="line_note", name="Note")

        line._check_write_display_type({"display_type": "line_note"})

    # --- _check_write_locked_order ---

    def test_protected_field_refused_on_a_locked_order(self):
        order = self._make_order()
        line = self._make_line(order=order, product_qty=1.0)
        order.write({"state": "done"})
        order.write({"locked": True})

        with self.assertRaises(UserError) as err:
            line._check_write_locked_order({"price_unit": 42.0})
        self.assertIn("locked order", str(err.exception))

    def test_unprotected_field_allowed_on_a_locked_order(self):
        order = self._make_order()
        line = self._make_line(order=order, product_qty=1.0)
        order.write({"state": "done"})
        order.write({"locked": True})

        line._check_write_locked_order({"sequence": 99})  # must not raise

    def test_protected_field_allowed_while_unlocked(self):
        line = self._make_line(product_qty=1.0)
        self.assertFalse(line.locked)

        line._check_write_locked_order({"price_unit": 42.0})  # must not raise

    def test_downpayment_name_may_change_while_locked(self):
        """The one exemption: a down payment's description stays editable."""
        order = self._make_order()
        line = self._make_line(order=order, product_qty=1.0, is_downpayment=True)
        order.write({"state": "done"})
        order.write({"locked": True})

        line._check_write_locked_order({"name": "Down payment (draft)"})

    def test_downpayment_exemption_covers_only_the_name(self):
        order = self._make_order()
        line = self._make_line(order=order, product_qty=1.0, is_downpayment=True)
        order.write({"state": "done"})
        order.write({"locked": True})

        with self.assertRaises(UserError):
            line._check_write_locked_order(
                {"name": "Down payment", "price_unit": 42.0},
            )

    # --- _get_line_identifier ---

    def test_identifier_prefers_the_product(self):
        line = self._make_line(product_qty=1.0)

        self.assertEqual(
            line._get_line_identifier(line),
            self.product.display_name,
        )

    def test_identifier_falls_back_to_the_first_line_of_the_description(self):
        line = self._make_line(product_id=False, name="First line\nsecond line")

        self.assertEqual(line._get_line_identifier(line), "First line")

    def test_identifier_truncates_a_long_description(self):
        line = self._make_line(product_id=False, name="x" * 80)

        identifier = line._get_line_identifier(line)

        self.assertTrue(identifier.endswith("..."))
        self.assertEqual(len(identifier), 53, "50 characters plus the ellipsis")

    def test_identifier_falls_back_to_a_number_without_product_or_name(self):
        # name is NOT NULL on the table, so the empty string is how a line with
        # no description actually reaches this branch.
        line = self._make_line(product_id=False, name="", sequence=7)

        self.assertIn("7", line._get_line_identifier(line))
