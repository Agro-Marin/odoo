from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPartnerSaleGuards(TransactionCase):
    """Partner order roll-up and the edit guards a confirmed order imposes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.salesman = new_test_user(
            cls.env, login='partner_guard_seller',
            groups='base.group_user,sales_team.group_sale_salesman',
        )
        cls.outsider = new_test_user(
            cls.env, login='partner_guard_outsider', groups='base.group_user',
        )
        cls.parent = cls.env['res.partner'].create({
            'name': 'Holding company', 'is_company': True,
        })
        cls.child = cls.env['res.partner'].create({
            'name': 'Branch office', 'parent_id': cls.parent.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Guarded product', 'type': 'consu', 'list_price': 50.0,
        })

    def _order(self, partner, confirm=False):
        # the order must belong to the salesman: the personal sales-team rule
        # hides other people's orders, which would read as zero.
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'user_id': self.salesman.id,
            'line_ids': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': 1,
            })],
        })
        if confirm:
            order.action_confirm()
        return order

    def test_child_orders_roll_up_to_the_parent(self):
        """An order placed by a branch also counts for its holding."""
        self._order(self.child)
        parent = self.parent.with_user(self.salesman)
        child = self.child.with_user(self.salesman)
        (parent + child).invalidate_recordset(['sale_order_count'])
        self.assertEqual(child.sale_order_count, 1)
        self.assertEqual(parent.sale_order_count, 1)

    def test_parent_own_orders_add_to_the_children_ones(self):
        """The holding totals its own orders plus those of its branches."""
        self._order(self.parent)
        self._order(self.child)
        parent = self.parent.with_user(self.salesman)
        parent.invalidate_recordset(['sale_order_count'])
        self.assertEqual(parent.sale_order_count, 2)

    def test_count_is_acl_protected(self):
        """The count field itself is denied to users outside the group."""
        self._order(self.child)
        partner = self.parent.with_user(self.outsider)
        partner.invalidate_recordset(['sale_order_count'])
        with self.assertRaises(AccessError):
            self.assertIsNotNone(partner.sale_order_count)

    def test_country_editable_while_no_order_is_confirmed(self):
        """A draft order does not lock the partner's country."""
        self._order(self.parent)
        self.assertTrue(self.parent._can_edit_country())

    def test_country_locked_by_a_confirmed_order(self):
        """Once an order is confirmed the country can no longer change."""
        self._order(self.parent, confirm=True)
        self.assertFalse(self.parent._can_edit_country())

    def test_country_locked_through_the_invoice_partner(self):
        """The lock also applies when the partner only invoices the order."""
        buyer = self.env['res.partner'].create({'name': 'Ordering party'})
        order = self._order(buyer)
        order.partner_invoice_id = self.parent
        order.action_confirm()
        self.assertFalse(self.parent._can_edit_country())

    def test_vat_locked_by_a_confirmed_order_of_a_branch(self):
        """A branch order locks the VAT of its whole commercial entity."""
        self.assertTrue(self.parent.can_edit_vat())
        self._order(self.child, confirm=True)
        self.assertFalse(self.parent.can_edit_vat())
