from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestCrmTeamSales(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.team = cls.env["crm.team"].create({"name": "Grind team"})
        cls.customer = cls.env["res.partner"].create({"name": "Team customer"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Team product",
                "type": "consu",
                "list_price": 100.0,
            }
        )

    def _orders(self, count, state=None):
        orders = self.env["sale.order"].create(
            [
                {
                    "partner_id": self.customer.id,
                    "team_id": self.team.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": self.product.id,
                                "product_qty": 1,
                            }
                        )
                    ],
                }
                for _dummy in range(count)
            ]
        )
        if state == "cancel":
            orders.action_cancel()
        return orders

    def test_order_count_ignores_cancelled(self):
        self._orders(2)
        self._orders(1, state="cancel")
        self.team.invalidate_recordset(["sale_order_count"])
        self.assertEqual(self.team.sale_order_count, 2)

    def test_team_without_orders_counts_zero(self):
        fresh = self.env["crm.team"].create({"name": "Empty team"})
        self.assertEqual(fresh.sale_order_count, 0)

    def test_deleting_a_lightly_used_team_is_allowed(self):
        self._orders(4)
        self.team.invalidate_recordset(["sale_order_count"])
        self.team.unlink()
        self.assertFalse(self.team.exists())

    def test_deleting_an_actively_used_team_is_refused(self):
        self._orders(5)
        self.team.invalidate_recordset(["sale_order_count"])
        with self.assertRaises(UserError):
            self.team.unlink()

    def test_cancelled_orders_do_not_protect_the_team(self):
        self._orders(6, state="cancel")
        self.team.invalidate_recordset(["sale_order_count"])
        self.assertEqual(self.team.sale_order_count, 0)
        self.team.unlink()
        self.assertFalse(self.team.exists())

    def test_invoiced_is_zero_without_paid_invoices(self):
        self._orders(2)
        self.team.invalidate_recordset(["invoiced"])
        self.assertEqual(self.team.invoiced, 0.0)

    def test_invoiced_target_is_rounded(self):
        self.team.update_invoiced_target("1234.6")
        self.assertEqual(self.team.invoiced_target, 1235)
        self.team.update_invoiced_target("")
        self.assertEqual(self.team.invoiced_target, 0)

    def test_dashboard_button_follows_the_sales_context(self):
        in_sales = self.team.with_context(in_sales_app=True)
        in_sales._compute_dashboard_button_name()
        self.assertEqual(in_sales.dashboard_button_name, "Sales Analysis")

        action = in_sales.action_primary_channel_button()
        self.assertEqual(action["type"], "ir.actions.act_window")


@tagged("post_install", "-at_install")
class TestCrmTeamInvoicedWindow(TestSaleCommon):
    """`invoiced` reports a calendar month, and the calendar is the user's."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.team = cls.env["crm.team"].create({"name": "Bajio team"})

    def _paid_invoice(self, invoice_date, amount=1000.0):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "team_id": self.team.id,
                "invoice_date": invoice_date,
                "date": invoice_date,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "price_unit": amount,
                        }
                    )
                ],
            }
        )
        invoice.action_post()
        self.env["account.payment.register"].with_context(
            active_model="account.move",
            active_ids=invoice.ids,
        ).create({})._create_payments()
        invoice.flush_model()
        return invoice

    @freeze_time("2026-01-15 12:00:00")
    def test_invoiced_counts_this_months_paid_invoices(self):
        self._paid_invoice("2026-01-10")
        self.assertEqual(self.team.invoiced, 1000.0)

    @freeze_time("2026-02-01 02:00:00")
    def test_invoiced_window_follows_the_user_timezone(self):
        # 02:00 UTC on the 1st is still 20:00 on the 31st for a UTC-6 user, so
        # the month they are looking at is January. Bounding the window with
        # UTC today instead starts it on February 1st and reports the month as
        # empty on its last afternoon.
        self._paid_invoice("2026-01-10")
        team = self.team.with_context(tz="America/Mexico_City")
        self.assertEqual(team.invoiced, 1000.0)
