from datetime import datetime

from psycopg.errors import NotNullViolation

from odoo.tests import tagged, users
from odoo.tools import mute_logger

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestSaleProductTemplate(SaleCommon):
    @users("salesman")
    def test_sale_get_configurator_display_price(self):
        configurator_price = self.env[
            "product.template"
        ]._get_configurator_display_price(
            product_or_template=self._create_product(list_price=40),
            quantity=3,
            date=datetime(2000, 1, 1),
            currency=self.currency,
            pricelist=self.pricelist,
        )

        self.assertEqual(configurator_price[0], 40)

    @users("salesman")
    def test_sale_get_additional_configurator_data(self):
        configurator_data = self.env[
            "product.template"
        ]._get_additional_configurator_data(
            product_or_template=self.product,
            date=datetime(2000, 1, 1),
            currency=self.currency,
            pricelist=self.pricelist,
        )

        self.assertEqual(configurator_data, {})

    def test_invoice_policy_cannot_be_created_empty(self):
        """A product cannot be stored without an invoicing policy.

        The requirement lived in the form view only, so every other write
        path went around it: `_compute_invoice_policy` fills the field when
        it is left out, but an explicit falsy value in the vals wins over a
        `readonly=False` compute and reaches the column as NULL.
        """
        with mute_logger("odoo.db"), self.assertRaises(NotNullViolation):
            self.env["product.template"].create(
                {
                    "name": "Service with no invoicing policy",
                    "type": "service",
                    "invoice_policy": False,
                }
            )

    def test_invoice_policy_cannot_be_emptied_by_write(self):
        """Nor can it be emptied afterwards.

        `_compute_invoice_policy` only depends on `type`, so clearing the
        policy on its own never triggers the recompute that would fill it
        back in.
        """
        template = self.env["product.template"].create(
            {
                "name": "Service",
                "type": "service",
            }
        )
        self.assertEqual(template.invoice_policy, "ordered")

        with mute_logger("odoo.db"), self.assertRaises(NotNullViolation):
            template.invoice_policy = False
            template.flush_recordset()
