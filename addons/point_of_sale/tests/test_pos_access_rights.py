import logging
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import new_test_user, tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestPosAccessRights(CommonPosTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cashier = new_test_user(
            cls.env,
            login="pos_plain_cashier",
            groups="base.group_user,point_of_sale.group_pos_user",
            company_id=cls.company.id,
        )
        cls.manager = new_test_user(
            cls.env,
            login="pos_plain_manager",
            groups="base.group_user,point_of_sale.group_pos_manager",
            company_id=cls.company.id,
        )

    def test_cashier_cannot_repoint_the_pos_journal(self):
        sink = self.env["account.journal"].create(
            {
                "name": "Sink",
                "type": "sale",
                "code": "SINKJ",
                "company_id": self.company.id,
            }
        )
        original = self.pos_config_usd.journal_id
        with self.assertRaises(AccessError):
            self.pos_config_usd.with_user(self.cashier).write(
                {"journal_id": sink.id}
            )
        self.pos_config_usd.invalidate_recordset(["journal_id"])
        self.assertEqual(self.pos_config_usd.journal_id, original)

    def test_cashier_cannot_attach_a_pricelist(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Cashier pricelist",
                "currency_id": self.pos_config_usd.currency_id.id,
            }
        )
        with self.assertRaises(AccessError):
            self.pos_config_usd.with_user(self.cashier).write(
                {"available_pricelist_ids": [Command.link(pricelist.id)]}
            )
        self.pos_config_usd.invalidate_recordset(["available_pricelist_ids"])
        self.assertNotIn(pricelist, self.pos_config_usd.available_pricelist_ids)

    def test_manager_can_still_configure(self):
        self.pos_config_usd.with_user(self.manager).write(
            {"iface_big_scrollbars": True}
        )
        self.assertTrue(self.pos_config_usd.iface_big_scrollbars)

    def test_cashier_can_still_mint_the_bus_token(self):
        config = self.pos_config_usd
        config.sudo().access_token = False
        token = config.with_user(self.cashier)._get_access_token()
        self.assertTrue(token)
        self.assertEqual(config.sudo().access_token, token)

    def test_cashier_can_still_notify_synchronisation(self):
        config = self.pos_config_usd
        config.open_ui()
        config.with_user(self.cashier).notify_synchronisation(
            config.current_session_id.id, 0
        )

    def test_cashier_can_still_register_a_device(self):
        config = self.pos_config_usd
        result = config.with_user(self.cashier).register_new_device_identifier()
        self.assertTrue(result["device_identifier"])

    def test_cashier_can_still_open_a_session(self):
        config = self.pos_config_usd.with_user(self.cashier)
        config.open_ui()
        self.assertTrue(config.current_session_id)

    def test_cashier_can_toggle_a_pos_favourite(self):
        template = self.env["product.template"].create(
            {"name": "Favourite probe", "available_in_pos": True}
        )
        template.with_user(self.cashier).set_pos_favorite(True)
        self.assertTrue(template.is_favorite)
        template.with_user(self.cashier).set_pos_favorite(False)
        self.assertFalse(template.is_favorite)

    def test_favourite_toggle_writes_nothing_else(self):
        template = self.env["product.template"].create(
            {"name": "Favourite probe 2", "available_in_pos": True, "list_price": 7}
        )
        template.with_user(self.cashier).set_pos_favorite(True)
        self.assertEqual(template.list_price, 7)

    def test_favourite_toggle_refuses_a_non_pos_product(self):
        template = self.env["product.template"].create(
            {"name": "Not in pos", "available_in_pos": False}
        )
        with self.assertRaises(AccessError):
            template.with_user(self.cashier).set_pos_favorite(True)

    def _paid_order_payload(self, uuid):
        product = self.env["product.product"].search(
            [("available_in_pos", "=", True)], limit=1
        )
        payment_method = self.pos_config_usd.payment_method_ids.filtered(
            lambda pm: not pm.split_transactions
        )[:1]
        return {
            "uuid": uuid,
            "session_id": self.pos_config_usd.current_session_id.id,
            "company_id": self.company.id,
            "partner_id": self.partner_a.id,
            "state": "paid",
            "to_invoice": True,
            "amount_tax": 0,
            "amount_total": 100,
            "amount_paid": 100,
            "amount_return": 0,
            "lines": [
                Command.create(
                    {
                        "product_id": product.id,
                        "qty": 1,
                        "price_unit": 100,
                        "price_subtotal": 100,
                        "price_subtotal_incl": 100,
                        "uuid": f"{uuid}-line",
                    }
                )
            ],
            "payment_ids": [
                Command.create(
                    {
                        "amount": 100,
                        "payment_method_id": payment_method.id,
                        "uuid": f"{uuid}-pay",
                    }
                )
            ],
        }

    def test_cashier_can_invoice_an_order(self):
        self.pos_config_usd.open_ui()
        PosOrder = type(self.env["pos.order"])
        original = PosOrder._reconcile_invoice_payments

        def cold_cache(inner_self, invoice, payment_moves):
            inner_self.env.invalidate_all()
            return original(inner_self, invoice, payment_moves)

        with patch.object(PosOrder, "_reconcile_invoice_payments", cold_cache):
            self.env["pos.order"].with_user(self.cashier).sync_from_ui(
                [self._paid_order_payload("cashier-invoice-0001")]
            )
        order = self.env["pos.order"].search([("uuid", "=", "cashier-invoice-0001")])
        self.assertTrue(order.account_move, "the cashier's order was not invoiced")
        self.assertEqual(order.state, "done")

    def test_cashier_invoice_still_reconciles(self):
        self.pos_config_usd.open_ui()
        self.env["pos.order"].with_user(self.cashier).sync_from_ui(
            [self._paid_order_payload("cashier-invoice-0002")]
        )
        order = self.env["pos.order"].search([("uuid", "=", "cashier-invoice-0002")])
        receivable = (
            self.env["res.partner"]
            ._find_accounting_partner(order.account_move.partner_id)
            .with_company(order.company_id)
            .property_account_receivable_id
        )
        invoice_lines = order.account_move.line_ids.filtered(
            lambda line: line.account_id == receivable
        )
        self.assertTrue(invoice_lines)
        self.assertTrue(all(invoice_lines.mapped("reconciled")))

    def test_favourite_toggle_refuses_a_non_pos_user(self):
        outsider = new_test_user(
            self.env, login="pos_outsider", groups="base.group_user"
        )
        template = self.env["product.template"].create(
            {"name": "Favourite probe 3", "available_in_pos": True}
        )
        with self.assertRaises(AccessError):
            template.with_user(outsider).set_pos_favorite(True)
