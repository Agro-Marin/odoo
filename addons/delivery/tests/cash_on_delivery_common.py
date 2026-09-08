from odoo.fields import Command

from odoo.addons.delivery.tests.common import DeliveryCommon
from odoo.addons.payment_custom.tests.common import PaymentCustomCommon


class CashOnDeliveryCommon(PaymentCustomCommon, DeliveryCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Confirming an order without lines is refused, and the transaction's
        # post-processing confirms this one.
        cls.cod_product = cls.env["product.product"].create(
            {
                "name": "Cash on delivery product",
                "type": "consu",
                "list_price": 20.0,
            }
        )
        cls.sale_order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "state": "draft",
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.cod_product.id,
                            "product_qty": 1.0,
                        }
                    )
                ],
            }
        )
        cls.cod_provider = cls._prepare_provider(
            code="custom", custom_mode="cash_on_delivery"
        )
