from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestDuplicateOrders(BaseOrderTestCase):
    """`mixin.order._get_duplicate_orders` matches on two keys, not one.

    The query has always matched `origin = name` OR `<ref> = <ref>`, but the
    filter in front of it admitted only orders carrying a reference, so the
    origin half could never fire. An order created from another one -- which
    is exactly what `origin` records -- was invisible to the check unless
    somebody had independently typed a partner reference.
    """

    def test_an_order_naming_another_in_its_origin_is_a_duplicate(self):
        first = self._make_order()
        second = self._make_order(origin=first.name)

        self.assertEqual(second.duplicated_order_ids, first)

    def test_two_orders_sharing_a_reference_are_duplicates(self):
        first = self._make_order(partner_ref="SHARED")
        second = self._make_order(partner_ref="SHARED")

        self.assertEqual(second.duplicated_order_ids, first)
        self.assertEqual(first.duplicated_order_ids, second)

    def test_an_order_matching_on_neither_key_is_not_a_duplicate(self):
        self._make_order(partner_ref="A")
        lonely = self._make_order()

        self.assertFalse(lonely.duplicated_order_ids)

    def test_a_different_partner_is_not_a_duplicate(self):
        other_partner = self.env["res.partner"].create({"name": "Other"})
        first = self._make_order(partner_ref="SHARED")
        second = self._make_order(
            partner_ref="SHARED",
            partner_id=other_partner.id,
        )

        self.assertFalse(second.duplicated_order_ids)
        self.assertFalse(first.duplicated_order_ids)

    def test_a_cancelled_order_is_neither_matched_nor_matching(self):
        first = self._make_order(partner_ref="SHARED")
        second = self._make_order(partner_ref="SHARED")
        first.action_cancel()
        second.invalidate_recordset()

        self.assertFalse(second.duplicated_order_ids)

    def test_a_rename_made_in_this_transaction_is_seen(self):
        """The query reads `duplicate_order.name`, so it must be flushed."""
        first = self._make_order()
        second = self._make_order(origin="RENAMED-LATER")
        first.name = "RENAMED-LATER"

        self.assertEqual(second.duplicated_order_ids, first)

    def test_only_draft_orders_report_duplicates(self):
        first = self._make_order(partner_ref="SHARED")
        second = self._make_order(partner_ref="SHARED")
        self._make_line(order=second)
        second.action_confirm()
        second.invalidate_recordset()

        self.assertFalse(second.duplicated_order_ids)
        self.assertEqual(first.duplicated_order_ids, second)
