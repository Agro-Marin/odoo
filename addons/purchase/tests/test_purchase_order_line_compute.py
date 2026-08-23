from datetime import timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseOrderLineCompute(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_with_sellers = cls.env["product.product"].create(
            {
                "name": "Product With Sellers",
                "standard_price": 50.0,
                "seller_ids": [
                    Command.create(
                        {
                            "partner_id": cls.partner_a.id,
                            "min_qty": 1,
                            "price": 10.0,
                            "discount": 5.0,
                            "delay": 3,
                            "product_code": "PROD-A",
                            "product_name": "Product from Vendor A",
                        }
                    ),
                    Command.create(
                        {
                            "partner_id": cls.partner_a.id,
                            "min_qty": 10,
                            "price": 8.0,
                            "discount": 10.0,
                            "delay": 2,
                            "product_code": "PROD-A-BULK",
                            "product_name": "Product from Vendor A (Bulk)",
                        }
                    ),
                    Command.create(
                        {
                            "partner_id": cls.partner_b.id,
                            "min_qty": 1,
                            "price": 12.0,
                            "discount": 0.0,
                            "delay": 5,
                            "product_code": "PROD-B",
                            "product_name": "Product from Vendor B",
                        }
                    ),
                ],
            }
        )
        cls.product_without_sellers = cls.env["product.product"].create(
            {
                "name": "Product Without Sellers",
                "standard_price": 100.0,
            }
        )

    def test_selected_seller_id_stored(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertTrue(line._fields["selected_seller_id"].store)

        self.assertTrue(line.selected_seller_id)
        self.assertEqual(line.selected_seller_id.min_qty, 1)
        self.assertEqual(line.selected_seller_id.price, 10.0)

    def test_selected_seller_id_changes_with_quantity(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertEqual(line.selected_seller_id.min_qty, 1)
        self.assertEqual(line.price_unit, 10.0)
        self.assertEqual(line.discount, 5.0)

        line.product_qty = 15
        self.assertEqual(line.selected_seller_id.min_qty, 10)
        self.assertEqual(line.price_unit, 8.0)
        self.assertEqual(line.discount, 10.0)

        line.product_qty = 5
        self.assertEqual(line.selected_seller_id.min_qty, 1)
        self.assertEqual(line.price_unit, 10.0)
        self.assertEqual(line.discount, 5.0)

    def test_selected_seller_id_changes_with_partner(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertEqual(line.selected_seller_id.partner_id, self.partner_a)
        self.assertEqual(line.price_unit, 10.0)

        po.partner_id = self.partner_b
        self.assertEqual(line.selected_seller_id.partner_id, self.partner_b)
        self.assertEqual(line.price_unit, 12.0)

    def test_selected_seller_id_none_when_no_match(self):
        partner_c = self.env["res.partner"].create({"name": "Partner C"})

        po = self.env["purchase.order"].create(
            {
                "partner_id": partner_c.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertFalse(line.selected_seller_id)
        self.assertEqual(line.price_unit, 50.0)
        self.assertEqual(line.discount, 0.0)

    def test_selected_seller_id_none_for_product_without_sellers(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_without_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertFalse(line.selected_seller_id)
        self.assertEqual(line.price_unit, 100.0)
        self.assertEqual(line.discount, 0.0)

    def test_price_unit_auto_tracks_computed_price(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertEqual(line.price_unit, 10.0)
        self.assertEqual(line.price_unit_auto, 10.0)

        line.product_qty = 15
        self.assertEqual(line.price_unit, 8.0)
        self.assertEqual(line.price_unit_auto, 8.0)

    def test_manual_price_override_preserved_on_qty_change(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertEqual(line.price_unit, 10.0)
        self.assertEqual(line.price_unit_auto, 10.0)

        line.price_unit = 99.0

        line.product_qty = 15
        self.assertEqual(line.price_unit, 99.0, "Manual price should be preserved")
        self.assertEqual(line.price_unit_auto, 8.0)

    def test_manual_price_override_preserved_on_partner_change(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        line.price_unit = 99.0

        po.partner_id = self.partner_b
        self.assertEqual(line.price_unit, 99.0, "Manual price should be preserved")
        self.assertEqual(line.price_unit_auto, 12.0)

    def test_price_resets_on_product_change(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner_a
        with po_form.line_ids.new() as line:
            line.product_id = self.product_with_sellers
            line.product_qty = 5
        po = po_form.save()
        line = po.line_ids

        line.price_unit = 99.0
        self.assertEqual(line.price_unit, 99.0)

        with Form(po) as po_form:
            with po_form.line_ids.edit(0) as line_form:
                line_form.product_id = self.product_without_sellers
        self.assertEqual(
            po.line_ids.price_unit, 100.0, "Price should reset on product change"
        )

    def test_discount_updates_with_seller(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertEqual(line.discount, 5.0)

        line.product_qty = 15
        self.assertEqual(line.discount, 10.0)

        line.product_qty = 0.5
        self.assertEqual(line.discount, 0.0)

    def test_name_computed_from_seller(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner_a
        with po_form.line_ids.new() as line:
            line.product_id = self.product_with_sellers
            line.product_qty = 5
        po = po_form.save()

        self.assertIn("PROD-A", po.line_ids.name)

    def test_name_updates_on_seller_change(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner_a
        with po_form.line_ids.new() as line:
            line.product_id = self.product_with_sellers
            line.product_qty = 5
        po = po_form.save()

        self.assertIn("PROD-A", po.line_ids.name)
        self.assertNotIn("BULK", po.line_ids.name)

        po.line_ids.product_qty = 15
        self.assertIn("PROD-A-BULK", po.line_ids.name)

    def test_custom_name_preserved_on_qty_change(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner_a
        with po_form.line_ids.new() as line:
            line.product_id = self.product_with_sellers
            line.product_qty = 5
        po = po_form.save()
        line = po.line_ids

        custom_name = "My custom product description"
        line.name = custom_name

        line.product_qty = 15

        self.assertEqual(line.name, custom_name)

    @freeze_time("2024-01-15")
    def test_date_commitment_computed_from_seller_delay(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        expected_date = fields.Datetime.now() + timedelta(days=3)
        self.assertEqual(line.date_commitment.date(), expected_date.date())

    @freeze_time("2024-01-15")
    def test_date_commitment_updates_on_seller_change(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        initial_date = fields.Datetime.now() + timedelta(days=3)
        self.assertEqual(line.date_commitment.date(), initial_date.date())

        line.product_qty = 15
        expected_date = fields.Datetime.now() + timedelta(days=2)
        self.assertEqual(line.date_commitment.date(), expected_date.date())

    @freeze_time("2024-01-15")
    def test_custom_date_commitment_preserved(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        custom_date = fields.Datetime.now() + timedelta(days=30)
        line.date_commitment = custom_date

        line.product_qty = 15

        self.assertEqual(line.date_commitment.date(), custom_date.date())

    def test_form_price_computation_flow(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner_a

        with po_form.line_ids.new() as line:
            line.product_id = self.product_with_sellers
            self.assertEqual(line.price_unit, 10.0)

            line.product_qty = 15
            self.assertEqual(line.price_unit, 8.0)

            line.price_unit = 50.0

        po = po_form.save()
        self.assertEqual(po.line_ids.price_unit, 50.0)

        with Form(po) as po_form:
            with po_form.line_ids.edit(0) as line:
                line.product_qty = 20
                self.assertEqual(line.price_unit, 50.0)

    def test_form_partner_change_updates_all_lines(self):
        po_form = Form(self.env["purchase.order"])
        po_form.partner_id = self.partner_a
        with po_form.line_ids.new() as line:
            line.product_id = self.product_with_sellers
            line.product_qty = 5
        po = po_form.save()

        self.assertEqual(po.line_ids.price_unit, 10.0)
        self.assertIn("PROD-A", po.line_ids.name)

        po.partner_id = self.partner_b

        self.assertEqual(po.line_ids.price_unit, 12.0)
        self.assertIn("PROD-B", po.line_ids.name)

    def test_display_type_lines_ignored(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "display_type": "line_section",
                            "name": "Section Header",
                        }
                    ),
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    ),
                ],
            }
        )

        section_line = po.line_ids.filtered(lambda l: l.display_type)
        product_line = po.line_ids.filtered(lambda l: not l.display_type)

        self.assertFalse(section_line.selected_seller_id)
        self.assertFalse(section_line.price_unit)
        self.assertTrue(product_line.selected_seller_id)
        self.assertEqual(product_line.price_unit, 10.0)

    def test_zero_quantity_line(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 0,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertTrue(line.selected_seller_id)

    @freeze_time("2024-01-15")
    def test_date_is_manual_initially_false(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertFalse(line.date_is_manual)
        expected_date = fields.Datetime.now() + timedelta(days=3)
        self.assertEqual(line.date_commitment.date(), expected_date.date())

    @freeze_time("2024-01-15")
    def test_date_is_manual_set_via_onchange(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        self.assertFalse(line.date_is_manual)

        custom_date = fields.Datetime.now() + timedelta(days=30)
        line.write(
            {
                "date_commitment": custom_date,
                "date_is_manual": True,
            }
        )

        self.assertTrue(po.line_ids.date_is_manual)
        self.assertEqual(po.line_ids.date_commitment.date(), custom_date.date())

    @freeze_time("2024-01-15")
    def test_date_preserved_when_manual_flag_set(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        custom_date = fields.Datetime.now() + timedelta(days=30)
        line.write(
            {
                "date_commitment": custom_date,
                "date_is_manual": True,
            }
        )

        line.product_qty = 15

        self.assertEqual(line.date_commitment.date(), custom_date.date())
        self.assertTrue(line.date_is_manual)

    @freeze_time("2024-01-15")
    def test_date_updates_without_manual_flag(self):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_with_sellers.id,
                            "product_qty": 5,
                        }
                    )
                ],
            }
        )
        line = po.line_ids

        initial_date = fields.Datetime.now() + timedelta(days=3)
        self.assertEqual(line.date_commitment.date(), initial_date.date())
        self.assertFalse(line.date_is_manual)

        line.product_qty = 15

        expected_date = fields.Datetime.now() + timedelta(days=2)
        self.assertEqual(line.date_commitment.date(), expected_date.date())
        self.assertFalse(line.date_is_manual)
