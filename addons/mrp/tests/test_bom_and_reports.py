from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestBomAndReports(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mo_overview = cls.env["report.mrp.report_mo_overview"]
        cls.bom_structure = cls.env["report.mrp.report_bom_structure"]

    def _storable(self, name, **values):
        return self.env["product.product"].create(
            {"name": name, "is_storable": True, **values}
        )

    def _bom(self, product, lines, **values):
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": component.id, "product_qty": qty, **extra}
                    )
                    for component, qty, extra in lines
                ],
                **values,
            }
        )

    def _no_variant_template(self, *attribute_names, display_type="radio"):
        template = self.env["product.template"].create(
            {"name": "Configurable", "is_storable": True}
        )
        values_by_attribute = []
        for name in attribute_names:
            attribute = self.env["product.attribute"].create(
                {
                    "name": name,
                    "create_variant": "no_variant",
                    "display_type": display_type,
                    "value_ids": [
                        Command.create({"name": f"{name}-1"}),
                        Command.create({"name": f"{name}-2"}),
                    ],
                }
            )
            line = self.env["product.template.attribute.line"].create(
                {
                    "product_tmpl_id": template.id,
                    "attribute_id": attribute.id,
                    "value_ids": [Command.set(attribute.value_ids.ids)],
                }
            )
            values_by_attribute.append(line.product_template_value_ids)
        return template, values_by_attribute

    def _mo_component(self, data, product):
        return next(
            component["summary"]
            for component in data["components"]
            if component["summary"]["product_id"] == product.id
        )

    def test_mo_overview_prices_a_kit_component_at_the_kit_demand(self):
        finished = self._storable("Finished")
        kit = self.env["product.product"].create({"name": "Kit"})
        component = self._storable("Component", standard_price=10)
        bom = self._bom(finished, [(kit, 4, {})])
        self._bom(kit, [(component, 3, {})], type="phantom", product_qty=2)
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1}
        )
        production.action_confirm()
        self.assertEqual(production.move_raw_ids.product_uom_qty, 6)

        data = self.mo_overview._get_report_data(production.id)
        row = self._mo_component(data, component)
        self.assertEqual(row["mo_cost"], 60)
        self.assertEqual(
            row["bom_cost"],
            60,
            "four kits of which two need three components are six components",
        )
        self.assertFalse(row["mo_cost_decorator"])
        self.assertEqual(data["summary"]["bom_cost"], 60)

    def test_mo_overview_follows_the_kit_the_order_exploded(self):
        finished = self._storable("Finished")
        component = self._storable("Component", standard_price=10)
        manufactured_part = self._storable("Manufactured Part", standard_price=1)
        dual = self._storable("Dual", standard_price=100)
        bom = self._bom(finished, [(dual, 1, {})])
        self._bom(dual, [(manufactured_part, 1, {})], sequence=1)
        self._bom(dual, [(component, 2, {})], type="phantom", sequence=2)
        production = self.env["mrp.production"].create(
            {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1}
        )
        production.action_confirm()
        self.assertEqual(production.move_raw_ids.product_id, component)

        data = self.mo_overview._get_report_data(production.id)
        self.assertEqual(
            data["summary"]["bom_cost"],
            20,
            "the kit line is exploded into its components, not missing from the order",
        )

    def test_a_no_variant_by_product_counts_in_the_cost_share(self):
        template, [values] = self._no_variant_template("Finish")
        first, second = (self._storable(name) for name in ("First", "Second"))
        component = self._storable("Component")
        with self.assertRaisesRegex(ValidationError, "cannot exceed 100"):
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": template.id,
                    "bom_line_ids": [Command.create({"product_id": component.id})],
                    "byproduct_ids": [
                        Command.create({"product_id": first.id, "cost_share": 60}),
                        Command.create(
                            {
                                "product_id": second.id,
                                "cost_share": 60,
                                "bom_product_template_attribute_value_ids": [
                                    Command.link(values[0].id)
                                ],
                            }
                        ),
                    ],
                }
            )

    def test_exclusive_no_variant_by_products_share_the_cost_separately(self):
        template, [values] = self._no_variant_template("Finish")
        first, second = (self._storable(name) for name in ("First", "Second"))
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": template.id,
                "byproduct_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "cost_share": 60,
                            "bom_product_template_attribute_value_ids": [
                                Command.link(value.id)
                            ],
                        }
                    )
                    for product, value in ((first, values[0]), (second, values[1]))
                ],
            }
        )
        self.assertEqual(len(bom.byproduct_ids), 2)

    def test_multi_choice_no_variant_by_products_add_up(self):
        template, [values] = self._no_variant_template("Extras", display_type="multi")
        first, second = (self._storable(name) for name in ("First", "Second"))
        with self.assertRaisesRegex(ValidationError, "cannot exceed 100"):
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": template.id,
                    "byproduct_ids": [
                        Command.create(
                            {
                                "product_id": product.id,
                                "cost_share": 60,
                                "bom_product_template_attribute_value_ids": [
                                    Command.link(value.id)
                                ],
                            }
                        )
                        for product, value in ((first, values[0]), (second, values[1]))
                    ],
                }
            )

    def test_a_no_variant_component_takes_part_in_the_cycle_check(self):
        template, [values] = self._no_variant_template("Finish")
        finished = template.product_variant_id
        part = self._storable("Part")
        self._bom(
            finished,
            [
                (
                    part,
                    1,
                    {
                        "bom_product_template_attribute_value_ids": [
                            Command.link(values[0].id)
                        ]
                    },
                )
            ],
        )
        with self.assertRaisesRegex(ValidationError, "cycle"):
            self._bom(part, [(finished, 1, {})])

    def test_a_line_on_two_no_variant_attributes_needs_both(self):
        template, [finish, size] = self._no_variant_template("Finish", "Size")
        finished = template.product_variant_id
        both, plain = self._storable("Both"), self._storable("Plain")
        bom = self._bom(
            finished,
            [
                (plain, 1, {}),
                (
                    both,
                    1,
                    {
                        "bom_product_template_attribute_value_ids": [
                            Command.link(finish[0].id),
                            Command.link(size[0].id),
                        ]
                    },
                ),
            ],
        )

        def components(never_values):
            _boms, lines = bom._explode(
                finished, 1, never_attribute_values=never_values
            )
            return self.env["product.product"].union(
                *(line.product_id for line, _data in lines)
            )

        self.assertEqual(components(finish[0] | size[1]), plain)
        self.assertEqual(components(finish[1] | size[0]), plain)
        self.assertEqual(components(finish[0] | size[0]), plain | both)

    def _bom_overview(self, bom):
        report = self.env.ref("mrp.bom_overview_report")
        options = report.with_context(
            active_model="mrp.bom", active_id=bom.id
        ).get_options({"selected_variant_id": report.id})
        return options, report._get_lines(options)

    def test_bom_overview_operation_and_by_product_rows_are_distinct(self):
        finished = self._storable("Finished")
        component, byproduct = self._storable("Component"), self._storable("Waste")
        bom = self._bom(
            finished,
            [(component, 1, {})],
            operation_ids=[
                Command.create({"name": "Cut", "workcenter_id": self.workcenter_2.id})
            ],
            byproduct_ids=[Command.create({"product_id": byproduct.id})],
        )
        options, lines = self._bom_overview(bom)
        ids = [line["id"] for line in lines]
        self.assertEqual(len(ids), len(set(ids)), ids)

        waste_line = next(
            line for line in lines if line["name"] == byproduct.display_name
        )
        action = self.env["mrp.bom.overview.report.handler"].caret_option_open_record(
            options, {"line_id": waste_line["id"]}
        )
        self.assertEqual(
            (action["res_model"], action["res_id"]), ("product.product", byproduct.id)
        )

    def _free(self, product, quantity):
        self.env["stock.quant"]._update_available_quantity(
            product, self.warehouse_1.lot_stock_id, quantity
        )

    def _structure(self, bom, **context):
        return self.bom_structure.with_context(
            warehouse_id=self.warehouse_1.id, **context
        )._get_report_data(bom.id)["lines"]

    def test_producible_reads_a_sub_bom_line_in_its_own_unit(self):
        finished = self._storable("Finished")
        sub = self._storable("Sub")
        self._bom(sub, [(self._storable("Raw"), 1, {})])
        bom = self._bom(finished, [(sub, 1, {"product_uom_id": self.uom_dozen.id})])
        self._free(sub, 24)
        self.assertEqual(self._structure(bom)["producible_qty"], 2)

    def test_producible_merges_sub_bom_lines_in_one_unit(self):
        finished = self._storable("Finished")
        sub = self._storable("Sub")
        self._bom(sub, [(self._storable("Raw"), 1, {})])
        bom = self._bom(
            finished,
            [(sub, 1, {"product_uom_id": self.uom_dozen.id}), (sub, 6, {})],
        )
        self._free(sub, 36)
        self.assertEqual(self._structure(bom)["producible_qty"], 2)

    def test_availability_adds_consumption_in_the_product_unit(self):
        finished = self._storable("Finished")
        part = self._storable("Part")
        bom = self._bom(
            finished,
            [(part, 0.5, {"product_uom_id": self.uom_dozen.id}), (part, 5, {})],
        )
        self._free(part, 10)
        first, second = self._structure(bom)["components"]
        self.assertEqual(first["availability_state"], "available")
        self.assertNotEqual(
            second["availability_state"],
            "available",
            "six plus five parts are more than the ten free",
        )

    def test_availability_counts_a_forecasted_component_once(self):
        finished = self._storable("Finished")
        part = self._storable("Part")
        sub = self._storable("Sub")
        self._bom(sub, [(part, 4, {})])
        bom = self._bom(finished, [(part, 3, {}), (sub, 1, {})])
        self._free(part, 2)
        receipt = self.env["stock.move"].create(
            {
                "product_id": part.id,
                "product_uom_qty": 6,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.warehouse_1.lot_stock_id.id,
                "date": fields.Datetime.now() + timedelta(days=2),
            }
        )
        receipt._action_confirm()
        self.env.flush_all()
        lines = self._structure(bom)
        part_row = lines["components"][0]
        sub_part_row = lines["components"][1]["components"][0]
        self.assertEqual(part_row["availability_state"], "expected")
        self.assertEqual(
            sub_part_row["availability_state"],
            "expected",
            "three plus four parts fit in the eight forecasted",
        )

    def _second_company(self):
        currency = self.env["res.currency"].create(
            {"name": "TSR", "symbol": "T", "rounding": 1.0}
        )
        company = self.env["res.company"].create(
            {"name": "Second Company", "currency_id": currency.id}
        )
        self.env.user.company_ids |= company
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], limit=1
        )
        warehouse.manufacture_steps = "pbm"
        warehouse.pbm_route_id.rule_ids.filtered(
            lambda rule: rule.location_dest_id == warehouse.pbm_loc_id
        ).delay = 3
        env = self.env(
            context=dict(
                self.env.context,
                allowed_company_ids=[self.env.company.id, company.id],
            )
        )
        return env, company, warehouse

    def test_bom_structure_uses_the_warehouse_of_the_bom_company(self):
        env, company, warehouse = self._second_company()
        finished = self._storable(
            "Finished", route_ids=[Command.set(self.route_manufacture.ids)]
        )
        bom = self._bom(
            finished, [(self._storable("Raw"), 1, {})], company_id=company.id
        )
        lines = env["report.mrp.report_bom_structure"]._get_report_data(bom.id)["lines"]
        self.assertEqual(lines["lead_time"], 3)

        report = env.ref("mrp.bom_overview_report")
        options = report.with_context(
            active_model="mrp.bom", active_id=bom.id
        ).get_options({"selected_variant_id": report.id})
        self.assertEqual(options["bom_overview_warehouse_id"], warehouse.id)

    def test_bom_days_use_the_warehouse_of_the_bom_company(self):
        env, company, _warehouse = self._second_company()
        part = self._storable(
            "Part", route_ids=[Command.set(self.route_manufacture.ids)]
        )
        raw = self.env["product.product"].create({"name": "Raw"})
        self._bom(part, [(raw, 1, {})], company_id=company.id)
        bom = self._bom(
            self._storable("Finished"), [(part, 1, {})], company_id=company.id
        )
        env["mrp.bom"].browse(bom.id).action_compute_bom_days()
        self.assertEqual(bom.days_to_prepare_mo, 3)

    def test_bom_structure_rounds_an_operation_in_the_bom_currency(self):
        env, company, _warehouse = self._second_company()
        workcenter = self.env["mrp.workcenter"].create(
            {"name": "Priced", "costs_hour": 100, "company_id": company.id}
        )
        bom = self._bom(
            self._storable("Finished"),
            [(self._storable("Raw"), 1, {})],
            company_id=company.id,
            operation_ids=[
                Command.create(
                    {
                        "name": "Press",
                        "workcenter_id": workcenter.id,
                        "time_mode": "manual",
                        "time_cycle_manual": 1,
                    }
                )
            ],
        )
        lines = env["report.mrp.report_bom_structure"]._get_report_data(bom.id)["lines"]
        [operation] = lines["operations"]
        self.assertEqual(operation["bom_cost"], 2)

    def test_the_catalog_prices_a_component_at_its_cost(self):
        component = self._storable("Component", standard_price=7)
        bom = self._bom(self._storable("Finished"), [(component, 1, {})])
        production = self.env["mrp.production"].create(
            {"product_id": bom.product_tmpl_id.product_variant_id.id, "bom_id": bom.id}
        )
        for record in (bom, production):
            data = record._get_product_catalog_order_data(component)
            self.assertEqual(data[component.id]["price"], 7)
        self.assertEqual(
            bom._update_order_line_info(component.id, 2, child_field="bom_line_ids"), 7
        )
        self.assertEqual(
            production._update_order_line_info(
                component.id, 2, child_field="move_raw_ids"
            ),
            7,
        )

    def test_the_order_quantity_in_the_product_unit_matches_its_move(self):
        production = self.env["mrp.production"].create(
            {
                "product_id": self.product_4.id,
                "product_uom_id": self.uom_unit.id,
                "product_qty": 4,
                "bom_id": self.bom_1.id,
            }
        )
        production.action_confirm()
        self.assertEqual(
            production.product_uom_qty, production.move_finished_ids.product_qty
        )
