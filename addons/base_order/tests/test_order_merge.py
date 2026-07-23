# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

# Part 3 of base_order's by-parts coverage: the merge mixin's validation,
# grouping, eligibility, and target-selection helpers (order.merge.mixin),
# exercised through sale.order. The full action_merge line-merge flow is
# intentionally left for a dedicated review (guard R1).


@tagged("post_install", "-at_install")
class TestOrderMergeMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.SaleOrder = cls.env["sale.order"]
        cls.partner_a = cls.env["res.partner"].create({"name": "Partner A"})
        cls.partner_b = cls.env["res.partner"].create({"name": "Partner B"})

    def _order(self, partner, date_order=None):
        vals = {"partner_id": partner.id}
        if date_order:
            vals["date_order"] = date_order
        return self.SaleOrder.create(vals)

    def test_validate_selection_requires_at_least_two(self):
        """Merging needs at least two selected orders."""
        one = self._order(self.partner_a)
        with self.assertRaises(UserError):
            self.SaleOrder._merge_validate_selection(one)
        # two orders pass validation (no exception)
        self.SaleOrder._merge_validate_selection(one + self._order(self.partner_a))

    def test_validate_groups_requires_a_group(self):
        """An empty group set is rejected."""
        with self.assertRaises(UserError):
            self.SaleOrder._merge_validate_groups([])
        # a non-empty group set passes
        self.SaleOrder._merge_validate_groups([self._order(self.partner_a)])

    def test_group_orders_groups_by_partner(self):
        """Orders with the same partner group together; distinct partners do not."""
        same = self._order(self.partner_a) + self._order(self.partner_a)
        groups = self.SaleOrder._merge_group_orders(same)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

        distinct = self._order(self.partner_a) + self._order(self.partner_b)
        self.assertEqual(self.SaleOrder._merge_group_orders(distinct), [])

    def test_eligible_orders_are_draft(self):
        """Draft orders are eligible for merging."""
        orders = self._order(self.partner_a) + self._order(self.partner_a)
        self.assertEqual(orders._merge_get_eligible_orders(), orders)

    def test_merge_target_is_the_oldest_order(self):
        """The merge target is the oldest order by order date."""
        old = self._order(self.partner_a, date_order="2020-01-01 00:00:00")
        new = self._order(self.partner_a, date_order="2024-01-01 00:00:00")
        self.assertEqual(self.SaleOrder._merge_get_target(old + new), old)
