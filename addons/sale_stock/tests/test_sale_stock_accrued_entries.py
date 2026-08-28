from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import Form, tagged

from odoo.addons.sale.tests.common import TestSaleCommon


@tagged("post_install", "-at_install")
class TestAccruedStockSaleOrders(TestSaleCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        product = cls.env["product.product"].create(
            {
                "name": "Product",
                "list_price": 30.0,
                "type": "consu",
                "uom_id": cls.uom_unit.id,
                "invoice_policy": "transferred",
            }
        )
        cls.sale_order = (
            cls.env["sale.order"]
            .with_context(tracking_disable=True)
            .create(
                {
                    "partner_id": cls.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": product.id,
                                "product_qty": 10.0,
                                "tax_ids": False,
                            }
                        )
                    ],
                }
            )
        )
        cls.sale_order.action_confirm()
        cls.account_expense = cls.company_data["default_account_expense"]
        cls.account_revenue = cls.company_data["default_account_revenue"]

    def test_sale_stock_accruals(self):
        pick = self.sale_order.picking_ids
        pick.move_ids.write({"quantity": 2, "picked": True})
        pick.button_validate()
        wiz_act = pick.button_validate()
        Form.from_action(self.env, wiz_act).save().process()
        pick.move_ids.write({"date": fields.Date.to_date("2020-01-02")})

        pick = pick.copy()
        pick.move_ids.write({"quantity": 3, "picked": True})
        pick.button_validate()
        pick.move_ids.write({"date": fields.Date.to_date("2020-01-06")})

        wizard = (
            self.env["account.accrued.orders.wizard"]
            .with_context(
                {
                    "active_model": "sale.order",
                    "active_ids": self.sale_order.ids,
                }
            )
            .create(
                {
                    "account_id": self.account_expense.id,
                    "date": "2020-01-01",
                }
            )
        )
        with self.assertRaises(UserError):
            wizard.create_entries()

        wizard.date = fields.Date.to_date("2020-01-04")
        self.assertRecordValues(
            self.env["account.move"].search(wizard.create_entries()["domain"]).line_ids,
            [
                {"account_id": self.account_revenue.id, "debit": 60, "credit": 0},
                {"account_id": wizard.account_id.id, "debit": 0, "credit": 60},
                {"account_id": self.account_revenue.id, "debit": 0, "credit": 60},
                {"account_id": wizard.account_id.id, "debit": 60, "credit": 0},
            ],
        )

        wizard.date = fields.Date.to_date("2020-01-07")
        self.assertRecordValues(
            self.env["account.move"].search(wizard.create_entries()["domain"]).line_ids,
            [
                {"account_id": self.account_revenue.id, "debit": 150, "credit": 0},
                {"account_id": wizard.account_id.id, "debit": 0, "credit": 150},
                {"account_id": self.account_revenue.id, "debit": 0, "credit": 150},
                {"account_id": wizard.account_id.id, "debit": 150, "credit": 0},
            ],
        )

    def test_sale_stock_invoiced_accrued_entries(self):
        pick = self.sale_order.picking_ids
        pick.move_ids.write({"quantity": 2, "picked": True})
        pick.button_validate()
        Form.from_action(self.env, pick.button_validate()).save().process()
        pick.move_ids.write({"date": fields.Date.to_date("2020-01-02")})

        inv = self.sale_order._create_invoices()
        inv.invoice_date = fields.Date.to_date("2020-01-04")
        inv.action_post()

        pick = pick.copy()
        pick.move_ids.write({"quantity": 3, "picked": True})
        pick.button_validate()
        pick.move_ids.write({"date": fields.Date.to_date("2020-01-06")})

        inv = self.sale_order._create_invoices()
        inv.invoice_date = fields.Date.to_date("2020-01-08")
        inv.action_post()

        wizard = (
            self.env["account.accrued.orders.wizard"]
            .with_context(
                {
                    "active_model": "sale.order",
                    "active_ids": self.sale_order.ids,
                }
            )
            .create(
                {
                    "account_id": self.company_data["default_account_expense"].id,
                    "date": "2020-01-02",
                }
            )
        )
        self.assertRecordValues(
            self.env["account.move"].search(wizard.create_entries()["domain"]).line_ids,
            [
                {"account_id": self.account_revenue.id, "debit": 60, "credit": 0},
                {"account_id": wizard.account_id.id, "debit": 0, "credit": 60},
                {"account_id": self.account_revenue.id, "debit": 0, "credit": 60},
                {"account_id": wizard.account_id.id, "debit": 60, "credit": 0},
            ],
        )

        wizard.date = fields.Date.to_date("2020-01-05")
        with self.assertRaises(UserError):
            wizard.create_entries()

        wizard.date = fields.Date.to_date("2020-01-07")
        self.assertRecordValues(
            self.env["account.move"].search(wizard.create_entries()["domain"]).line_ids,
            [
                {"account_id": self.account_revenue.id, "debit": 90, "credit": 0},
                {"account_id": wizard.account_id.id, "debit": 0, "credit": 90},
                {"account_id": self.account_revenue.id, "debit": 0, "credit": 90},
                {"account_id": wizard.account_id.id, "debit": 90, "credit": 0},
            ],
        )

        wizard.date = fields.Date.to_date("2020-01-09")
        with self.assertRaises(UserError):
            wizard.create_entries()
