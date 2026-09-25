from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestStockIntegration(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manufacture_route = cls.warehouse_1.manufacture_pull_id.route_id
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Integration B"})
        cls.warehouse_b = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company_b.id)], limit=1
        )
        cls.env.user.company_ids |= cls.company_b

    def env_ab(self):
        return self.env(
            context=dict(
                self.env.context,
                allowed_company_ids=[self.company_a.id, self.company_b.id],
            )
        )

    def make_variants(self, name):
        template = self.env["product.template"].create(
            {
                "name": name,
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.size_attribute.id,
                            "value_ids": [
                                Command.set(
                                    (self.size_attribute_s | self.size_attribute_m).ids
                                )
                            ],
                        }
                    )
                ],
            }
        )
        return template.product_variant_ids

    def make_bom(self, product, **values):
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": self.product_2.id, "product_qty": 1})
                ],
                **values,
            }
        )

    def test_orderpoints_of_two_companies_round_to_their_own_bom_unit(self):
        env = self.env_ab()
        product = env["product.product"].create(
            {"name": "Shared made", "is_storable": True}
        )
        self.make_bom(
            product, product_uom_id=self.uom_dozen.id, company_id=self.company_a.id
        )
        self.make_bom(
            product, product_uom_id=self.uom_unit.id, company_id=self.company_b.id
        )
        orderpoints = env["stock.warehouse.orderpoint"].create(
            [
                {
                    "product_id": product.id,
                    "warehouse_id": warehouse.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "company_id": warehouse.company_id.id,
                    "route_id": self.manufacture_route.id,
                }
                for warehouse in (self.warehouse_1, self.warehouse_b)
            ]
        )
        self.assertEqual(
            {op.company_id: op.replenishment_uom_id_placeholder for op in orderpoints},
            {
                self.company_a: self.uom_dozen.display_name,
                self.company_b: self.uom_unit.display_name,
            },
        )

    def test_days_to_order_ignores_a_sibling_variant_bom(self):
        covered, other = self.make_variants("Days to order")
        self.make_bom(covered, product_id=covered.id, sequence=1, days_to_prepare_mo=10)
        self.make_bom(covered, sequence=2, days_to_prepare_mo=3)
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": other.id,
                "warehouse_id": self.warehouse_1.id,
                "location_id": self.warehouse_1.lot_stock_id.id,
                "route_id": self.manufacture_route.id,
            }
        )
        self.assertEqual(orderpoint.days_to_order, 3)

    def test_orphan_line_of_a_kit_links_to_the_move_still_short_in_its_own_unit(self):
        kit = self.env["product.product"].create({"name": "Linked kit"})
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": self.product_2.id, "product_qty": 1})
                ],
            }
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": kit.id,
                            "product_uom_id": self.uom_dozen.id,
                            "product_uom_qty": 1,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                    for _index in range(2)
                ],
            }
        )
        full, short = picking.move_ids
        line_values = {
            "picking_id": picking.id,
            "product_id": kit.id,
            "product_uom_id": self.uom_dozen.id,
            "quantity": 1,
            "location_id": self.stock_location.id,
            "location_dest_id": self.customer_location.id,
        }
        self.env["stock.move.line"].create({**line_values, "move_id": full.id})
        orphan = self.env["stock.move.line"].create(line_values)
        self.assertEqual(orphan.move_id, short)

    def test_done_scrap_move_keeps_its_locations_when_the_order_changes_type(self):
        mo, _bom, _final, component, _other = self.generate_mo()
        self.env["stock.quant"]._update_available_quantity(
            component, mo.location_src_id, 10
        )
        scrap = self.env["stock.scrap"].create(
            {
                "product_id": component.id,
                "product_uom_id": component.uom_id.id,
                "scrap_qty": 1,
                "production_id": mo.id,
            }
        )
        scrap.action_validate()
        scrapped = scrap.move_ids
        self.assertEqual(scrapped.state, "done")
        source, destination = scrapped.location_id, scrapped.location_dest_id
        elsewhere = self.env["stock.location"].create(
            {"name": "Elsewhere", "location_id": self.warehouse_1.view_location_id.id}
        )
        other_type = mo.picking_type_id.copy(
            {"default_location_src_id": elsewhere.id, "sequence_code": "OTH"}
        )
        mo.picking_type_id = other_type
        self.env.flush_all()
        self.assertEqual(mo.location_src_id, elsewhere)
        self.assertEqual(
            (mo.move_raw_ids - scrapped).location_id,
            elsewhere,
            "sanity: the open component moves follow the new operation type",
        )
        self.assertEqual(
            (scrapped.location_id, scrapped.location_dest_id), (source, destination)
        )

    def test_route_usability_follows_the_variant_bom(self):
        covered, other = self.make_variants("Resupply variant")
        self.make_bom(covered, product_id=covered.id)
        allowed = {
            product: self.env["product.replenish"]
            .new(
                {
                    "product_id": product.id,
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "product_uom_id": product.uom_id.id,
                    "warehouse_id": self.warehouse_1.id,
                }
            )
            .allowed_route_ids._origin
            for product in (covered, other)
        }
        self.assertIn(self.manufacture_route, allowed[covered])
        self.assertNotIn(self.manufacture_route, allowed[other])

    def test_manufacture_rule_follows_the_warehouse_company_bom(self):
        env = self.env_ab()
        self.assertEqual(env.company, self.company_a)
        product = env["product.product"].create(
            {"name": "Made in B", "is_storable": True}
        )
        self.make_bom(product, company_id=self.company_b.id)
        orderpoint = env["stock.warehouse.orderpoint"].create(
            {
                "product_id": product.id,
                "warehouse_id": self.warehouse_b.id,
                "location_id": self.warehouse_b.lot_stock_id.id,
                "company_id": self.company_b.id,
            }
        )
        self.assertIn(self.warehouse_b.manufacture_pull_id, orderpoint.rule_ids)

    def test_byproduct_move_keeps_its_own_packaging_unit(self):
        byproduct = self.env["product.product"].create(
            {"name": "Offcut", "is_storable": True, "uom_id": self.uom_kg.id}
        )
        final = self.env["product.product"].create(
            {"name": "Cut board", "is_storable": True}
        )
        bom = self.make_bom(
            final,
            product_uom_id=self.uom_dozen.id,
            byproduct_ids=[
                Command.create(
                    {
                        "product_id": byproduct.id,
                        "product_qty": 2,
                        "product_uom_id": self.uom_kg.id,
                    }
                )
            ],
        )
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = final
        mo_form.bom_id = bom
        mo = mo_form.save()
        by_product = {move.product_id: move for move in mo.move_finished_ids}
        self.assertEqual(by_product[final].packaging_uom_id, self.uom_dozen)
        self.assertEqual(by_product[byproduct].packaging_uom_id, self.uom_kg)

    def test_scrapped_kit_with_a_combo_component_counts_its_kits(self):
        combo_item = self.env["product.product"].create({"name": "Combo item"})
        combo_product = self.env["product.product"].create(
            {
                "name": "Combo part",
                "type": "combo",
                "combo_ids": [
                    Command.create(
                        {
                            "name": "Combo choice",
                            "combo_item_ids": [
                                Command.create({"product_id": combo_item.id})
                            ],
                        }
                    )
                ],
            }
        )
        component = self.env["product.product"].create(
            {"name": "Kit part", "is_storable": True}
        )
        kit = self.env["product.product"].create({"name": "Combo kit"})
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1}),
                    Command.create({"product_id": combo_product.id, "product_qty": 1}),
                ],
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 10
        )
        scrap = self.env["stock.scrap"].create(
            {
                "product_id": kit.id,
                "product_uom_id": kit.uom_id.id,
                "bom_id": bom.id,
                "scrap_qty": 2,
                "location_id": self.stock_location.id,
            }
        )
        scrap.action_validate()
        self.assertEqual(scrap.move_ids.product_id, component)
        self.assertEqual(scrap.scrap_qty, 2)

    def make_lead_time_orderpoint(self, horizon_days=0, **orderpoint_values):
        self.env.company.stock_config_id.horizon_days = horizon_days
        product = self.env["product.product"].create(
            {"name": "Lead timed", "is_storable": True}
        )
        bom = self.make_bom(product, produce_delay=1, days_to_prepare_mo=0)
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, 10
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 15,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "date": fields.Datetime.now() + timedelta(days=5),
            }
        )._action_confirm()
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": product.id,
                "warehouse_id": self.warehouse_1.id,
                "location_id": self.stock_location.id,
                "route_id": self.manufacture_route.id,
                **orderpoint_values,
            }
        )
        return bom, orderpoint

    def stored(self, record, field_name):
        self.env.flush_all()
        self.env.invalidate_all()
        return record.browse(record.id)[field_name]

    def test_stored_suggestion_follows_the_bom_lead_times(self):
        for field_name in ("produce_delay", "days_to_prepare_mo"):
            with self.subTest(field_name=field_name):
                bom, orderpoint = self.make_lead_time_orderpoint(
                    product_min_qty=0, product_max_qty=0
                )
                self.assertEqual(self.stored(orderpoint, "qty_to_order_computed"), 0)
                bom[field_name] = 10
                self.assertEqual(self.stored(orderpoint, "qty_to_order_computed"), 5)

    def test_stored_deadline_follows_the_days_to_prepare(self):
        bom, orderpoint = self.make_lead_time_orderpoint(
            horizon_days=30, product_min_qty=5, product_max_qty=5
        )
        before = self.stored(orderpoint, "deadline_date")
        bom.days_to_prepare_mo = 2
        self.assertEqual(
            self.stored(orderpoint, "deadline_date"), before - timedelta(days=2)
        )

    def test_lead_days_ignore_the_resupplied_warehouse_manufacturing_steps(self):
        resupplied = self.env["stock.warehouse"].create(
            {
                "name": "Resupplied",
                "code": "RSP",
                "manufacture_to_resupply": False,
                "resupply_wh_ids": [Command.set(self.warehouse_1.ids)],
            }
        )
        resupply_route = resupplied.resupply_route_ids.filtered(
            lambda route: route.supplier_wh_id == self.warehouse_1
        )
        resupply_route.rule_ids.procure_method = "make_to_order"
        product = self.env["product.product"].create(
            {
                "name": "Made elsewhere",
                "is_storable": True,
                "route_ids": [Command.set(self.manufacture_route.ids)],
            }
        )
        self.make_bom(product, produce_delay=2)
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": product.id,
                "warehouse_id": resupplied.id,
                "location_id": resupplied.lot_stock_id.id,
                "route_id": resupply_route.id,
            }
        )
        self.assertIn(self.warehouse_1.manufacture_pull_id, orderpoint.rule_ids)
        one_step = self.stored(orderpoint, "lead_days")
        resupplied.manufacture_steps = "pbm"
        resupplied.pbm_route_id.rule_ids.delay = 7
        self.assertEqual(self.stored(orderpoint, "lead_days"), one_step)

    def test_view_production_of_a_picking_with_an_order_on_an_archived_type(self):
        mo_kept = self.generate_mo()[0]
        mo_hidden = self.generate_mo()[0]
        archived_type = mo_hidden.picking_type_id.copy({"sequence_code": "ARC"})
        mo_hidden.picking_type_id = archived_type
        mo_hidden.production_group_id = mo_kept.production_group_id
        archived_type.active = False
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product_2.id,
                            "product_uom_qty": 1,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                            "production_group_id": mo_kept.production_group_id.id,
                        }
                    )
                ],
            }
        )
        self.assertEqual(picking.production_count, 1)
        action = picking.action_view_mrp_production()
        self.assertEqual(action["res_id"], mo_kept.id)

    def test_production_group_cycle_through_parents_is_refused(self):
        parent, child = self.env["mrp.production.group"].create(
            [{"name": "Parent"}, {"name": "Child"}]
        )
        parent.child_ids = [Command.link(child.id)]
        with self.assertRaises(ValidationError):
            parent.parent_ids = [Command.link(child.id)]
            self.env.flush_all()

    def test_show_bom_sees_a_manufacture_rule_archived_in_the_transaction(self):
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.product_2.id,
                "warehouse_id": self.warehouse_1.id,
                "location_id": self.warehouse_1.lot_stock_id.id,
                "route_id": self.manufacture_route.id,
            }
        )
        self.assertTrue(orderpoint.show_bom)
        self.manufacture_route.rule_ids.active = False
        orderpoint.invalidate_recordset(["show_bom"])
        self.assertFalse(orderpoint.show_bom)


@tagged("post_install", "-at_install")
class TestReplenishmentWithoutPurchase(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.warehouse_1
        cls.suppliers = cls.env.ref("stock.stock_location_suppliers")

    def setUp(self):
        super().setUp()
        if "buy_pull_id" in self.env["stock.warehouse"]._fields:
            self.skipTest("purchase_stock replaces the vendor pull with its Buy route")

    def test_a_bought_in_component_is_received_from_vendors(self):
        component = self.env["product.product"].create(
            {"name": "Bought in", "is_storable": True}
        )
        rule = self.env["stock.rule"]._get_rule(
            component, self.warehouse.lot_stock_id, {"warehouse_id": self.warehouse}
        )
        self.assertEqual(rule.location_src_id, self.suppliers)
        self.assertEqual(rule.route_id, self.warehouse.reception_route_id)
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": component.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "product_min_qty": 5,
                "product_max_qty": 10,
            }
        )
        orderpoint.action_replenish()
        receipt = self.env["stock.move"].search([("product_id", "=", component.id)])
        self.assertEqual(receipt.location_id, self.suppliers)
        self.assertEqual(receipt.product_uom_qty, 10)

    def test_a_product_with_a_bom_is_still_manufactured(self):
        product = self.env["product.product"].create(
            {"name": "Made here", "is_storable": True}
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": self.product_1.id, "product_qty": 1})
                ],
            }
        )
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": product.id,
                "location_id": self.warehouse.lot_stock_id.id,
                "product_min_qty": 5,
                "product_max_qty": 10,
            }
        )
        self.assertEqual(
            orderpoint.effective_route_id, self.warehouse.manufacture_pull_id.route_id
        )
        orderpoint.action_replenish()
        self.assertTrue(
            self.env["mrp.production"].search([("product_id", "=", product.id)])
        )
