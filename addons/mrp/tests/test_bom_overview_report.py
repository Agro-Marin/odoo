from odoo import Command, fields
from odoo.tests import Form, tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestBomOverviewReport(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env.ref("mrp.bom_overview_report")
        cls.data_layer = cls.env["report.mrp.report_bom_structure"]

    def _options(self, **extra):
        return self.report.with_context(
            active_model="mrp.bom", active_id=self.bom_1.id
        ).get_options({"selected_variant_id": self.report.id, **extra})

    def test_the_overview_opens_on_the_bom_of_the_context(self):
        options = self._options()
        self.assertEqual(options["bom_overview_bom_id"], self.bom_1.id)
        self.assertEqual(options["bom_overview_quantity"], self.bom_1.product_qty)

        lines = self.report._get_lines(options)
        self.assertEqual(lines[0]["name"], self.bom_1.product_id.display_name)

    def test_the_client_names_the_record_with_active_id_alone(self):
        options = self.report.with_context(active_id=self.bom_1.id).get_options(
            {"selected_variant_id": self.report.id}
        )
        self.assertEqual(
            options["bom_overview_bom_id"],
            self.bom_1.id,
            "the client action passes active_id and no active_model",
        )

    def test_every_component_of_the_data_layer_is_a_line_under_the_product(self):
        options = self._options()
        data = self.data_layer.with_context(
            warehouse_id=options["bom_overview_warehouse_id"]
        )._get_report_data(
            bom_id=self.bom_1.id, searchQty=options["bom_overview_quantity"]
        )
        lines = self.report._get_lines(options)
        names = [line["name"] for line in lines]
        for component in data["lines"]["components"]:
            self.assertIn(component["name"], names)
        self.assertTrue(
            all(line["parent_id"] == lines[0]["id"] for line in lines[1:])
            or len(lines) > 1
        )

    def test_the_quantity_the_reader_asks_for_drives_the_components(self):
        one = self._options(bom_overview_quantity=1)
        ten = self._options(bom_overview_quantity=10)
        self.assertEqual(ten["bom_overview_quantity"], 10)

        def component_quantities(options):
            return [
                line["columns"][0].get("no_format")
                for line in self.report._get_lines(options)[1:]
            ]

        for single, tenfold in zip(
            component_quantities(one), component_quantities(ten), strict=True
        ):
            if isinstance(single, (int, float)) and single:
                self.assertAlmostEqual(tenfold, single * 10)

    def test_the_cost_column_carries_the_bom_cost_of_the_data_layer(self):
        options = self._options()
        data = self.data_layer.with_context(
            warehouse_id=options["bom_overview_warehouse_id"]
        )._get_report_data(
            bom_id=self.bom_1.id, searchQty=options["bom_overview_quantity"]
        )
        summary = self.report._get_lines(options)[0]
        values = {
            column["expression_label"]: cell.get("no_format")
            for column, cell in zip(options["columns"], summary["columns"], strict=True)
        }
        self.assertEqual(values["bom_cost"], data["lines"]["bom_cost"])

    def test_the_forecast_columns_are_offered_and_start_out_hidden(self):
        options = self._options()
        labels = [column["expression_label"] for column in options["columns"]]
        self.assertEqual(labels, ["quantity", "bom_cost"])
        self.assertEqual(
            [column["name"] for column in options["optional_columns"]],
            [
                "Unit",
                "Free to Use / On Hand",
                "Status",
                "Availability",
                "Lead Time",
                "Route",
            ],
        )

        options = self._options(hidden_columns=[])
        self.assertIn(
            "availability",
            [column["expression_label"] for column in options["columns"]],
        )

    def _sub_assembly_chain(self):
        self.full_availability()
        self.warehouse_1.manufacture_steps = "pbm"
        self.warehouse_1.manufacture_pull_id.delay = 4
        self.warehouse_1.pbm_route_id.rule_ids.filtered(
            lambda rule: rule.location_dest_id == self.warehouse_1.pbm_loc_id
        ).delay = 1
        sub_assembly, sub_component, parent, parent_component = self.env[
            "product.product"
        ].create(
            [
                {
                    "name": "Lead sub-assembly",
                    "is_storable": True,
                    "route_ids": [Command.set(self.route_manufacture.ids)],
                },
                {"name": "Lead sub component", "is_storable": True},
                {
                    "name": "Lead parent",
                    "is_storable": True,
                    "route_ids": [Command.set(self.route_manufacture.ids)],
                },
                {"name": "Lead parent component", "is_storable": True},
            ]
        )
        for component in (sub_component, parent_component):
            self.env["stock.quant"]._update_available_quantity(
                component, self.warehouse_1.lot_stock_id, 100
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
                "produce_delay": 1,
                "bom_line_ids": [
                    Command.create({"product_id": sub_assembly.id, "product_qty": 1}),
                    Command.create(
                        {"product_id": parent_component.id, "product_qty": 1}
                    ),
                ],
            }
        )
        return sub_assembly, parent_bom

    def _structure(self, bom):
        return self.data_layer.with_context(
            warehouse_id=self.warehouse_1.id
        )._get_report_data(bom.id)["lines"]

    def test_lead_time_is_the_schedulers_everywhere(self):
        sub_assembly, parent_bom = self._sub_assembly_chain()
        delays, _description = self.warehouse_1.manufacture_pull_id.with_context(
            bypass_delay_description=True, global_horizon_days=0
        )._get_lead_days(sub_assembly)
        scheduler = delays["total_delay"]
        self.assertEqual(scheduler, 3 + 1 + 2, "produce + pbm pull + prepare")

        [sub_row] = [
            row
            for row in self._structure(parent_bom)["components"]
            if row["product_id"] == sub_assembly.id
        ]
        self.assertEqual(sub_row["lead_time"], scheduler)
        self.assertEqual(sub_row["manufacture_delay"], scheduler - 2)

        replenish = self.env["product.replenish"].new(
            {
                "product_id": sub_assembly.id,
                "product_tmpl_id": sub_assembly.product_tmpl_id.id,
                "warehouse_id": self.warehouse_1.id,
                "route_id": self.route_manufacture.id,
            }
        )
        self.assertEqual(
            (replenish.date_planned.date() - fields.Date.today()).days, scheduler
        )

    def test_simulated_availability_keeps_the_pull_rule_delays(self):
        _sub_assembly, parent_bom = self._sub_assembly_chain()
        without_operation = self._structure(parent_bom)
        parent_bom.operation_ids = [
            Command.create(
                {
                    "name": "Short",
                    "workcenter_id": self.workcenter_2.id,
                    "time_cycle_manual": 1,
                }
            )
        ]
        with_operation = self._structure(parent_bom)
        self.assertEqual(with_operation["availability_state"], "estimated")
        self.assertEqual(
            with_operation["availability_delay"],
            without_operation["availability_delay"],
            "a one-minute operation does not cut the pbm transfer out of the delay",
        )

    def test_manufacture_opens_the_variant_the_reader_chose(self):
        options = self._options()
        variant = self.product_7_2
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.product_7_template.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create({"product_id": self.product_2.id, "product_qty": 1})
                ],
            }
        )
        self.assertNotEqual(bom.product_tmpl_id.product_variant_id, variant)
        options.update(
            bom_overview_bom_id=bom.id,
            bom_overview_quantity=3,
            bom_overview_variant_id=variant.id,
        )
        action = self.env[
            "mrp.bom.overview.report.handler"
        ].action_manufacture_from_bom(options)
        production = Form(self.env["mrp.production"].with_context(action["context"]))
        self.assertEqual(production.product_id, variant)

    def test_open_route_opens_what_the_route_names(self):
        sub_assembly, parent_bom = self._sub_assembly_chain()
        handler = self.env["mrp.bom.overview.report.handler"]
        options = self.report.with_context(
            active_model="mrp.bom", active_id=parent_bom.id
        ).get_options({"selected_variant_id": self.report.id})
        options["bom_overview_warehouse_id"] = self.warehouse_1.id
        lines = self.report._get_lines(options)
        [sub_line] = [
            line for line in lines if line["name"] == sub_assembly.display_name
        ]
        [component_line] = [
            line for line in lines if line["name"] == "Lead parent component"
        ]
        self.assertEqual(
            {option["action"] for option in self._caret_options(component_line)},
            {"caret_option_open_record"},
            "a row with no route offers no route to open",
        )
        action = handler.caret_option_open_route(options, {"line_id": sub_line["id"]})
        self.assertEqual(
            (action["res_model"], action["res_id"]),
            ("mrp.bom", sub_assembly.bom_ids.id),
        )

    def _caret_options(self, line):
        return self.env["mrp.bom.overview.report.handler"]._caret_options_initializer()[
            line["caret_options"]
        ]

    def test_the_printed_overview_lists_every_component_and_operation(self):
        html, _content_type = self.env["ir.actions.report"]._render_qweb_html(
            "mrp.report_bom_structure", self.bom_2.ids
        )
        html = html.decode()
        for line in self.bom_2.bom_line_ids:
            self.assertIn(line.product_id.display_name, html)
        for operation in self.bom_2.operation_ids:
            self.assertIn(operation.name, html)
