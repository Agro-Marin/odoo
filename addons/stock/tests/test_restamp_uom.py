"""Changing a product's unit must behave the same from the variant and the template."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRestampUom(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.pack_of_6 = cls.env.ref("uom.product_uom_pack_6")
        cls.dozen = cls.env.ref("uom.product_uom_dozen")
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)

    def _product_with_a_move(self, name, move_uom):
        product = self.env["product.product"].create(
            {
                "name": name,
                "type": "consu",
                "is_storable": True,
                "uom_id": self.unit.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 3,
                "product_uom_id": move_uom.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        move._action_confirm()
        self.env.flush_all()
        self.env.invalidate_all()
        return product, move

    def test_restamp_from_the_variant(self):
        """The variant's `uom_id` is related, and the ORM fills its cache with the new
        unit before determining that inverse -- so a guard reading it compared the
        history against the unit being moved *to*, and refused every product that had
        ever moved."""
        product, move = self._product_with_a_move("variant path", self.unit)

        product.uom_id = self.pack_of_6
        self.env.flush_all()

        self.assertEqual(move.product_uom_id, self.pack_of_6)

    def test_restamp_from_the_template(self):
        product, move = self._product_with_a_move("template path", self.unit)

        product.product_tmpl_id.uom_id = self.pack_of_6
        self.env.flush_all()

        self.assertEqual(move.product_uom_id, self.pack_of_6)

    def test_history_in_another_unit_is_still_refused_from_the_variant(self):
        """The quantities are not converted, so a move recorded in some other unit
        would be silently reinterpreted."""
        product, __ = self._product_with_a_move("mixed variant", self.dozen)

        with self.assertRaises(UserError) as caught:
            product.uom_id = self.pack_of_6
            self.env.flush_all()
        self.assertIn("Dozens", str(caught.exception))
        self.assertIn(
            "Units",
            str(caught.exception),
            "the message must name the unit being left, not the one being moved to",
        )

    def test_history_in_another_unit_is_still_refused_from_the_template(self):
        product, __ = self._product_with_a_move("mixed template", self.dozen)

        with self.assertRaises(UserError):
            product.product_tmpl_id.uom_id = self.pack_of_6
            self.env.flush_all()
