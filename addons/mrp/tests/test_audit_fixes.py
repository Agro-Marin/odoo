# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError, ValidationError
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

    def test_bom_create_syncs_product_uom_id(self):
        """mrp.bom.create

        A BoM created in code (no `product_uom_id` given) for a product measured
        in a non-default UoM must inherit the product's UoM, not the field's
        default ("Units"). Otherwise every UoM conversion in the BoM/MO reports
        and in explode() raises "cannot be converted" across UoM categories.
        """
        square_meter = self.env.ref("uom.product_uom_square_meter")
        template = self.env["product.template"].create(
            {"name": "Audit m2 product", "uom_id": square_meter.id}
        )
        bom = self.env["mrp.bom"].create(
            {"product_tmpl_id": template.id, "product_qty": 1.0}
        )
        self.assertEqual(
            bom.product_uom_id,
            square_meter,
            "BoM UoM must follow the product's UoM when not given explicitly.",
        )

    def test_routing_bom_change_removes_only_moved_operation_blocker(self):
        """mrp.routing.workcenter.write (bom_id change)

        Moving an operation to another BoM must strip *only that operation* from
        the blockers of its former siblings, leaving the other blockers intact.
        The pre-fix code compared a recordset to a singleton
        (`blocked_by_operation_ids == op`) and then cleared *all* blockers.
        """
        product = self.env["product.product"].create(
            {"name": "Audit Dep Final", "is_storable": True}
        )
        wc = self.workcenter_1
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1.0,
                "allow_operation_dependencies": True,
                "operation_ids": [
                    Command.create({"name": "OP A", "workcenter_id": wc.id}),
                    Command.create({"name": "OP B", "workcenter_id": wc.id}),
                    Command.create({"name": "OP C", "workcenter_id": wc.id}),
                ],
            }
        )
        op_a, op_b, op_c = bom.operation_ids
        # C is blocked by BOTH A and B.
        op_c.blocked_by_operation_ids = [Command.set((op_a + op_b).ids)]
        self.assertEqual(op_c.blocked_by_operation_ids, op_a + op_b)

        other_bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1.0,
                "allow_operation_dependencies": True,
            }
        )
        # Move A to another BoM; only A must be removed from C's blockers.
        op_a.bom_id = other_bom.id
        self.assertEqual(
            op_c.blocked_by_operation_ids,
            op_b,
            "Only the moved operation (A) may be removed; B must remain a blocker.",
        )

    def test_explode_detects_phantom_cycle(self):
        """mrp.bom.explode

        A phantom-BoM cycle (A's kit contains B, B's kit contains A) must raise a
        clean ValidationError rather than looping forever. `_check_bom_cycle`
        resolves BoMs without the phantom/company/picking_type parameters that
        explode() uses, so a phantom-specific cycle can slip past the config-time
        constraint; the runtime guard in explode() is the backstop. The
        constraint is patched off here only to build the cyclic data that would
        otherwise be rejected at save time.
        """
        prod_a = self.env["product.product"].create(
            {"name": "Cycle A", "is_storable": True}
        )
        prod_b = self.env["product.product"].create(
            {"name": "Cycle B", "is_storable": True}
        )
        # Two empty phantom BoMs (each valid on its own).
        bom_a = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": prod_a.product_tmpl_id.id,
                "product_id": prod_a.id,
                "product_qty": 1.0,
                "type": "phantom",
            }
        )
        bom_b = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": prod_b.product_tmpl_id.id,
                "product_id": prod_b.id,
                "product_qty": 1.0,
                "type": "phantom",
            }
        )
        # Close the loop (A's kit -> B, B's kit -> A) with direct SQL to bypass
        # the config-time _check_bom_cycle constraint, simulating a phantom cycle
        # it failed to resolve (it omits the phantom/company/picking_type
        # parameters that explode() uses).
        self.env.cr.execute(
            """
            INSERT INTO mrp_bom_line (product_id, product_uom_id, bom_id, product_qty)
            VALUES (%s, %s, %s, 1), (%s, %s, %s, 1)
            """,
            (
                prod_b.id,
                prod_b.uom_id.id,
                bom_a.id,
                prod_a.id,
                prod_a.uom_id.id,
                bom_b.id,
            ),
        )
        self.env["mrp.bom"].invalidate_model()
        self.env["mrp.bom.line"].invalidate_model()
        # Pre-fix: this would loop forever (the BFS queue grows without bound).
        with self.assertRaises(ValidationError):
            bom_a.explode(prod_a, 1.0)

    def test_bom_rejects_product_uom_of_another_category(self):
        """mrp.bom._check_product_uom_id_category

        `create` aligns the BoM unit with the product's only when it is not
        supplied (see test_bom_create_syncs_product_uom_id). An explicit
        cross-category unit had nothing stopping it, and `product_qty` is
        expressed in it: every explosion and cost roll-up then scaled by the
        ratio of two unrelated factors.
        """
        kgm = self.env.ref("uom.product_uom_kgm")
        unit = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "Audit uom-category product", "uom_id": unit.id}
        )
        with self.assertRaises(ValidationError):
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": template.id,
                    "product_qty": 1.0,
                    "product_uom_id": kgm.id,
                }
            )

    def test_bom_accepts_convertible_product_uom(self):
        """Control: a different but convertible unit stays allowed."""
        dozen = self.env.ref("uom.product_uom_dozen")
        unit = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "Audit dozen product", "uom_id": unit.id}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": template.id,
                "product_qty": 1.0,
                "product_uom_id": dozen.id,
            }
        )
        self.assertEqual(bom.product_uom_id, dozen)

    def test_bom_line_rejects_product_uom_of_another_category(self):
        """mrp.bom.line._check_product_uom_id_category"""
        kgm = self.env.ref("uom.product_uom_kgm")
        unit = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "Audit line parent", "uom_id": unit.id}
        )
        component = self.env["product.product"].create(
            {"name": "Audit line component", "uom_id": unit.id}
        )
        with self.assertRaises(ValidationError):
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": template.id,
                    "product_qty": 1.0,
                    "bom_line_ids": [
                        Command.create(
                            {
                                "product_id": component.id,
                                "product_qty": 1.0,
                                "product_uom_id": kgm.id,
                            }
                        )
                    ],
                }
            )

    def test_byproduct_rejects_product_uom_of_another_category(self):
        """mrp.bom.byproduct._check_product_uom_id_category

        The UoM compute on by-products is `readonly=False`, so an explicit
        value survives and would feed `cost_share` allocation in a unit
        unrelated to the by-product.
        """
        kgm = self.env.ref("uom.product_uom_kgm")
        unit = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "Audit byproduct parent", "uom_id": unit.id}
        )
        byproduct = self.env["product.product"].create(
            {"name": "Audit byproduct", "uom_id": unit.id}
        )
        with self.assertRaises(ValidationError):
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": template.id,
                    "product_qty": 1.0,
                    "byproduct_ids": [
                        Command.create(
                            {
                                "product_id": byproduct.id,
                                "product_qty": 1.0,
                                "product_uom_id": kgm.id,
                            }
                        )
                    ],
                }
            )

    # ------------------------------------------------------------------
    # mrp.workorder.write -- per-record derived values
    # ------------------------------------------------------------------
    def _audit_mo_with_two_workorders(self):
        unit = self.env.ref("uom.product_uom_unit")
        finished = self.env["product.product"].create(
            {"name": "Audit WO finished", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Audit WO component", "is_storable": True}
        )
        workcenter_a = self.env["mrp.workcenter"].create(
            {"name": "Audit WC A", "time_efficiency": 100.0}
        )
        workcenter_b = self.env["mrp.workcenter"].create(
            {"name": "Audit WC B", "time_efficiency": 100.0}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "product_uom_id": unit.id,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1.0})
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "product_qty": 1.0, "bom_id": bom.id}
        )
        workorders = self.env["mrp.workorder"].create(
            [
                {
                    "name": "Audit WO 1",
                    "workcenter_id": workcenter_a.id,
                    "product_uom_id": unit.id,
                    "production_id": production.id,
                    "duration_expected": 60.0,
                },
                {
                    "name": "Audit WO 2",
                    "workcenter_id": workcenter_b.id,
                    "product_uom_id": unit.id,
                    "production_id": production.id,
                    "duration_expected": 30.0,
                },
            ]
        )
        return production, workorders

    def test_workorder_write_keeps_per_record_end_date(self):
        """mrp.workorder.write

        `date_end` is recomputed from each work order's own duration. It used to
        be written back into the dict shared by the whole recordset, so a single
        `write` of both dates gave every work order the end date computed for the
        last one.
        """
        _production, workorders = self._audit_mo_with_two_workorders()
        start = datetime(2030, 1, 1, 8, 0, 0)
        workorders.write({"date_start": start, "date_end": start + timedelta(hours=1)})
        self.assertEqual(workorders[0].date_end, start + timedelta(minutes=60))
        self.assertEqual(workorders[1].date_end, start + timedelta(minutes=30))

    def test_workorder_write_keeps_per_record_duration(self):
        """mrp.workorder.write

        The multi-edit shape: only `date_start` is sent, for two work orders
        already planned over different spans. Each one's `duration_expected` is
        derived from its own span, and they must not collapse onto one value.
        """
        _production, workorders = self._audit_mo_with_two_workorders()
        base = datetime(2030, 2, 1, 6, 0, 0)
        workorders[0].write(
            {
                "date_start": base,
                "date_end": base + timedelta(hours=6),
                "duration_expected": 360.0,
            }
        )
        workorders[1].write(
            {
                "date_start": base,
                "date_end": base + timedelta(hours=10),
                "duration_expected": 600.0,
            }
        )
        workorders.write({"date_start": base + timedelta(hours=1)})
        self.assertNotEqual(
            workorders[0].duration_expected,
            workorders[1].duration_expected,
            "the two work orders span different intervals and cannot share a duration",
        )

    def test_workorder_write_does_not_mutate_caller_vals(self):
        """mrp.workorder.write must not rewrite the dict it was handed."""
        _production, workorders = self._audit_mo_with_two_workorders()
        # The 30-minute work order, against a one-hour request: the recomputed
        # end date differs from the one passed in, so a write-back is visible.
        vals = {
            "date_start": datetime(2030, 3, 1, 8, 0, 0),
            "date_end": datetime(2030, 3, 1, 9, 0, 0),
        }
        snapshot = dict(vals)
        workorders[1].write(vals)
        self.assertEqual(vals, snapshot)

    # ------------------------------------------------------------------
    # mrp.production.write -- multi-record safety
    # ------------------------------------------------------------------
    def _audit_two_productions(self):
        unit = self.env.ref("uom.product_uom_unit")
        finished = self.env["product.product"].create(
            {"name": "Audit MO finished", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Audit MO component", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "product_uom_id": unit.id,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1.0})
                ],
            }
        )
        productions = self.env["mrp.production"].create(
            [
                {"product_id": finished.id, "product_qty": 5.0, "bom_id": bom.id},
                {"product_id": finished.id, "product_qty": 5.0, "bom_id": bom.id},
            ]
        )
        return productions, component, unit

    def test_production_write_multi_record_with_raw_moves(self):
        """mrp.production.write

        Adding a component to several manufacturing orders at once used to raise
        `Expected singleton`: the method read `self.state` and
        `self.location_src_id` straight off the recordset. Each order must get
        its own move, stamped with its own source warehouse.
        """
        productions, component, unit = self._audit_two_productions()
        productions.action_confirm()
        productions.write(
            {
                "move_raw_ids": [
                    Command.create(
                        {
                            "product_id": component.id,
                            "product_uom_qty": 1.0,
                            "product_uom_id": unit.id,
                        }
                    )
                ]
            }
        )
        for production in productions:
            added = production.move_raw_ids.filtered(lambda m: not m.bom_line_id)
            self.assertEqual(len(added), 1)
            self.assertEqual(
                added.warehouse_id, production.location_src_id.warehouse_id
            )

    def test_production_write_multi_record_product_id_is_dropped(self):
        """mrp.production.write

        `product_id` is silently dropped once an order has left draft. On a
        recordset the guard used to raise `Expected singleton` instead.
        """
        productions, _component, _unit = self._audit_two_productions()
        original = productions.product_id
        productions.action_confirm()
        other = self.env["product.product"].create(
            {"name": "Audit MO other", "is_storable": True}
        )
        productions.write({"product_id": other.id})
        self.assertEqual(productions.product_id, original)

    def test_production_write_does_not_mutate_caller_vals(self):
        """mrp.production.write must not rewrite the dict it was handed."""
        productions, _component, _unit = self._audit_two_productions()
        productions.action_confirm()
        vals = {"product_id": productions[0].product_id.id, "priority": "1"}
        snapshot = dict(vals)
        productions.write(vals)
        self.assertEqual(vals, snapshot)

    # ------------------------------------------------------------------
    # Misc robustness
    # ------------------------------------------------------------------
    def test_get_name_backorder_reads_its_own_group(self):
        """mrp.production._get_name_backorder

        It reads `self.production_group_id`, so it is not an `@api.model`
        helper; called on the bare model the `max()` over an empty group raised.
        """
        self.assertEqual(
            self.env["mrp.production"]._get_name_backorder("WH/MO/00001-002", 3),
            "WH/MO/00001-003",
        )

    def test_autoprint_mass_generated_lots_without_label_format(self):
        """mrp.production._autoprint_mass_generated_lots

        The label format is an optional selection. With no format set, neither
        print branch bound `action` and `clean_action` raised UnboundLocalError.
        """
        productions, _component, _unit = self._audit_two_productions()
        picking_type = productions[0].picking_type_id
        picking_type.write(
            {
                "auto_print_generated_mrp_lot": True,
                "generated_mrp_lot_label_to_print": False,
            }
        )
        self.assertEqual(productions._autoprint_mass_generated_lots(), [])

    def test_bom_overview_attachment_lookup(self):
        """report.mrp.report_bom_structure._has_bom_attachment

        Resolved from one batched index instead of a `search_count` per node;
        it must still answer for both a variant-level and a template-level
        document.
        """
        report = self.env["report.mrp.report_bom_structure"]
        on_variant = self.env["product.product"].create(
            {"name": "Audit attach variant", "is_storable": True}
        )
        on_template = self.env["product.product"].create(
            {"name": "Audit attach template", "is_storable": True}
        )
        plain = self.env["product.product"].create(
            {"name": "Audit attach none", "is_storable": True}
        )
        self.env["product.document"].create(
            [
                {
                    "name": "variant-spec.txt",
                    "attached_on_mrp": "bom",
                    "res_model": "product.product",
                    "res_id": on_variant.id,
                },
                {
                    "name": "template-spec.txt",
                    "attached_on_mrp": "bom",
                    "res_model": "product.template",
                    "res_id": on_template.product_tmpl_id.id,
                },
            ]
        )
        # A variant-level document answers for the variant only ...
        self.assertTrue(report._has_bom_attachment(on_variant))
        self.assertFalse(
            report._has_bom_attachment(template=on_variant.product_tmpl_id)
        )
        # ... a template-level one answers for both.
        self.assertTrue(report._has_bom_attachment(on_template))
        self.assertTrue(
            report._has_bom_attachment(template=on_template.product_tmpl_id)
        )
        self.assertFalse(report._has_bom_attachment(plain))
        self.assertFalse(report._has_bom_attachment(template=plain.product_tmpl_id))

    # ------------------------------------------------------------------
    # Batched counts. Unlike the tests above these pass against the
    # pre-batch code too: they exist to pin the answers a `search_count`
    # per record used to give, now that two grouped queries give them.
    # ------------------------------------------------------------------
    def test_bom_counts_are_deduplicated(self):
        """product.template._compute_bom_count / _compute_used_in_bom_count

        A BoM reached both ways -- it produces the template and lists it as a
        by-product -- counts once, and so does a BoM naming the same component
        on two lines.
        """
        unit = self.env.ref("uom.product_uom_unit")
        finished = self.env["product.product"].create(
            {"name": "Count finished", "is_storable": True}
        )
        other = self.env["product.product"].create(
            {"name": "Count other", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Count component", "is_storable": True}
        )

        def bom(product, lines, byproducts=()):
            return self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "product_qty": 1.0,
                    "product_uom_id": unit.id,
                    "type": "normal",
                    "bom_line_ids": [
                        Command.create({"product_id": c.id, "product_qty": qty})
                        for c, qty in lines
                    ],
                    "byproduct_ids": [
                        Command.create(
                            {
                                "product_id": p.id,
                                "product_qty": 1.0,
                                "product_uom_id": unit.id,
                            }
                        )
                        for p in byproducts
                    ],
                }
            )

        bom(finished, [(component, 1.0)])
        bom(finished, [(component, 2.0)])
        # Lists `component` twice, and `finished` as a by-product.
        bom(other, [(component, 1.0), (component, 5.0)], byproducts=(finished,))
        self.env.invalidate_all()

        self.assertEqual(finished.product_tmpl_id.bom_count, 3)
        self.assertEqual(other.product_tmpl_id.bom_count, 1)
        self.assertEqual(component.product_tmpl_id.used_in_bom_count, 3)
        self.assertEqual(component.product_tmpl_id.bom_count, 0)

    def test_unbuild_without_bom_or_mo_is_refused(self):
        """mrp.unbuild.action_unbuild

        An unbuild order needs either a manufacturing order or a bill of
        materials to take the product apart into. With neither, the factor the
        moves are scaled by divided by an empty BoM's quantity and the user got
        a bare ZeroDivisionError.
        """
        product = self.env["product.product"].create(
            {"name": "Unbuild no BoM", "is_storable": True}
        )
        unbuild = self.env["mrp.unbuild"].create(
            {
                "product_id": product.id,
                "product_qty": 1.0,
                "product_uom_id": product.uom_id.id,
            }
        )
        self.assertFalse(unbuild.bom_id)
        self.assertFalse(unbuild.mo_id)
        # Stock it where this order will look, so `action_validate` gets past
        # its availability check and reaches the step under test.
        self.env["stock.quant"].create(
            {
                "location_id": unbuild.location_id.id,
                "product_id": product.id,
                "inventory_quantity": 10,
            }
        ).action_apply_inventory()
        with self.assertRaises(UserError):
            unbuild.action_validate()

    def test_show_allocation_without_warehouse_on_operation_type(self):
        """mrp.production._compute_show_allocation

        An operation type is not required to name a warehouse, and the
        operation-type form lets a user clear it (`force_save="1"`). The compute
        cached one location set per warehouse and then read that cache with
        `picking_type_id.warehouse_id.id`, which is `False` for such a type --
        `KeyError: False`, raised out of the `web_read` that opens the
        manufacturing order's form, since `show_allocation` is in its arch.
        """
        self.env.user.group_ids = [
            Command.link(self.env.ref("mrp.group_mrp_reception_report").id)
        ]
        finished, component = self.env["product.product"].create(
            [
                {"name": "Alloc finished", "is_storable": True},
                {"name": "Alloc component", "is_storable": True},
            ]
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1.0})
                ],
            }
        )
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        picking_type = warehouse.manu_type_id.copy(
            {"name": "Manufacturing (no warehouse)", "sequence_code": "MONOWH"}
        )
        picking_type.warehouse_id = False
        self.assertFalse(picking_type.warehouse_id)

        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "bom_id": bom.id,
                "product_qty": 1.0,
                "picking_type_id": picking_type.id,
            }
        )
        self.env.flush_all()
        production.invalidate_recordset()
        # The RPC the form issues, not just a Python read.
        self.assertFalse(
            production.web_read({"id": {}, "show_allocation": {}})[0]["show_allocation"]
        )

    def test_production_state_leaves_progress_when_nothing_is_consumed(self):
        """mrp.production._compute_state

        Ticking a component as consumed moves the order to `progress`. Removing
        the tick has to move it back: the branch chain used to fall through with
        nothing assigned, so the stored `progress` survived and the order could
        never return to `confirmed` from the interface.
        """
        production = self.generate_mo()[0]
        production.action_confirm()
        self.env.flush_all()
        self.assertEqual(production.state, "confirmed")

        production.move_raw_ids.picked = True
        self.env.flush_all()
        production.invalidate_recordset()
        self.assertEqual(production.state, "progress")

        production.move_raw_ids.picked = False
        production.qty_producing = 0
        self.env.flush_all()
        production.invalidate_recordset()
        self.assertEqual(production.state, "confirmed")

    def test_draft_production_is_not_confirmed_by_its_state_compute(self):
        """mrp.production._compute_state

        Guards the branch added for the test above: `draft` is the one state the
        compute cannot re-derive from the moves, so it must be carried over
        rather than turned into `confirmed`.
        """
        production = self.env["mrp.production"].create(
            {"product_id": self.product_4.id, "product_qty": 1.0}
        )
        self.env.flush_all()
        self.assertEqual(production.state, "draft")

        production.invalidate_recordset()
        self.env.add_to_compute(production._fields["state"], production)
        self.env.flush_all()
        self.assertEqual(production.state, "draft")

    def test_picking_type_is_computed_per_company(self):
        """mrp.production._compute_picking_type_id

        The compute builds a map keyed by company, but filled it from a
        `limit=1` search -- so it could only ever hold one company and every
        other order fell through to `False` on a required field. A batch create
        spanning two companies reached that as a NotNullViolation.
        """
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "Audit second company"})
        self.env["stock.warehouse"].create(
            {"name": "Audit WH B", "code": "AWB", "company_id": company_b.id}
        )
        self.env.user.company_ids = [Command.link(company_b.id)]
        env = self.env(
            context=dict(
                self.env.context, allowed_company_ids=[company_a.id, company_b.id]
            )
        )
        product = env["product.product"].create({"name": "Two-company product"})

        # An explicit name is what makes `create` leave the field to the
        # precompute instead of filling it itself.
        productions = env["mrp.production"].create(
            [
                {
                    "name": "AUDIT/0001",
                    "product_id": product.id,
                    "product_qty": 1.0,
                    "company_id": company_a.id,
                },
                {
                    "name": "AUDIT/0002",
                    "product_id": product.id,
                    "product_qty": 1.0,
                    "company_id": company_b.id,
                },
            ]
        )
        env.flush_all()
        for production in productions:
            self.assertTrue(production.picking_type_id)
            self.assertEqual(
                production.picking_type_id.warehouse_id.company_id,
                production.company_id,
            )

    def test_deleting_a_workorder_keeps_its_predecessors_other_edges(self):
        """mrp.workorder.unlink

        Splicing the deleted work order out of the dependency graph assigned a
        recordset to `needed_by_workorder_ids`, which *replaces* it: with B
        blocking both A and C, deleting A wiped B's successors and left C
        unblocked. Only work orders without an operation stay damaged -- the
        others are rebuilt by the `_action_confirm` at the end of `unlink` --
        which is exactly the case enterprise's "Add Work Order" wizard creates.
        """
        # A draft order: confirming one chains its work orders automatically,
        # and the point here is a graph the user shaped.
        production = self.env["mrp.production"].create(
            {"product_id": self.product_4.id, "product_qty": 1.0}
        )
        production.allow_workorder_dependencies = True
        workorder_a, workorder_b, workorder_c = self.env["mrp.workorder"].create(
            [
                {
                    "name": name,
                    "production_id": production.id,
                    "workcenter_id": self.workcenter_1.id,
                }
                for name in ("Manual A", "Manual B", "Manual C")
            ]
        )
        workorder_a.blocked_by_workorder_ids = [Command.set(workorder_b.ids)]
        workorder_c.blocked_by_workorder_ids = [Command.set(workorder_b.ids)]
        self.env.flush_all()
        self.assertEqual(workorder_b.needed_by_workorder_ids, workorder_a | workorder_c)

        workorder_a.unlink()
        self.env.flush_all()
        (workorder_b | workorder_c).invalidate_recordset()
        self.assertEqual(workorder_b.needed_by_workorder_ids, workorder_c)
        self.assertEqual(workorder_c.blocked_by_workorder_ids, workorder_b)

    def test_planned_workorders_may_be_rescheduled_onto_each_other(self):
        """mrp.workorder._plan_workorder

        Planning booked its `resource.reservation` in `hard` enforcement while
        every other reservation this model creates is `soft`, so moving a
        planned work order onto an occupied slot raised "already reserved
        during this time" instead of being reported as a conflict -- which is
        what `_get_conflicted_workorder_ids` and the work order popover exist
        to do.
        """
        finished, component = self.env["product.product"].create(
            [
                {"name": "Replan finished", "is_storable": True},
                {"name": "Replan component", "is_storable": True},
            ]
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1.0})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": "Replan operation",
                            "workcenter_id": self.workcenter_1.id,
                            "time_cycle_manual": 60,
                        }
                    )
                ],
            }
        )
        productions = self.env["mrp.production"].create(
            [
                {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0}
                for _ in range(2)
            ]
        )
        productions.button_plan()
        self.env.flush_all()
        first, second = productions[0].workorder_ids, productions[1].workorder_ids
        self.assertEqual(first.reservation_id.enforcement_mode, "soft")

        second.write({"date_start": first.date_start, "date_end": first.date_end})
        self.env.flush_all()
        self.assertEqual(second.date_start, first.date_start)
        # The overlap is reported, not refused.
        self.assertIn(second.id, first._get_conflicted_workorder_ids()[first.id])

    def test_manual_consumption_flag_is_a_boolean(self):
        """stock.move._determine_is_manual_consumption

        `bom_line and bom_line.operation_id` yields a recordset, and the value
        is written into a Boolean field.
        """
        Move = self.env["stock.move"]
        self.assertIs(
            Move._determine_is_manual_consumption(self.env["mrp.bom.line"]), False
        )
        bom = self.bom_1
        bom.operation_ids = [
            Command.create({"name": "Flag op", "workcenter_id": self.workcenter_1.id})
        ]
        bom.bom_line_ids[0].operation_id = bom.operation_ids[0]
        self.assertIs(Move._determine_is_manual_consumption(bom.bom_line_ids[0]), True)

    def test_variant_bom_counts_match_their_template_counterparts(self):
        """product.product._compute_bom_count / _compute_used_in_bom_count

        The `product.template` pair was batched into grouped queries and the
        `product.product` pair was left running one `search_count` per record.
        Beyond the query count, the two must agree on what they count.
        """
        finished, other, component = self.env["product.product"].create(
            [
                {"name": "Variant counts finished", "is_storable": True},
                {"name": "Variant counts other", "is_storable": True},
                {"name": "Variant counts component", "is_storable": True},
            ]
        )
        unit = self.env.ref("uom.product_uom_unit")
        self.env["mrp.bom"].create(
            [
                {
                    "product_tmpl_id": finished.product_tmpl_id.id,
                    "product_qty": 1.0,
                    "bom_line_ids": [
                        Command.create({"product_id": component.id, "product_qty": 1.0})
                    ],
                },
                {
                    "product_tmpl_id": finished.product_tmpl_id.id,
                    "product_id": finished.id,
                    "product_qty": 2.0,
                },
                {
                    "product_tmpl_id": other.product_tmpl_id.id,
                    "product_qty": 1.0,
                    "byproduct_ids": [
                        Command.create(
                            {
                                "product_id": finished.id,
                                "product_qty": 1.0,
                                "product_uom_id": unit.id,
                            }
                        )
                    ],
                    "bom_line_ids": [
                        Command.create(
                            {"product_id": component.id, "product_qty": 5.0}
                        ),
                        Command.create(
                            {"product_id": component.id, "product_qty": 7.0}
                        ),
                    ],
                },
            ]
        )
        self.env.invalidate_all()
        # Template BoM + variant BoM + the by-product BoM, counted once each.
        self.assertEqual(finished.bom_count, 3)
        self.assertEqual(finished.product_tmpl_id.bom_count, 3)
        # Two BoMs use it, one of them on two lines.
        self.assertEqual(component.used_in_bom_count, 2)
        self.assertEqual(component.product_tmpl_id.used_in_bom_count, 2)
        self.assertEqual(component.bom_count, 0)

    def _count_queries(self, callback, pattern):
        """Run `callback` and count the queries whose SQL matches `pattern`."""
        cursor = self.env.cr
        original = cursor.execute
        matched = []

        def spy(query, *args, **kwargs):
            if re.search(pattern, str(query), re.IGNORECASE):
                matched.append(query)
            return original(query, *args, **kwargs)

        cursor.execute = spy
        try:
            callback()
        finally:
            cursor.execute = original
        return len(matched)

    def test_orderpoint_bom_placeholder_does_not_scale_with_the_row_count(self):
        """stock.warehouse.orderpoint._get_default_boms

        `bom_id_placeholder` is a column of the Replenishment list, and its
        compute resolved the default BoM one orderpoint at a time -- a
        `_bom_find` search per row. `_bom_find` takes a recordset, so the whole
        list needs a bounded number of them.
        """
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        products = self.env["product.product"].create(
            [{"name": f"Placeholder {i}", "is_storable": True} for i in range(20)]
        )
        self.env["mrp.bom"].create(
            [
                {"product_tmpl_id": product.product_tmpl_id.id, "product_qty": 1.0}
                for product in products
            ]
        )
        orderpoints = self.env["stock.warehouse.orderpoint"].create(
            [
                {
                    "product_id": product.id,
                    "warehouse_id": warehouse.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "product_min_qty": 1.0,
                    "product_max_qty": 5.0,
                }
                for product in products
            ]
        )
        self.env.flush_all()

        def read_placeholders():
            orderpoints.invalidate_recordset(["bom_id_placeholder"])
            orderpoints.mapped("bom_id_placeholder")

        queries = self._count_queries(read_placeholders, r"\bmrp_bom\b")
        self.assertLessEqual(
            queries,
            4,
            "resolving the default BoM of %s orderpoints took %s mrp_bom queries;"
            " it must not scale with the number of rows" % (len(orderpoints), queries),
        )

    def test_variant_bom_counters_do_not_scale_with_the_record_count(self):
        """product.product._compute_bom_count / _compute_used_in_bom_count

        Both ran one `search_count` per record while their `product.template`
        counterparts were already grouped.
        """
        products = self.env["product.product"].create(
            [{"name": f"Counter {i}", "is_storable": True} for i in range(20)]
        )
        self.env["mrp.bom"].create(
            [
                {"product_tmpl_id": product.product_tmpl_id.id, "product_qty": 1.0}
                for product in products
            ]
        )
        self.env.flush_all()

        for field in ("bom_count", "used_in_bom_count"):

            def read_field(field=field):
                products.invalidate_recordset([field])
                products.mapped(field)

            queries = self._count_queries(read_field, r"\bmrp_bom")
            self.assertLessEqual(
                queries,
                3,
                "%s took %s mrp_bom queries for %s products"
                % (field, queries, len(products)),
            )
