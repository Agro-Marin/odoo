from odoo.tests import Form, HttpCase, new_test_user, tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestControllersAccessRights(HttpCase, TestSaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = mail_new_test_user(
            cls.env, login="jimmy-portal", groups="base.group_portal"
        )

    def test_SO_and_DO_portal_acess(self):
        so_form = Form(self.env["sale.order"])
        so_form.partner_id = self.portal_user.partner_id
        with so_form.line_ids.new() as line:
            line.product_id = self.product_a
        so = so_form.save()
        so.action_confirm()
        picking = so.picking_ids

        for login in (None, self.portal_user.login):
            so_url = "/my/orders/%s" % so.id
            picking_url = "/my/picking/pdf/%s" % picking.id

            self.authenticate(login, login)

            if not login:
                so._portal_ensure_token()
                so_token = so.access_token
                so_url = "%s?access_token=%s" % (so_url, so_token)
                picking_url = "%s?access_token=%s" % (picking_url, so_token)

            response = self.url_open(
                url=so_url,
                allow_redirects=False,
            )
            self.assertEqual(
                response.status_code,
                200,
                "Should be correct %s"
                % ("with a connected user" if login else "using access token"),
            )
            response = self.url_open(
                url=picking_url,
                allow_redirects=False,
            )
            self.assertEqual(
                response.status_code,
                200,
                "Should be correct %s"
                % ("with a connected user" if login else "using access token"),
            )


@tagged("post_install", "-at_install")
class TestSalesmanDeliveryAccess(TestSaleCommon):
    """A salesperson who is not an inventory user still owns their order's delivery.

    `access_stock_picking_salesman` already grants this user read/write/create on
    `stock.picking`, so the data is theirs; only the way in was missing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.salesman = new_test_user(
            cls.env,
            login="salesman-without-stock",
            groups="sales_team.group_sale_salesman",
        )
        cls.sale_order_form = cls.env.ref("sale.view_sale_order_form")

    def _form_arch_for(self, user):
        return (
            self.env["sale.order"]
            .with_user(user)
            .get_view(self.sale_order_form.id, "form")["arch"]
        )

    def test_00_the_salesman_is_not_an_inventory_user(self):
        """Guard: without this the rest of the class proves nothing."""
        self.assertFalse(
            self.salesman.has_group("stock.group_stock_user"),
            "The whole point is a salesperson OUTSIDE stock.group_stock_user",
        )

    def test_01_salesman_reaches_the_delivery_of_their_order(self):
        self.assertIn(
            "action_view_delivery",
            self._form_arch_for(self.salesman),
            "A salesperson must reach the delivery of the order they own",
        )

    def test_02_match_deliveries_stays_an_inventory_button(self):
        """Negative control, and the scope boundary.

        `action_delivery_matching` is ours, not upstream's, and it drives writes
        on the transfer. It stays behind `stock.group_stock_user`, which also
        proves this arch really is filtered by groups rather than always
        carrying every button.
        """
        self.assertNotIn(
            "action_delivery_matching",
            self._form_arch_for(self.salesman),
            "Matching deliveries is still an inventory action",
        )

    def test_03_salesman_may_read_the_lots_on_that_delivery(self):
        """The picking's move lines carry lot_id; reading it needs stock.lot."""
        self.env["stock.lot"].with_user(self.salesman).check_access("read")

    def test_04_salesman_may_not_write_lots(self):
        """Negative control: the widened access is read-only."""
        self.assertFalse(
            self.env["stock.lot"].with_user(self.salesman).has_access("write"),
        )
