# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestMrpAuditFixes(TestMrpCommon):
    """Regression tests for the correctness fixes applied to the MRP module.

    Each test is written so that it fails against the pre-fix code and passes
    afterwards; the docstring names the method that was corrected.
    """

    def test_report_bom_structure_merges_duplicate_component_qty(self):
        """report.mrp.report_bom_structure._merge_components

        When the same component appears on two BoM lines the report merges them
        into a single row. `base_bom_line_qty` (which feeds the "producible" /
        ready-to-produce computation) must be the SUM of the two lines' per-unit
        quantities, not `merged_quantity + second_line_quantity`.
        """
        final = self.env["product.product"].create(
            {"name": "Audit Final", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Audit Component", "is_storable": True, "standard_price": 1.0}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": final.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 2.0}),
                    Command.create({"product_id": component.id, "product_qty": 3.0}),
                ],
            }
        )

        report = self.env["report.mrp.report_bom_structure"]
        data = report._get_report_data(bom_id=bom.id, searchQty=1, searchVariant=False)

        merged = [
            line
            for line in data["lines"]["components"]
            if line["product"].id == component.id
        ]
        self.assertEqual(
            len(merged), 1, "The duplicated component must be merged into one row."
        )
        # 2 + 3 = 5. The pre-fix code produced (2 + 3) + 3 = 8.
        self.assertAlmostEqual(
            merged[0]["base_bom_line_qty"],
            5.0,
            msg="Merged base_bom_line_qty must sum the two lines (2 + 3 = 5).",
        )
        # The scaled quantity (also 5 at searchQty=1) stays correct too.
        self.assertAlmostEqual(merged[0]["quantity"], 5.0)

    def test_create_mo_with_non_create_finished_command_and_byproduct(self):
        """mrp.production.create

        Passing both `move_finished_ids` (with a non-CREATE command, whose [2]
        element is not a values dict) and `move_byproduct_ids` must not raise.
        The pre-fix code did `command[2]["product_id"]` unconditionally and
        crashed (TypeError) on any non-CREATE command. `Command.set([])` is used
        here because its [2] is a list, reproducing the crash without needing an
        external move to link.
        """
        final = self.env["product.product"].create(
            {"name": "Audit Final 2", "is_storable": True}
        )
        byproduct = self.env["product.product"].create(
            {"name": "Audit Byproduct", "is_storable": True}
        )
        picking_type = self.env["mrp.production"]._get_default_picking_type_id(
            self.env.company.id
        )

        # Should not raise (pre-fix: TypeError on the non-CREATE command).
        mo = self.env["mrp.production"].create(
            {
                "product_id": final.id,
                "product_qty": 1.0,
                "picking_type_id": picking_type,
                "move_finished_ids": [Command.set([])],
                "move_byproduct_ids": [
                    Command.create(
                        {
                            "product_id": byproduct.id,
                            "product_uom_qty": 1.0,
                            "product_uom_id": byproduct.uom_id.id,
                            "location_id": self.env.ref(
                                "stock.stock_location_stock"
                            ).id,
                            "location_dest_id": self.env.ref(
                                "stock.stock_location_stock"
                            ).id,
                        }
                    )
                ],
            }
        )
        self.assertIn(
            byproduct,
            mo.move_byproduct_ids.product_id,
            "The by-product move must survive the create() command normalization.",
        )
