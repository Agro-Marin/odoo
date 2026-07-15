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

    def test_monetary_opt_widget_blanks_unset_amount(self):
        """ir.qweb.field.monetary_opt.value_to_html

        The MO Overview report uses False as a "not applicable" sentinel for
        cost cells (mirroring the OWL props type [Number, Boolean]). The base
        'monetary' widget rejects booleans and raises, so those cells use the
        'monetary_opt' widget instead: an unset (False/None) amount renders
        blank, while a genuine amount — including 0 — still renders.
        """
        converter = self.env["ir.qweb.field.monetary_opt"]
        options = {"display_currency": self.env.company.currency_id}
        self.assertEqual(converter.value_to_html(False, options), "")
        self.assertEqual(converter.value_to_html(None, options), "")
        # A real amount (and a genuine 0) is delegated to the parent monetary
        # converter and still rendered as a currency value.
        self.assertIn("oe_currency_value", converter.value_to_html(0.0, options))
        self.assertIn("oe_currency_value", converter.value_to_html(12.5, options))

    def test_mo_overview_report_renders_with_unset_costs(self):
        """report.mrp.report_mo_overview (PDF/HTML rendering)

        A confirmed MO whose operations carry no BoM cost reports bom_cost as
        False. Rendering the report with the BoM Costs column enabled must not
        raise 'The value send to monetary field is not a number.' — the False
        cell is rendered blank via the 'monetary_opt' widget.
        """
        # A zero-cost workcenter makes the operation's bom_cost falsy -> False.
        self.workcenter_1.costs_hour = 0.0
        product = (
            self.bom_2.product_id or self.bom_2.product_tmpl_id.product_variant_ids[:1]
        )
        mo = self.env["mrp.production"].create(
            {"product_id": product.id, "bom_id": self.bom_2.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        html, content_type = self.env["ir.actions.report"]._render_qweb_html(
            "mrp.report_mo_overview",
            mo.ids,
            data={
                "moCosts": "1",
                "bomCosts": "1",
                "realCosts": "1",
                "unfoldedIds": "[]",
            },
        )
        self.assertEqual(content_type, "html")
        self.assertTrue(html, "The MO Overview report should render non-empty HTML.")

    def test_bom_producible_qty_sums_mixed_uom_component_lines(self):
        """report.mrp.report_bom_structure._compute_current_production_capacity

        A component on two BoM lines in *different* UoMs is not merged (merging
        requires the same UoM), so both rows reach the producible computation.
        "Ready To Produce" must sum the two demands in a single unit and use the
        component's free stock once — not add raw quantities across units and
        overwrite the availability with whichever line is iterated last.
        """
        unit = self.env.ref("uom.product_uom_unit")
        dozen = self.env.ref("uom.product_uom_dozen")
        component = self.env["product.product"].create(
            {"name": "Mixed-UoM Component", "is_storable": True, "uom_id": unit.id}
        )
        finished = self.env["product.product"].create(
            {"name": "Mixed-UoM Finished", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create(
                        {
                            "product_id": component.id,
                            "product_qty": 2.0,
                            "product_uom_id": unit.id,
                        }
                    ),
                    Command.create(
                        {
                            "product_id": component.id,
                            "product_qty": 1.0,
                            "product_uom_id": dozen.id,
                        }
                    ),
                ],
            }
        )
        # 28 units on hand -> demand per finished unit = 2 + (1 dozen = 12) = 14
        # units -> floor(28 / 14) = 2 producible. The pre-fix code mixed units
        # (2 + 1 = 3) and overwrote availability, yielding a wrong count.
        self.env["stock.quant"]._update_available_quantity(
            component, self.env.ref("stock.stock_location_stock"), 28.0
        )
        data = self.env["report.mrp.report_bom_structure"]._get_report_data(
            bom_id=bom.id, searchQty=1, searchVariant=False
        )
        comp_rows = [
            line
            for line in data["lines"]["components"]
            if line["product"].id == component.id
        ]
        self.assertEqual(
            len(comp_rows), 2, "Different-UoM component lines must not be merged."
        )
        self.assertEqual(
            data["lines"]["producible_qty"],
            2.0,
            "Ready-To-Produce must sum mixed-UoM demand (2u + 1doz = 14u) against "
            "28u of stock -> 2.",
        )
