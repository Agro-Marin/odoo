import re
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tests import Form, tagged

from .common import TestMrpCommon
from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestMrpAuditFixes(TestMrpCommon):
    def test_report_bom_structure_merges_duplicate_component_qty(self):
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
        self.assertAlmostEqual(
            merged[0]["base_bom_line_qty"],
            5.0,
            msg="Merged base_bom_line_qty must sum the two lines (2 + 3 = 5).",
        )
        self.assertAlmostEqual(merged[0]["quantity"], 5.0)

    def test_create_mo_with_non_create_finished_command_and_byproduct(self):
        final = self.env["product.product"].create(
            {"name": "Audit Final 2", "is_storable": True}
        )
        byproduct = self.env["product.product"].create(
            {"name": "Audit Byproduct", "is_storable": True}
        )
        picking_type = self.env["mrp.production"]._get_default_picking_type_id(
            self.env.company.id
        )

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
        converter = self.env["ir.qweb.field.monetary_opt"]
        options = {"display_currency": self.env.company.currency_id}
        self.assertEqual(converter.value_to_html(False, options), "")
        self.assertEqual(converter.value_to_html(None, options), "")
        self.assertIn("oe_currency_value", converter.value_to_html(0.0, options))
        self.assertIn("oe_currency_value", converter.value_to_html(12.5, options))

    def test_mo_overview_report_renders_with_unset_costs(self):
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
        op_c.blocked_by_operation_ids = [Command.set((op_a + op_b).ids)]
        self.assertEqual(op_c.blocked_by_operation_ids, op_a + op_b)

        other_bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1.0,
                "allow_operation_dependencies": True,
            }
        )
        op_a.bom_id = other_bom.id
        self.assertEqual(
            op_c.blocked_by_operation_ids,
            op_b,
            "Only the moved operation (A) may be removed; B must remain a blocker.",
        )

    def test_explode_detects_phantom_cycle(self):
        prod_a = self.env["product.product"].create(
            {"name": "Cycle A", "is_storable": True}
        )
        prod_b = self.env["product.product"].create(
            {"name": "Cycle B", "is_storable": True}
        )
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
        with self.assertRaises(ValidationError):
            bom_a.explode(prod_a, 1.0)

    def test_bom_rejects_product_uom_of_another_category(self):
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
        _production, workorders = self._audit_mo_with_two_workorders()
        start = datetime(2030, 1, 1, 8, 0, 0)
        workorders.write({"date_start": start, "date_end": start + timedelta(hours=1)})
        self.assertEqual(workorders[0].date_end, start + timedelta(minutes=60))
        self.assertEqual(workorders[1].date_end, start + timedelta(minutes=30))

    def test_workorder_write_keeps_per_record_duration(self):
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
        _production, workorders = self._audit_mo_with_two_workorders()
        vals = {
            "date_start": datetime(2030, 3, 1, 8, 0, 0),
            "date_end": datetime(2030, 3, 1, 9, 0, 0),
        }
        snapshot = dict(vals)
        workorders[1].write(vals)
        self.assertEqual(vals, snapshot)

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
        productions, _component, _unit = self._audit_two_productions()
        original = productions.product_id
        productions.action_confirm()
        other = self.env["product.product"].create(
            {"name": "Audit MO other", "is_storable": True}
        )
        productions.write({"product_id": other.id})
        self.assertEqual(productions.product_id, original)

    def test_production_write_does_not_mutate_caller_vals(self):
        productions, _component, _unit = self._audit_two_productions()
        productions.action_confirm()
        vals = {"product_id": productions[0].product_id.id, "priority": "1"}
        snapshot = dict(vals)
        productions.write(vals)
        self.assertEqual(vals, snapshot)

    def test_get_name_backorder_reads_its_own_group(self):
        self.assertEqual(
            self.env["mrp.production"]._get_name_backorder("WH/MO/00001-002", 3),
            "WH/MO/00001-003",
        )

    def test_autoprint_mass_generated_lots_without_label_format(self):
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
        self.assertTrue(report._has_bom_attachment(on_variant))
        self.assertFalse(
            report._has_bom_attachment(template=on_variant.product_tmpl_id)
        )
        self.assertTrue(report._has_bom_attachment(on_template))
        self.assertTrue(
            report._has_bom_attachment(template=on_template.product_tmpl_id)
        )
        self.assertFalse(report._has_bom_attachment(plain))
        self.assertFalse(report._has_bom_attachment(template=plain.product_tmpl_id))

    def test_bom_counts_are_deduplicated(self):
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
        bom(other, [(component, 1.0), (component, 5.0)], byproducts=(finished,))
        self.env.invalidate_all()

        self.assertEqual(finished.product_tmpl_id.bom_count, 3)
        self.assertEqual(other.product_tmpl_id.bom_count, 1)
        self.assertEqual(component.product_tmpl_id.used_in_bom_count, 3)
        self.assertEqual(component.product_tmpl_id.bom_count, 0)

    def test_unbuild_without_bom_or_mo_is_refused(self):
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
        self.assertFalse(
            production.web_read({"id": {}, "show_allocation": {}})[0]["show_allocation"]
        )

    def test_production_state_leaves_progress_when_nothing_is_consumed(self):
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
        self.assertIn(second.id, first._get_conflicted_workorder_ids()[first.id])

    def test_manual_consumption_flag_is_a_boolean(self):
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
        self.assertEqual(finished.bom_count, 3)
        self.assertEqual(finished.product_tmpl_id.bom_count, 3)
        self.assertEqual(component.used_in_bom_count, 2)
        self.assertEqual(component.product_tmpl_id.used_in_bom_count, 2)
        self.assertEqual(component.bom_count, 0)

    def _count_queries(self, callback, pattern):
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

    def test_live_duration_reports_a_running_timer(self):
        production = self.generate_mo()[0]
        workorder = self.env["mrp.workorder"].create(
            {
                "name": "Live duration",
                "production_id": production.id,
                "workcenter_id": self.workcenter_1.id,
            }
        )
        loss = self.env["mrp.workcenter.productivity.loss"].search(
            [("loss_type", "=", "productive")], limit=1
        )
        self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": workorder.id,
                "workcenter_id": self.workcenter_1.id,
                "loss_id": loss.id,
                "date_start": self.env.cr.now() - timedelta(minutes=30),
            }
        )
        self.env.flush_all()
        workorder.invalidate_recordset()

        self.assertAlmostEqual(workorder.duration_live, 30.0, delta=1.0)
        self.assertAlmostEqual(workorder.duration_live, workorder.get_duration())
        self.assertEqual(workorder.time_ids.duration, 0.0)

    def test_live_duration_matches_the_stored_one_when_nothing_runs(self):
        production = self.generate_mo()[0]
        workorder = self.env["mrp.workorder"].create(
            {
                "name": "Closed timer",
                "production_id": production.id,
                "workcenter_id": self.workcenter_1.id,
            }
        )
        loss = self.env["mrp.workcenter.productivity.loss"].search(
            [("loss_type", "=", "productive")], limit=1
        )
        ended = self.env.cr.now()
        self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": workorder.id,
                "workcenter_id": self.workcenter_1.id,
                "loss_id": loss.id,
                "date_start": ended - timedelta(minutes=12),
                "date_end": ended,
            }
        )
        self.env.flush_all()
        workorder.invalidate_recordset()

        self.assertAlmostEqual(workorder.duration, 12.0, delta=0.1)
        self.assertAlmostEqual(workorder.duration_live, workorder.duration)

    def test_live_duration_is_computed_for_the_whole_list_at_once(self):
        production = self.generate_mo()[0]
        workorders = self.env["mrp.workorder"].create(
            [
                {
                    "name": f"Batch live {index}",
                    "production_id": production.id,
                    "workcenter_id": self.workcenter_1.id,
                }
                for index in range(5)
            ]
        )
        self.env.flush_all()
        workorders.invalidate_recordset()
        self.assertEqual(workorders.mapped("duration_live"), [0.0] * 5)

    def test_mo_overview_rounds_costs_in_the_orders_own_currency(self):
        jpy = (
            self.env["res.currency"]
            .with_context(active_test=False)
            .search([("name", "=", "JPY")], limit=1)
        )
        jpy.active = True
        self.assertLess(
            jpy.decimal_places,
            self.env.company.currency_id.decimal_places,
            "this test needs a viewing currency coarser than the order's",
        )
        viewer_company = self.env["res.company"].create(
            {"name": "Coarse currency viewer", "currency_id": jpy.id}
        )
        self.env["stock.warehouse"].create(
            {"name": "CCV", "code": "CCV", "company_id": viewer_company.id}
        )
        self.env.user.company_ids = [Command.link(viewer_company.id)]

        finished, component = self.env["product.product"].create(
            [
                {"name": "Currency finished", "is_storable": True},
                {"name": "Currency component", "is_storable": True},
            ]
        )
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Currency workcenter", "costs_hour": 37.0}
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
                            "name": "Currency operation",
                            "workcenter_id": workcenter.id,
                            "time_cycle_manual": 17,
                        }
                    )
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1.0}
        )
        production.action_confirm()
        production.workorder_ids.unlink()
        self.env.flush_all()

        report = self.env["report.mrp.report_mo_overview"].with_company(viewer_company)
        self.assertEqual(report.env.company, viewer_company)
        bom_cost = report._get_report_data(production.id)["summary"]["bom_cost"]

        order_currency = production.company_id.currency_id
        self.assertAlmostEqual(bom_cost, order_currency.round(10.4833), places=2)
        self.assertNotAlmostEqual(bom_cost, 10.0, places=2)

    def test_split_wizard_bounds_the_batch_count_on_the_onchange_path(self):
        product = self.env["product.product"].create(
            {"name": "Split bound", "is_storable": True}
        )
        production = self.env["mrp.production"].create(
            {"product_id": product.id, "product_qty": 100000.0}
        )
        wizard = self.env["mrp.production.split"].create(
            {"production_id": production.id}
        )
        max_splits = wizard.MAX_SPLITS
        self.assertEqual(len(wizard.production_detailed_vals_ids), 1)

        with self.assertRaises(ValidationError), Form(wizard) as form:
            form.max_batch_size = 20.0
        self.assertEqual(len(wizard.production_detailed_vals_ids), 1)

        with Form(wizard) as form:
            form.max_batch_size = production.product_qty / max_splits
            self.assertEqual(form.num_splits, max_splits)
        self.assertEqual(len(wizard.production_detailed_vals_ids), max_splits)

    def test_delay_alert_search_answers_what_the_field_shows(self):
        component = self.env["product.product"].create(
            {"name": "Delay alert component", "is_storable": True},
        )
        finished = self.env["product.product"].create(
            {"name": "Delay alert finished", "is_storable": True},
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1}),
                ],
            },
        )
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "product_qty": 1, "bom_id": bom.id},
        )
        production.action_confirm()
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        upstream = self.env["stock.picking"].create(
            {
                "picking_type_id": warehouse.int_type_id.id,
                "move_ids": [
                    Command.create(
                        {"product_id": component.id, "product_uom_qty": 1},
                    ),
                ],
            },
        )
        upstream.action_confirm()
        production.move_raw_ids.move_orig_ids = [Command.set(upstream.move_ids.ids)]
        upstream.move_ids.date = datetime(2031, 12, 1)
        production.move_raw_ids.date = datetime(2030, 1, 1)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(production.date_delay_alert, datetime(2031, 12, 1))
        Production = self.env["mrp.production"]
        for operator, value, expected in (
            ("!=", False, True),
            (">", datetime(2031, 6, 1), True),
            ("<", datetime(2031, 6, 1), False),
            ("=", datetime(2031, 12, 1), True),
            ("=", datetime(2031, 1, 1), False),
        ):
            with self.subTest(operator=operator, value=value):
                self.assertEqual(
                    bool(
                        Production.search(
                            [
                                ("id", "=", production.id),
                                ("date_delay_alert", operator, value),
                            ],
                        )
                    ),
                    expected,
                    "the search must classify by the same rule the field shows",
                )

        self.assertTrue(
            Production.search(
                [
                    ("id", "=", production.id),
                    "|",
                    ("date_delay_alert", "!=", False),
                    ("is_delayed", "=", True),
                ],
            ),
            "the Late filter the search view ships must find a delayed order",
        )

    def _kit_with_one_component(self, on_hand):
        component = self.env["product.product"].create(
            {"name": "Audit Kit Component", "is_storable": True}
        )
        kit = self.env["product.product"].create(
            {"name": "Audit Kit", "is_storable": True}
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, on_hand
        )
        return kit, component

    def test_kit_quantities_are_readable_without_manufacturing_rights(self):
        kit, __ = self._kit_with_one_component(7.0)
        reader = mail_new_test_user(
            self.env,
            login="audit_kit_reader",
            name="Audit Kit Reader",
            groups="stock.group_stock_user",
        )
        self.assertFalse(
            reader.has_group("mrp.group_mrp_user"),
            "the reader must not carry manufacturing rights for this to measure "
            "anything",
        )

        self.assertEqual(
            kit.with_user(reader).qty_available,
            7.0,
            "a reader without manufacturing rights must get the kit's quantity, "
            "not an AccessError on mrp.bom",
        )

    def test_kit_component_quantities_still_obey_the_reader_record_rules(self):
        kit, component = self._kit_with_one_component(7.0)
        reader = mail_new_test_user(
            self.env,
            login="audit_kit_ruled_reader",
            name="Audit Kit Ruled Reader",
            groups="stock.group_stock_user",
        )
        self.env["ir.rule"].create(
            {
                "name": "Audit: no quant is visible",
                "model_id": self.env["ir.model"]._get_id("stock.quant"),
                "domain_force": "[(0, '=', 1)]",
                "groups": [Command.link(self.quick_ref("stock.group_stock_user").id)],
            }
        )

        self.assertEqual(
            component.with_user(reader).qty_available,
            0.0,
            "the rule must hide the component's own quantity, or this test "
            "cannot tell the two environments apart",
        )
        self.assertEqual(
            kit.with_user(reader).qty_available,
            0.0,
            "the kit's quantity is its components': elevating the BoM lookup "
            "must not elevate the components' quant reads",
        )

    def _audit_cancel_fixture(self, consumption="flexible", with_byproduct=False):
        unit = self.env.ref("uom.product_uom_unit")
        finished = self.env["product.product"].create(
            {"name": "Audit cancel finished", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Audit cancel component", "is_storable": True}
        )
        byproduct = self.env["product.product"].create(
            {"name": "Audit cancel byproduct", "is_storable": True}
        )
        bom_vals = {
            "product_tmpl_id": finished.product_tmpl_id.id,
            "product_qty": 1.0,
            "product_uom_id": unit.id,
            "type": "normal",
            "consumption": consumption,
            "bom_line_ids": [
                Command.create({"product_id": component.id, "product_qty": 1.0})
            ],
        }
        if with_byproduct:
            bom_vals["byproduct_ids"] = [
                Command.create(
                    {
                        "product_id": byproduct.id,
                        "product_qty": 1.0,
                        "product_uom_id": unit.id,
                    }
                )
            ]
        bom = self.env["mrp.bom"].create(bom_vals)
        location = self.env["stock.warehouse"].search([], limit=1).lot_stock_id
        self.env["stock.quant"]._update_available_quantity(component, location, 100)
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "product_qty": 2.0, "bom_id": bom.id}
        )
        production.action_confirm()
        production.action_assign()
        production.qty_producing = 1
        production._set_qty_producing()
        return production

    def test_cancelling_a_part_consumed_order_lands_on_cancel(self):
        production = self._audit_cancel_fixture()
        production.move_raw_ids.picked = True
        production.move_raw_ids._action_done()
        self.assertEqual(production.state, "progress")

        production.action_cancel()
        production.invalidate_recordset()
        self.assertEqual(
            production.state,
            "cancel",
            "every finished move is cancelled, so _compute_state decides cancel; "
            "_action_cancel used to write 'done' here and the write never ran",
        )

    def test_cancelling_leaves_a_produced_byproduct_order_done(self):
        production = self._audit_cancel_fixture(with_byproduct=True)
        byproduct_move = production.move_byproduct_ids
        byproduct_move.quantity = 1
        byproduct_move.picked = True
        byproduct_move._action_done()
        production.move_raw_ids.picked = True
        production.move_raw_ids._action_done()

        production.action_cancel()
        production.invalidate_recordset()
        self.assertEqual(
            production.state,
            "done",
            "not every finished move is cancelled, so _compute_state reaches its "
            "own done branch on its own -- this is the outcome the deleted block "
            "claimed to produce",
        )

    def test_cancelling_does_not_depend_on_the_boms_consumption(self):
        states = {}
        for consumption in ("flexible", "strict"):
            production = self._audit_cancel_fixture(consumption=consumption)
            production.move_raw_ids.picked = True
            production.move_raw_ids._action_done()
            production.action_cancel()
            production.invalidate_recordset()
            states[consumption] = production.state
        self.assertEqual(
            states["flexible"],
            states["strict"],
            "the deleted block only fired for flexible BoMs; if consumption ever "
            "changes the cancel outcome, it is a new rule and needs its own home",
        )

    def _audit_one_production(self):
        unit = self.env.ref("uom.product_uom_unit")
        finished = self.env["product.product"].create(
            {"name": "Audit depends finished", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Audit depends component", "is_storable": True}
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
            {"product_id": finished.id, "product_qty": 3.0, "bom_id": bom.id}
        )
        production.action_confirm()
        return production, component, unit

    def test_scrap_count_follows_its_own_scraps(self):
        production, component, unit = self._audit_one_production()
        self.assertEqual(production.scrap_count, 0)

        self.env["stock.scrap"].create(
            {
                "production_id": production.id,
                "product_id": component.id,
                "product_uom_id": unit.id,
                "scrap_qty": 1,
            }
        )

        self.assertEqual(len(production.scrap_ids), 1)
        self.assertEqual(
            production.scrap_count,
            1,
            "the compute declared no dependency at all, so the count stayed at "
            "its first reading for the whole transaction",
        )

    def test_transfer_count_follows_the_groups_moves(self):
        production, component, unit = self._audit_one_production()
        self.assertEqual(production.count_transfer_outgoing, 0)

        picking_type = self.env["stock.picking.type"].search(
            [("code", "in", ("internal", "outgoing"))], limit=1
        )
        self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": production.location_src_id.id,
                "location_dest_id": production.location_dest_id.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": component.id,
                            "product_uom_qty": 1,
                            "product_uom_id": unit.id,
                            "location_id": production.location_src_id.id,
                            "location_dest_id": production.location_dest_id.id,
                            "production_group_id": production.production_group_id.id,
                        }
                    )
                ],
            }
        )

        self.assertEqual(
            production.count_transfer_outgoing,
            1,
            "the compute depended on `state`, which no part of it reads, so a "
            "picking appearing in the group never invalidated it",
        )

    def test_availability_follows_its_moves_without_borrowing_reservation_state(self):
        production, _component, _unit = self._audit_one_production()
        self.assertEqual(production.components_availability_state, "unavailable")

        production.move_raw_ids.product_uom_qty = 0
        self.assertEqual(
            production.components_availability_state,
            "available",
            "the body reads move.state and move.product_qty; it used to reach "
            "them only through reservation_state's own dependency list",
        )

    def _audit_availability_population(self):
        unit = self.env.ref("uom.product_uom_unit")
        location = self.env["stock.warehouse"].search([], limit=1).lot_stock_id
        start = datetime(2026, 9, 15, 8, 0, 0)
        made = {}
        for tag, stocked, incoming_days in (
            ("avail", True, None),
            ("short", False, None),
            ("late", False, 20),
            ("soon", False, -5),
        ):
            component = self.env["product.product"].create(
                {"name": "Audit avail %s c" % tag, "is_storable": True}
            )
            finished = self.env["product.product"].create(
                {"name": "Audit avail %s f" % tag, "is_storable": True}
            )
            if stocked:
                self.env["stock.quant"]._update_available_quantity(
                    component, location, 100
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
                {
                    "product_id": finished.id,
                    "product_qty": 2.0,
                    "bom_id": bom.id,
                    "date_start": start,
                }
            )
            production.action_confirm()
            if stocked:
                production.action_assign()
            if incoming_days is not None:
                incoming = self.env["stock.picking.type"].search(
                    [("code", "=", "incoming")], limit=1
                )
                self.env["stock.move"].create(
                    {
                        "product_id": component.id,
                        "product_uom_qty": 100,
                        "product_uom_id": unit.id,
                        "location_id": self.env.ref(
                            "stock.stock_location_suppliers"
                        ).id,
                        "location_dest_id": location.id,
                        "picking_type_id": incoming.id,
                        "date": start + timedelta(days=incoming_days),
                    }
                )._action_confirm()
            made[tag] = production
        return made

    def _availability_state_by_scan(self, value):
        """What _search_components_availability_state did before it pre-filtered."""
        open_orders = self.env["mrp.production"].search(
            [("state", "in", ("confirmed", "progress", "to_close"))]
        )
        return set(
            open_orders.filtered(lambda p: p.components_availability_state in value).ids
        )

    def test_availability_search_matches_a_full_scan_for_every_state(self):
        made = self._audit_availability_population()
        self.assertEqual(
            {tag: p.components_availability_state for tag, p in made.items()},
            {
                "avail": "available",
                "short": "unavailable",
                "late": "late",
                "soon": "expected",
            },
            "the fixture must cover all four states or the comparison is vacuous",
        )

        production = self.env["mrp.production"]
        for value in (
            ["available"],
            ["unavailable"],
            ["late"],
            ["expected"],
            ["available", "late"],
            ["unavailable", "expected"],
            ["available", "unavailable", "late", "expected"],
        ):
            self.assertEqual(
                set(
                    production.search(
                        [("components_availability_state", "in", value)]
                    ).ids
                ),
                self._availability_state_by_scan(value),
                "the SQL pre-filter changed the answer for %s" % value,
            )

    def test_availability_search_skips_the_fully_reserved_orders(self):
        made = self._audit_availability_population()
        production = self.env["mrp.production"]
        candidates = production.search(
            production._components_availability_open_domain()
            & Domain(
                "move_raw_ids",
                "any",
                production._components_availability_unsettled_move_domain(),
            )
        )
        self.assertNotIn(
            made["avail"],
            candidates,
            "a fully reserved order can produce neither a shortage nor a forecast "
            "date, so it must never reach the Python compute",
        )
        for tag in ("short", "late", "soon"):
            self.assertIn(made[tag], candidates)

    def _audit_byproduct_fixture(self):
        unit = self.env.ref("uom.product_uom_unit")
        finished = self.env["product.product"].create(
            {"name": "Audit byp finished", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Audit byp component", "is_storable": True}
        )
        byproduct = self.env["product.product"].create(
            {"name": "Audit byp byproduct", "is_storable": True}
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
        return finished, byproduct, bom, unit

    def test_writing_both_move_keys_keeps_the_byproduct(self):
        finished, byproduct, bom, unit = self._audit_byproduct_fixture()
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "product_qty": 1.0, "bom_id": bom.id}
        )

        production.write(
            {
                "move_finished_ids": [
                    Command.update(
                        production.move_finished_ids[0].id, {"product_uom_qty": 2}
                    )
                ],
                "move_byproduct_ids": [
                    Command.create(
                        {
                            "product_id": byproduct.id,
                            "product_uom_qty": 1,
                            "product_uom_id": unit.id,
                        }
                    )
                ],
            }
        )

        self.assertIn(
            byproduct,
            production.move_finished_ids.product_id,
            "the merge used to be gated on bom_id also being in vals; without it "
            "the byproduct command was dropped and no stock.move was ever created",
        )
        self.assertTrue(
            self.env["stock.move"].search_count(
                [
                    ("product_id", "=", byproduct.id),
                    ("production_id", "=", production.id),
                ]
            )
        )

    def test_writing_both_move_keys_matches_creating_with_both(self):
        finished, byproduct, bom, unit = self._audit_byproduct_fixture()

        def byproduct_command():
            return Command.create(
                {
                    "product_id": byproduct.id,
                    "product_uom_qty": 1,
                    "product_uom_id": unit.id,
                }
            )

        created = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "product_qty": 1.0,
                "bom_id": bom.id,
                "move_finished_ids": [
                    Command.create(
                        {
                            "product_id": finished.id,
                            "product_uom_qty": 1,
                            "product_uom_id": unit.id,
                        }
                    )
                ],
                "move_byproduct_ids": [byproduct_command()],
            }
        )
        written = self.env["mrp.production"].create(
            {"product_id": finished.id, "product_qty": 1.0, "bom_id": bom.id}
        )
        written.write({"move_byproduct_ids": [byproduct_command()]})

        self.assertEqual(
            sorted(created.move_finished_ids.product_id.mapped("name")),
            sorted(written.move_finished_ids.product_id.mapped("name")),
            "create() and write() must fold the byproduct key the same way",
        )

    def test_writing_product_id_on_a_mixed_set_still_reaches_the_draft_orders(self):
        productions, _component, _unit = self._audit_two_productions()
        draft, confirmed = productions[0], productions[1]
        confirmed.action_confirm()
        original = confirmed.product_id
        other = self.env["product.product"].create(
            {"name": "Audit mixed other", "is_storable": True}
        )

        productions.write({"product_id": other.id})

        self.assertEqual(
            draft.product_id,
            other,
            "a draft order used to lose its product change because a confirmed "
            "sibling was in the same recordset",
        )
        self.assertEqual(confirmed.product_id, original)

    def test_every_path_agrees_on_the_orders_production_location(self):
        unit = self.env.ref("uom.product_uom_unit")
        company = self.env.company
        finished_location = self.env["stock.location"].create(
            {"name": "Audit prod FIN", "usage": "production", "company_id": company.id}
        )
        component_location = self.env["stock.location"].create(
            {"name": "Audit prod COMP", "usage": "production", "company_id": company.id}
        )
        finished = self.env["product.product"].create(
            {"name": "Audit prodloc finished", "is_storable": True}
        )
        component = self.env["product.product"].create(
            {"name": "Audit prodloc component", "is_storable": True}
        )
        finished.with_company(company).property_stock_production = finished_location
        component.with_company(company).property_stock_production = component_location
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
            {"product_id": finished.id, "product_qty": 2.0, "bom_id": bom.id}
        )
        expected = production.production_location_id
        self.assertEqual(expected, finished_location)

        raw_move = production.move_raw_ids
        self.assertEqual(raw_move.location_dest_id, expected)
        self.assertEqual(production.move_finished_ids.location_id, expected)
        self.assertEqual(
            production._get_move_raw_values(
                component, 1.0, unit, bom_line=bom.bom_line_ids[0]
            )["location_dest_id"],
            expected.id,
            "the vals builder used to spell this as the finished product's own "
            "property_stock_production, with no company fallback",
        )

        # the compute, which is what an unsaved form row shows and what a move
        # linked to the order after the fact gets
        linked = self.env["stock.move"].create(
            {
                "product_id": component.id,
                "product_uom_qty": 1,
                "product_uom_id": unit.id,
                "location_id": production.location_src_id.id,
                "location_dest_id": production.location_src_id.id,
                "company_id": company.id,
            }
        )
        linked.write({"raw_material_production_id": production.id})
        self.assertEqual(
            linked.location_dest_id,
            expected,
            "the compute used to answer with the component's production location, "
            "which disagreed with everything that actually got saved",
        )
