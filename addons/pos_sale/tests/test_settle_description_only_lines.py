from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSettleDescriptionOnlyLines(TransactionCase):
    """Settling a sale order that carries a line with no product.

    A quotation may price work that is not a catalogue item -- the line has a
    description, an amount and no `product_id`. The register cannot hold a
    line without a product, so such a line has to arrive under a stand-in or
    the cashier settles an order that is quietly short of what was agreed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env["pos.config"].search([], limit=1)
        cls.partner = cls.env["res.partner"].create({"name": "Settle SO partner"})
        cls.catalogue_product = cls.env["product.product"].create(
            {
                "name": "Catalogue item",
                "type": "service",
                "list_price": 20.0,
                "available_in_pos": True,
            }
        )

    def _order_with_a_description_only_line(self):
        return self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.catalogue_product.id,
                            "product_qty": 1,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Custom fitting, as agreed on site",
                            "product_qty": 1,
                            "price_unit": 35.0,
                        },
                    ),
                ],
            }
        )

    def test_the_register_is_sent_the_line_with_no_product(self):
        """The description line reaches the register instead of vanishing."""
        order = self._order_with_a_description_only_line()
        description_line = order.line_ids.filtered(lambda line: not line.product_id)
        self.assertTrue(description_line, "the fixture must have a productless line")

        settled = order.line_ids.read_converted()
        self.assertIn(
            description_line.id,
            [line["id"] for line in settled],
            "a priced line with no product is part of what was sold",
        )

    def test_the_line_keeps_its_own_price_and_quantity(self):
        """Nothing about the stand-in product may reprice the line."""
        order = self._order_with_a_description_only_line()
        description_line = order.line_ids.filtered(lambda line: not line.product_id)
        settled = {line["id"]: line for line in order.line_ids.read_converted()}[
            description_line.id
        ]
        self.assertEqual(settled["price_unit"], 35.0)
        self.assertEqual(settled["product_uom_qty"], 1.0)

    def test_a_section_or_note_line_is_still_not_settled(self):
        """Layout lines are not goods and never were."""
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.catalogue_product.id,
                            "product_qty": 1,
                        },
                    ),
                    (0, 0, {"name": "A section", "display_type": "line_section"}),
                ],
            }
        )
        section = order.line_ids.filtered(
            lambda line: line.display_type == "line_section"
        )
        self.assertNotIn(
            section.id, [line["id"] for line in order.line_ids.read_converted()]
        )

    def test_the_register_knows_which_line_is_wearing_the_stand_in(self):
        """`has_default_product` is what lets the UI show the real text."""
        self.assertTrue(
            self.config.default_product_id,
            "installing pos_sale must give every register a stand-in product",
        )
        line_fields = self.env["pos.order.line"]._load_pos_data_fields(self.config)
        self.assertIn("has_default_product", line_fields)
        self.assertIn("sale_order_line_name", line_fields)
