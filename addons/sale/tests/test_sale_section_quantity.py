from psycopg.errors import CheckViolation

from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestSaleSectionQuantity(SaleCommon):
    """A section carries its own quantity, and moving it rescales what it holds."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "name": "Kitchen",
                            "display_type": "line_section",
                        }
                    ),
                    Command.create(
                        {
                            "name": "Kitchen tap",
                            "product_id": cls.product.id,
                            "product_qty": 4.0,
                        }
                    ),
                    Command.create(
                        {
                            "name": "Kitchen / Cabinets",
                            "display_type": "line_subsection",
                        }
                    ),
                    Command.create(
                        {
                            "name": "Cabinet door",
                            "product_id": cls.product.id,
                            "product_qty": 6.0,
                        }
                    ),
                    Command.create(
                        {
                            "name": "Bathroom",
                            "display_type": "line_section",
                        }
                    ),
                    Command.create(
                        {
                            "name": "Bathroom tap",
                            "product_id": cls.product.id,
                            "product_qty": 10.0,
                        }
                    ),
                ],
            }
        )
        (
            cls.kitchen,
            cls.kitchen_tap,
            cls.cabinets,
            cls.cabinet_door,
            cls.bathroom,
            cls.bathroom_tap,
        ) = cls.order.line_ids

    def test_section_quantity_defaults_to_one_unit_on_sections_only(self):
        for section in (self.kitchen, self.cabinets, self.bathroom):
            self.assertEqual(section.section_qty, 1.0)
            self.assertEqual(section.section_uom_id, self.uom_unit)
        for line in (self.kitchen_tap, self.cabinet_door, self.bathroom_tap):
            self.assertFalse(line.section_qty)
            self.assertFalse(line.section_uom_id)

    def test_section_quantity_is_forbidden_on_a_product_line(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(CheckViolation):
            self.kitchen_tap.section_qty = 3.0

    def test_raising_a_section_quantity_rescales_every_line_it_holds(self):
        self.kitchen.section_qty = 3.0

        # 3 kitchens: everything under the section, subsection included.
        self.assertEqual(self.kitchen_tap.product_qty, 12.0)
        self.assertEqual(self.cabinet_door.product_qty, 18.0)
        # The subsection's own quantity follows, so its total stays coherent.
        self.assertEqual(self.cabinets.section_qty, 3.0)
        # A neighbouring section is untouched.
        self.assertEqual(self.bathroom_tap.product_qty, 10.0)

    def test_lowering_a_section_quantity_divides_back(self):
        self.kitchen.section_qty = 4.0
        self.kitchen.section_qty = 2.0

        self.assertEqual(self.kitchen_tap.product_qty, 8.0)
        self.assertEqual(self.cabinet_door.product_qty, 12.0)

    def test_a_subsection_quantity_only_moves_its_own_lines(self):
        self.cabinets.section_qty = 5.0

        self.assertEqual(self.cabinet_door.product_qty, 30.0)
        self.assertEqual(self.kitchen_tap.product_qty, 4.0)
        self.assertEqual(self.kitchen.section_qty, 1.0)

    def test_changing_the_section_unit_converts_the_line_quantities(self):
        # One dozen kitchens is twelve kitchens.
        self.kitchen.section_uom_id = self.uom_dozen

        self.assertEqual(self.kitchen_tap.product_qty, 48.0)
        self.assertEqual(self.cabinet_door.product_qty, 72.0)

    def test_an_incompatible_section_unit_leaves_the_lines_alone(self):
        # Units and kilograms share no reference unit: there is no factor to apply.
        self.kitchen.section_uom_id = self.uom_kgm

        self.assertEqual(self.kitchen_tap.product_qty, 4.0)
        self.assertEqual(self.cabinet_door.product_qty, 6.0)

    def test_quantity_and_unit_moving_together_apply_a_single_factor(self):
        self.kitchen.write(
            {
                "section_qty": 2.0,
                "section_uom_id": self.uom_dozen.id,
            }
        )

        # 2 dozen kitchens = 24 kitchens, not 2 and then 24.
        self.assertEqual(self.kitchen_tap.product_qty, 96.0)
        self.assertEqual(self.cabinet_door.product_qty, 144.0)
