from unittest.mock import patch

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPosDeferredInvoicePdf(TestPoSCommon):
    """Rendering the invoice PDF is what made validating an invoiced order slow,
    so it happens after the cashier is free again."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.product100 = self.create_product("Product_100", self.categ_basic, 100, 50)

    def _order_params(self, uuid):
        return {
            "pos_order_lines_ui_args": [(self.product100, 1)],
            "payments": [(self.cash_pm1, 100)],
            "customer": self.customer,
            "is_invoiced": True,
            "uuid": uuid,
        }

    def _patch_pdf_rendering(self):
        return patch.object(
            type(self.env["account.move"]),
            "_generate_and_send",
            autospec=True,
            return_value=None,
        )

    def test_validation_leaves_the_pdf_to_the_cron(self):
        self.open_new_session()
        with self._patch_pdf_rendering() as generate:
            orders = self._create_orders([self._order_params("00100-010-0001")])
        order = orders["00100-010-0001"]

        self.assertFalse(
            generate.called,
            "validating an order must not render the invoice PDF inline",
        )
        self.assertTrue(order.account_move, "the invoice itself is still created")
        self.assertTrue(order.defer_invoice_pdf)

        with self._patch_pdf_rendering() as generate:
            self.env["pos.order"]._cron_process_pos_orders()
        self.assertEqual(generate.call_count, 1)
        self.assertFalse(order.defer_invoice_pdf)

    def test_the_download_setting_keeps_it_inline(self):
        self.config.use_download_invoice = True
        self.open_new_session()
        with self._patch_pdf_rendering() as generate:
            orders = self._create_orders([self._order_params("00100-010-0002")])
        order = orders["00100-010-0002"]

        self.assertEqual(generate.call_count, 1)
        self.assertFalse(order.defer_invoice_pdf)
