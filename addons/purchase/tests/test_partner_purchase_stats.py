from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPartnerPurchaseStats(TransactionCase):
    """Vendor order roll-up and the purchases badge on the contact view."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.buyer = new_test_user(
            cls.env, login='partner_purchase_buyer',
            groups='base.group_user,purchase.group_purchase_user',
        )
        cls.outsider = new_test_user(
            cls.env, login='partner_purchase_outsider', groups='base.group_user',
        )
        cls.parent = cls.env['res.partner'].create({
            'name': 'Vendor group', 'is_company': True,
        })
        cls.child = cls.env['res.partner'].create({
            'name': 'Vendor branch', 'parent_id': cls.parent.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Sourced part', 'type': 'consu', 'purchase_ok': True,
        })

    def _order(self, partner):
        # orders belong to the buyer: the personal purchase rule hides
        # other people's orders, which would read as zero.
        return self.env['purchase.order'].create({
            'partner_id': partner.id,
            'user_id': self.buyer.id,
            'line_ids': [Command.create({
                'product_id': self.product.id,
                'product_qty': 1,
            })],
        })

    def test_branch_orders_roll_up_to_the_group(self):
        """An order placed on a branch also counts for its parent vendor."""
        self._order(self.child)
        parent = self.parent.with_user(self.buyer)
        child = self.child.with_user(self.buyer)
        (parent + child).invalidate_recordset(['purchase_order_count'])
        self.assertEqual(child.purchase_order_count, 1)
        self.assertEqual(parent.purchase_order_count, 1)

    def test_group_totals_its_own_and_branch_orders(self):
        """The parent adds its own orders to those of its branches."""
        self._order(self.parent)
        self._order(self.child)
        parent = self.parent.with_user(self.buyer)
        parent.invalidate_recordset(['purchase_order_count'])
        self.assertEqual(parent.purchase_order_count, 2)

    def test_unrelated_partner_is_not_counted(self):
        """Orders of another vendor never reach this one (boundary)."""
        stranger = self.env['res.partner'].create({'name': 'Other vendor'})
        self._order(stranger)
        parent = self.parent.with_user(self.buyer)
        parent.invalidate_recordset(['purchase_order_count'])
        self.assertEqual(parent.purchase_order_count, 0)

    def test_count_is_acl_protected(self):
        """The count is denied to users outside the purchase group."""
        self._order(self.child)
        partner = self.parent.with_user(self.outsider)
        partner.invalidate_recordset(['purchase_order_count'])
        with self.assertRaises(AccessError):
            self.assertIsNotNone(partner.purchase_order_count)

    def test_statistics_badge_reports_the_purchases(self):
        """The contact statistics carry a purchases badge with the count."""
        self._order(self.child)
        parent = self.parent.with_user(self.buyer)
        parent.invalidate_recordset(['purchase_order_count'])
        stats = parent._compute_application_statistics_hook()
        labels = {
            entry['label']: entry['value'] for entry in stats[parent.id]
        }
        self.assertEqual(labels.get('Purchases'), 1)

    def test_statistics_badge_absent_without_orders(self):
        """A vendor with no orders gets no purchases badge (boundary)."""
        parent = self.parent.with_user(self.buyer)
        parent.invalidate_recordset(['purchase_order_count'])
        stats = parent._compute_application_statistics_hook()
        labels = [entry['label'] for entry in stats[parent.id]]
        self.assertNotIn('Purchases', labels)
