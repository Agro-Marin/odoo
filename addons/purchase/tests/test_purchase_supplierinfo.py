from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseSupplierinfoFromOrder(AccountTestInvoicingCommon):
    """What confirming an RFQ teaches the product about its vendor.

    Two things it used to get wrong: every line after the first of a given
    template was dropped, so variants priced differently collapsed onto the
    first line's price; and the lead time was written as a literal 0.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.attribute = cls.env["product.attribute"].create(
            {
                "name": "Section Size",
                "value_ids": [
                    Command.create({"name": "Small"}),
                    Command.create({"name": "Large"}),
                ],
            },
        )
        cls.template = cls.env["product.template"].create(
            {
                "name": "Two-Variant Product",
                "purchase_ok": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": cls.attribute.id,
                            "value_ids": [Command.set(cls.attribute.value_ids.ids)],
                        },
                    ),
                ],
            },
        )
        cls.variant_small, cls.variant_large = cls.template.product_variant_ids
        cls.vendor = cls.env["res.partner"].create({"name": "Variant Vendor"})

    def _confirm(self, order):
        order.action_confirm()
        self.template.invalidate_recordset()
        return self.template.seller_ids

    def test_variants_priced_apart_get_one_pricelist_each(self):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.variant_small.id,
                            "product_qty": 1,
                            "price_unit": 10.0,
                        },
                    ),
                    Command.create(
                        {
                            "product_id": self.variant_large.id,
                            "product_qty": 1,
                            "price_unit": 20.0,
                        },
                    ),
                ],
            },
        )
        sellers = self._confirm(order)

        self.assertEqual(
            len(sellers),
            2,
            "two variants bought at two prices need two vendor pricelists",
        )
        self.assertEqual(sellers.product_id, self.variant_small + self.variant_large)
        self.assertEqual(
            {s.product_id.id: s.price for s in sellers},
            {self.variant_small.id: 10.0, self.variant_large.id: 20.0},
        )

    def test_variants_priced_alike_collapse_to_the_template(self):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.variant_small.id,
                            "product_qty": 1,
                            "price_unit": 15.0,
                        },
                    ),
                    Command.create(
                        {
                            "product_id": self.variant_large.id,
                            "product_qty": 1,
                            "price_unit": 15.0,
                        },
                    ),
                ],
            },
        )
        sellers = self._confirm(order)

        self.assertEqual(
            len(sellers),
            1,
            "one price for every variant is a template-level pricelist, not two",
        )
        self.assertFalse(
            sellers.product_id,
            "a template-level pricelist leaves the variant empty so it applies to all",
        )
        self.assertEqual(sellers.price, 15.0)

    def test_lead_time_is_learnt_from_the_expected_arrival(self):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.variant_small.id,
                            "product_qty": 1,
                            "price_unit": 10.0,
                        },
                    ),
                ],
            },
        )
        order.line_ids.write(
            {
                "date_is_manual": True,
                "date_commitment": fields.Datetime.now() + timedelta(days=7),
            },
        )
        sellers = self._confirm(order)

        self.assertEqual(
            sellers.delay,
            7,
            "the vendor promised seven days; the pricelist must say seven, not zero",
        )

    def test_lead_time_never_goes_negative(self):
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.variant_small.id,
                            "product_qty": 1,
                            "price_unit": 10.0,
                        },
                    ),
                ],
            },
        )
        order.line_ids.write(
            {
                "date_is_manual": True,
                "date_commitment": fields.Datetime.now() - timedelta(days=3),
            },
        )
        sellers = self._confirm(order)

        self.assertEqual(sellers.delay, 0, "a late arrival is not a negative lead time")
