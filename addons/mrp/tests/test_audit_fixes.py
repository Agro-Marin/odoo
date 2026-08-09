# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import ValidationError
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
