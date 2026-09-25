import gc
import math
from datetime import date, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestMoOverviewReport(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref("mrp.mo_overview_section")
        cls.production = cls.env["mrp.production"].create(
            {
                "product_id": cls.product_4.id,
                "product_uom_id": cls.product_4.uom_id.id,
                "product_qty": 5.0,
                "bom_id": cls.bom_1.id,
            }
        )
        cls.production.action_confirm()

    def _options(self, **extra):
        return self.report.with_context(
            active_model="mrp.production", active_id=self.production.id
        ).get_options({"selected_variant_id": self.report.id, **extra})

    def _lines(self, options):
        return self.report._get_lines(options)

    def test_the_overview_opens_on_the_manufacturing_order_of_the_context(self):
        options = self._options()
        self.assertEqual(
            options["mo_overview_production_id"],
            self.production.id,
            "the client action passes the MO through the context",
        )
        lines = self._lines(options)
        self.assertEqual(lines[0]["name"], self.production.product_id.display_name)

    def test_every_component_of_the_data_layer_is_a_line(self):
        options = self._options()
        data = self.env["report.mrp.report_mo_overview"]._get_report_data(
            self.production.id
        )
        names = [line["name"] for line in self._lines(options)]
        for component in data["components"]:
            self.assertIn(component["summary"]["name"], names)

    def test_the_summary_line_carries_the_costs_of_the_data_layer(self):
        options = self._options()
        data = self.env["report.mrp.report_mo_overview"]._get_report_data(
            self.production.id
        )
        summary_line = self._lines(options)[0]
        values = {
            column["expression_label"]: cell.get("no_format")
            for column, cell in zip(
                options["columns"], summary_line["columns"], strict=True
            )
        }
        self.assertEqual(values["quantity"], data["summary"]["quantity"])
        self.assertEqual(values["mo_cost"], data["summary"]["mo_cost"])
        self.assertEqual(values["bom_cost"], data["summary"]["bom_cost"])

    def test_the_cost_columns_the_reader_switched_off_are_absent(self):
        options = self._options()
        labels = [column["expression_label"] for column in options["columns"]]
        self.assertIn("mo_cost", labels)
        self.assertNotIn("real_cost", labels, "real cost starts out hidden")

        mo_cost_column = self.env.ref("mrp.mo_overview_report_column_mo_cost")
        options = self._options(hidden_columns=[mo_cost_column.id])
        self.assertNotIn(
            "mo_cost", [column["expression_label"] for column in options["columns"]]
        )
        self.assertTrue(
            all(
                len(line["columns"]) == len(options["columns"])
                for line in self._lines(options)
            )
        )

    def test_the_total_lines_state_the_unit_cost(self):
        options = self._options()
        data = self.env["report.mrp.report_mo_overview"]._get_report_data(
            self.production.id
        )
        total_lines = [
            line for line in self._lines(options) if line.get("class") == "total"
        ]
        self.assertEqual([line["name"] for line in total_lines], ["Unit Cost"])
        values = {
            column["expression_label"]: cell.get("no_format")
            for column, cell in zip(
                options["columns"], total_lines[0]["columns"], strict=True
            )
        }
        self.assertEqual(values["mo_cost"], data["extras"]["unit_mo_cost"])

    def test_the_overview_is_one_section_of_the_manufacturing_report(self):
        root = self.env.ref("mrp.mo_overview_report")
        self.assertEqual(
            root.section_report_ids,
            self.report + self.env.ref("mrp.mo_cost_breakdown_section"),
        )
        options = root.with_context(
            active_model="mrp.production", active_id=self.production.id
        ).get_options({"selected_variant_id": root.id})
        self.assertEqual(
            [section["name"] for section in options["sections"]],
            ["Overview", "Cost Breakdown"],
        )

    def test_the_cost_breakdown_section_mirrors_the_data_layer(self):
        breakdown = self.env.ref("mrp.mo_cost_breakdown_section")
        options = breakdown.with_context(
            active_model="mrp.production", active_id=self.production.id
        ).get_options({"selected_variant_id": breakdown.id})
        data = self.env["report.mrp.report_mo_overview"]._get_report_data(
            self.production.id
        )
        self.assertEqual(
            [line["name"] for line in breakdown._get_lines(options)],
            [row["name"] for row in data["cost_breakdown"]],
        )

    def test_an_operation_added_after_confirmation_is_costed_once(self):
        report = self.env["report.mrp.report_mo_overview"]
        before = report._get_report_data(self.production.id)["summary"]["bom_cost"]
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Costed", "costs_hour": 100, "time_start": 0, "time_stop": 0}
        )
        self.bom_1.operation_ids = [
            Command.create(
                {
                    "name": "late",
                    "workcenter_id": workcenter.id,
                    "time_cycle_manual": 60,
                }
            )
        ]
        after = report._get_report_data(self.production.id)["summary"]["bom_cost"]
        cycles = math.ceil(
            self.production.product_uom_id._get_quantity_in_unit(
                self.production.product_qty, self.bom_1.product_uom_id, round=False
            )
            / self.bom_1.product_qty
        )
        self.assertAlmostEqual(after - before, cycles * 100)

    def test_a_component_added_after_confirmation_is_costed_in_the_bom_unit(self):
        report = self.env["report.mrp.report_mo_overview"]
        before = report._get_report_data(self.production.id)["summary"]["bom_cost"]
        component = self.env["product.product"].create(
            {"name": "Late component", "is_storable": True, "standard_price": 10}
        )
        self.bom_1.bom_line_ids = [
            Command.create({"product_id": component.id, "product_qty": 1})
        ]
        after = report._get_report_data(self.production.id)["summary"]["bom_cost"]
        batches = (
            self.production.product_uom_id._get_quantity_in_unit(
                self.production.product_qty, self.bom_1.product_uom_id, round=False
            )
            / self.bom_1.product_qty
        )
        self.assertAlmostEqual(after - before, round(10 * batches, 2))

    def _stocked_production(self, components, stocked=True):
        products = self.env["product.product"].create(
            [
                {"name": f"Overview component {index}", "is_storable": True}
                for index in range(components)
            ]
        )
        finished = self.env["product.product"].create(
            {"name": f"Overview finished {components}", "is_storable": True}
        )
        if stocked:
            for product in products:
                self.env["stock.quant"]._update_available_quantity(
                    product, self.warehouse_1.lot_stock_id, 100
                )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": product.id, "product_qty": 1})
                    for product in products
                ],
            }
        )
        return self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "bom_id": bom.id,
                "product_qty": 1,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )

    def _origin_move_statements(self, production):
        self.env.flush_all()
        self.env.invalidate_all()
        self.env.registry.clear_all_caches()
        gc.collect()
        cursor_class = type(self.env.cr)
        with patch.object(
            cursor_class, "execute", autospec=True, side_effect=cursor_class.execute
        ) as execute:
            self.env["report.mrp.report_mo_overview"]._get_report_data(production.id)
        return sum(
            "stock_move_move_rel" in str(getattr(call.args[1], "code", call.args[1]))
            for call in execute.call_args_list
        )

    def test_the_origin_moves_are_read_once_for_every_raw_move(self):
        small = self._stocked_production(3)
        large = self._stocked_production(12)
        self.assertEqual(
            self._origin_move_statements(large),
            self._origin_move_statements(small),
        )

    def test_component_costs_are_read_in_the_company_of_the_order(self):
        viewer_company = self.env.company
        order_company = self.env["res.company"].create({"name": "Order company"})
        self.env.user.company_ids = [Command.link(order_company.id)]
        order_warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", order_company.id)], limit=1
        )
        component, finished = self.env["product.product"].create(
            [
                {"name": "Shared component", "is_storable": True},
                {"name": "Order company product", "is_storable": True},
            ]
        )
        component.with_company(viewer_company).standard_price = 10.0
        component.with_company(order_company).standard_price = 100.0
        bom = (
            self.env["mrp.bom"]
            .with_company(order_company)
            .create(
                {
                    "product_tmpl_id": finished.product_tmpl_id.id,
                    "company_id": order_company.id,
                    "product_qty": 1,
                    "bom_line_ids": [
                        Command.create({"product_id": component.id, "product_qty": 1})
                    ],
                }
            )
        )
        production = (
            self.env["mrp.production"]
            .with_company(order_company)
            .create(
                {
                    "product_id": finished.id,
                    "bom_id": bom.id,
                    "product_qty": 1,
                    "picking_type_id": order_warehouse.manu_type_id.id,
                }
            )
        )
        production.action_confirm()

        report = self.env["report.mrp.report_mo_overview"].with_context(
            allowed_company_ids=[viewer_company.id, order_company.id]
        )
        self.assertEqual(report.env.company, viewer_company)
        [component_data] = report._get_report_data(production.id)["components"]
        summary = component_data["summary"]
        self.assertEqual(
            (summary["unit_cost"], summary["mo_cost"], summary["bom_cost"]),
            (100.0, 100.0, 100.0),
            "the order's company prices its components, not the viewer's",
        )
        [to_order] = [
            line["summary"]
            for line in component_data["replenishments"]
            if line["summary"]["model"] == "to_order"
        ]
        self.assertEqual(to_order["mo_cost"], 100.0)

    def test_the_cost_breakdown_divides_by_the_quantity_produced(self):
        component, finished, byproduct = self.env["product.product"].create(
            [
                {"name": "Breakdown component", "is_storable": True},
                {"name": "Breakdown finished", "is_storable": True},
                {"name": "Breakdown byproduct", "is_storable": True},
            ]
        )
        component.standard_price = 10.0
        self.env["stock.quant"]._update_available_quantity(
            component, self.warehouse_1.lot_stock_id, 100
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
                "byproduct_ids": [
                    Command.create(
                        {
                            "product_id": byproduct.id,
                            "product_qty": 1,
                            "cost_share": 10,
                        }
                    )
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "bom_id": bom.id,
                "product_qty": 10,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        production.qty_producing = 12
        production.move_raw_ids.write({"quantity": 12, "picked": True})
        production.with_context(skip_consumption=True).button_mark_done()
        self.assertEqual(production.state, "done")

        data = self.env["report.mrp.report_mo_overview"]._get_report_data(production.id)
        finished_line = data["cost_breakdown"][0]
        self.assertAlmostEqual(
            finished_line["unit_avg_total_cost"],
            data["extras"]["unit_real_cost"],
            msg="108 over the 12 produced, not over the 10 planned",
        )
        self.assertAlmostEqual(finished_line["unit_avg_total_cost"], 9.0)

    def test_to_order_receipt_is_the_schedulers_lead_time(self):
        self.warehouse_1.manufacture_pull_id.delay = 4
        sub_assembly, sub_component, parent = self.env["product.product"].create(
            [
                {
                    "name": "Lead sub-assembly",
                    "is_storable": True,
                    "route_ids": [Command.set(self.route_manufacture.ids)],
                },
                {"name": "Lead sub component", "is_storable": True},
                {"name": "Lead parent", "is_storable": True},
            ]
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": sub_assembly.product_tmpl_id.id,
                "product_qty": 1,
                "produce_delay": 3,
                "days_to_prepare_mo": 2,
                "bom_line_ids": [
                    Command.create({"product_id": sub_component.id, "product_qty": 1})
                ],
            }
        )
        parent_bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": parent.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": sub_assembly.id, "product_qty": 1})
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": parent.id,
                "bom_id": parent_bom.id,
                "product_qty": 1,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        delays, _description = self.warehouse_1.manufacture_pull_id.with_context(
            bypass_delay_description=True, global_horizon_days=0
        )._get_lead_days(sub_assembly)

        data = self.env["report.mrp.report_mo_overview"]._get_report_data(production.id)
        [to_order] = [
            line["summary"]
            for component in data["components"]
            for line in component["replenishments"]
            if line["summary"]["model"] == "to_order"
        ]
        self.assertEqual(
            (to_order["receipt"]["date"].date() - date.today()).days,
            delays["total_delay"],
            "the scheduler counts the days to prepare the order, not the rule delay",
        )

    def test_a_done_operation_costs_what_the_work_order_posts(self):
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Costly", "costs_hour": 6000, "time_start": 0, "time_stop": 0}
        )
        finished = self.env["product.product"].create(
            {"name": "Timed finished", "is_storable": True}
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1,
                "operation_ids": [
                    Command.create(
                        {
                            "name": "Timed",
                            "workcenter_id": workcenter.id,
                            "time_cycle_manual": 10,
                        }
                    )
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": finished.id,
                "bom_id": bom.id,
                "product_qty": 1,
                "picking_type_id": self.warehouse_1.manu_type_id.id,
            }
        )
        production.action_confirm()
        production.qty_producing = 1
        production.button_mark_done()
        self.assertEqual(production.state, "done")
        workorder = production.workorder_ids
        start = fields.Datetime.now() - timedelta(hours=1)
        workorder.time_ids.unlink()
        self.env["mrp.workcenter.productivity"].create(
            {
                "workorder_id": workorder.id,
                "workcenter_id": workcenter.id,
                "loss_id": self.env.ref("mrp.block_reason7").id,
                "date_start": start,
                "date_end": start + timedelta(minutes=10, milliseconds=300),
            }
        )

        [operation] = self.env["report.mrp.report_mo_overview"]._get_report_data(
            production.id
        )["operations"]["details"]
        self.assertEqual(
            operation["real_cost"],
            production.company_id.currency_id.round(workorder._get_cost()),
            "the overview and the valuation read the same minutes",
        )
