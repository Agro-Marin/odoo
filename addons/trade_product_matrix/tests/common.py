import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class OrderProductMatrixCase(TransactionCase):
    allow_inherited_tests_method = True
    order_model = ""
    conflict_message = ""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        size, color = cls.env["product.attribute"].create(
            [
                {"name": "Grid Size", "create_variant": "always"},
                {"name": "Grid Color", "create_variant": "always"},
            ]
        )
        cls.env["product.attribute.value"].create(
            [
                {"name": name, "attribute_id": attribute.id}
                for attribute, names in ((size, ("S", "M")), (color, ("Red", "Blue")))
                for name in names
            ]
        )
        cls.template = cls.env["product.template"].create(
            {
                "name": "Grid Shirt",
                "type": "consu",
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {"attribute_id": a.id, "value_ids": [(6, 0, a.value_ids.ids)]},
                    )
                    for a in (size, color)
                ],
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Grid Partner"})

    def _ptavs(self, *names):
        return self.template.attribute_line_ids.product_template_value_ids.filtered(
            lambda ptav: ptav.name in names
        )

    def _order(self):
        return self.env[self.order_model].create({"partner_id": self.partner.id})

    def _apply(self, order, *cells):
        order.grid = json.dumps(
            {
                "product_template_id": self.template.id,
                "changes": [
                    {"ptav_ids": self._ptavs(*names).ids, "qty": qty}
                    for names, qty in cells
                ],
            }
        )
        order.grid_update = True
        order._apply_grid()

    def _variant(self, *names):
        return self.template.product_variant_ids.filtered(
            lambda product: (
                set(product.product_template_attribute_value_ids.mapped("name"))
                == set(names)
            )
        )

    def _cell_qty(self, matrix, *names):
        ids = sorted(self._ptavs(*names).ids)
        return next(
            cell["qty"]
            for row in matrix["matrix"]
            for cell in row
            if cell.get("ptav_ids") == ids
        )

    def test_grid_creates_a_line_per_changed_cell(self):
        order = self._order()
        self._apply(order, (("S", "Red"), 2), (("M", "Blue"), 3))
        self.assertEqual(
            {(line.product_id, line.product_qty) for line in order.line_ids},
            {(self._variant("S", "Red"), 2), (self._variant("M", "Blue"), 3)},
        )

    def test_grid_updates_and_removes_existing_lines(self):
        order = self._order()
        self._apply(order, (("S", "Red"), 2), (("M", "Blue"), 3))
        self._apply(order, (("S", "Red"), 5), (("M", "Blue"), 0))
        self.assertEqual(order.line_ids.product_id, self._variant("S", "Red"))
        self.assertEqual(order.line_ids.product_qty, 5)

    def test_grid_refuses_a_variant_on_several_lines(self):
        order = self._order()
        self._apply(order, (("S", "Red"), 1))
        order.line_ids.copy({"order_id": order.id})
        with self.assertRaisesRegex(ValidationError, self.conflict_message):
            self._apply(order, (("S", "Red"), 4))

    def test_matrix_reads_the_order_quantities(self):
        order = self._order()
        self._apply(order, (("S", "Red"), 2), (("M", "Blue"), 3))
        matrix = order._get_matrix(self.template)
        self.assertEqual(self._cell_qty(matrix, "S", "Red"), 2)
        self.assertEqual(self._cell_qty(matrix, "M", "Blue"), 3)
        self.assertEqual(self._cell_qty(matrix, "S", "Blue"), 0)

    def test_report_grids_can_be_turned_off(self):
        order = self._order()
        self._apply(order, (("S", "Red"), 2), (("M", "Blue"), 3))
        order.report_grids = False
        self.assertEqual(order.get_report_matrixes(), [])
