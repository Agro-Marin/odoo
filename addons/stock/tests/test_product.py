from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import Form, TransactionCase

from odoo.addons.stock.tests.common import TestStockCommon, is_module_installed


class TestVirtualAvailable(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.product_3.is_storable = True
        cls.picking_type_out.reservation_method = "manual"

        cls.env["stock.quant"].create(
            {
                "product_id": cls.product_3.id,
                "location_id": cls.stock_location.id,
                "quantity": 30.0,
            }
        )

        cls.env["stock.quant"].create(
            {
                "product_id": cls.product_3.id,
                "location_id": cls.stock_location.id,
                "quantity": 10.0,
                "owner_id": cls.user_stock_user.partner_id.id,
            }
        )

        cls.picking_out = cls.env["stock.picking"].create(
            {"state": "draft", "picking_type_id": cls.picking_type_out.id}
        )
        cls.env["stock.move"].create(
            {
                "product_id": cls.product_3.id,
                "product_uom_qty": 3.0,
                "product_uom_id": cls.product_3.uom_id.id,
                "picking_id": cls.picking_out.id,
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
            }
        )

        cls.picking_out_2 = cls.env["stock.picking"].create(
            {"state": "draft", "picking_type_id": cls.picking_type_out.id}
        )
        cls.env["stock.move"].create(
            {
                "restrict_partner_id": cls.user_stock_user.partner_id.id,
                "product_id": cls.product_3.id,
                "product_uom_qty": 5.0,
                "product_uom_id": cls.product_3.uom_id.id,
                "picking_id": cls.picking_out_2.id,
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.customer_location.id,
            }
        )

    def test_without_owner(self):
        self.assertAlmostEqual(40.0, self.product_3.qty_available_virtual)
        self.picking_out.action_assign()
        self.picking_out_2.action_assign()
        self.assertAlmostEqual(32.0, self.product_3.qty_available_virtual)

    def test_with_owner(self):
        prod_context = self.product_3.with_context(
            owner_id=self.user_stock_user.partner_id.id
        )
        self.assertAlmostEqual(10.0, prod_context.qty_available_virtual)
        self.picking_out.action_assign()
        self.picking_out_2.action_assign()
        self.assertAlmostEqual(5.0, prod_context.qty_available_virtual)

    def test_free_quantity(self):
        self.assertAlmostEqual(40.0, self.product_3.qty_free)
        self.picking_out.action_confirm()
        self.picking_out_2.action_confirm()
        self.assertAlmostEqual(40.0, self.product_3.qty_free)
        self.picking_out.action_assign()
        self.picking_out_2.action_assign()
        self.assertAlmostEqual(32.0, self.product_3.qty_free)
        self.picking_out.action_unreserve()
        self.picking_out_2.action_unreserve()
        self.assertAlmostEqual(40.0, self.product_3.qty_free)

    def test_archive_product_1(self):
        self.assertTrue(self.product_3.active)
        self.assertAlmostEqual(40.0, self.product_3.qty_available)
        self.assertAlmostEqual(40.0, self.product_3.qty_available_virtual)
        self.product_3.active = False
        self.assertAlmostEqual(40.0, self.product_3.qty_available)
        self.assertAlmostEqual(40.0, self.product_3.qty_available_virtual)

    def test_archive_product_2(self):
        self.assertTrue(self.product_3.active)
        orderpoint_form = Form(self.env["stock.warehouse.orderpoint"])
        orderpoint_form.product_id = self.product_3
        orderpoint_form.location_id = self.stock_location
        orderpoint_form.product_min_qty = 0.0
        orderpoint_form.product_max_qty = 5.0
        orderpoint = orderpoint_form.save()
        self.assertTrue(orderpoint.active)
        self.product_3.active = False
        self.assertFalse(orderpoint.active)

    def test_change_product_company(self):
        company1 = self.env.ref("base.main_company")
        company2 = self.env["res.company"].create({"name": "Second Company"})
        product = self.env["product.product"].create(
            {
                "name": "Product [TEST - Change Company]",
                "is_storable": True,
            }
        )
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "product_uom_id": self.uom_unit.id,
                "location_id": self.shelf_1.id,
                "quantity": 7,
                "reserved_quantity": 0,
            }
        )
        product.company_id = company1.id
        with self.assertRaises(UserError):
            product.company_id = company2.id
        quant = self.env["stock.quant"].search([("product_id", "=", product.id)])
        quant.quantity = 0
        self.env["stock.quant"]._remove_zero_quants()
        product.company_id = company2.id

    def test_change_product_company_02(self):
        company1 = self.env.ref("base.main_company")
        company2 = self.env["res.company"].create({"name": "Second Company"})
        product = self.env["product.product"].create(
            {
                "name": "Product [TEST - Change Company]",
                "type": "consu",
            }
        )
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
            }
        )
        self.env["stock.move"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 1,
                "picking_id": picking.id,
            }
        )
        picking.action_confirm()
        picking.button_validate()

        product.company_id = company1.id
        with self.assertRaises(UserError):
            product.company_id = company2.id

    def test_change_product_company_exclude_vendor_and_customer_location(self):
        company1 = self.env.ref("base.main_company")
        product = self.env["product.product"].create(
            {
                "name": "Product Single Company",
                "is_storable": True,
            }
        )
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "product_uom_id": self.uom_unit.id,
                "location_id": self.shelf_1.id,
                "quantity": 5,
            }
        )
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "product_uom_id": self.uom_unit.id,
                "location_id": self.supplier_location.id,
                "quantity": -15,
            }
        )
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "product_uom_id": self.uom_unit.id,
                "location_id": self.customer_location.id,
                "quantity": 10,
            }
        )
        product.company_id = company1.id

        product.company_id = False
        company2 = self.env["res.company"].create({"name": "Second Company"})
        with self.assertRaises(UserError):
            product.company_id = company2.id

    def test_search_qty_available(self):
        product = self.env["product.product"].create(
            {
                "name": "Brand new product",
                "is_storable": True,
            }
        )
        result = self.env["product.product"].search(
            [
                ("qty_available", "=", 0),
                ("id", "in", product.ids),
            ]
        )
        self.assertEqual(product, result)

    def test_search_qty_available_with_lot_owner_package_context(self):
        Product = self.env["product.product"]
        owner = self.user_stock_user.partner_id

        with_owner = Product.with_context(owner_id=owner.id).search(
            [("qty_available", ">", 0)]
        )
        self.assertIn(self.product_3, with_owner)

        other_owner = self.env["res.partner"].create({"name": "Other owner"})
        with_other_owner = Product.with_context(owner_id=other_owner.id).search(
            [("qty_available", ">", 0), ("id", "in", self.product_3.ids)]
        )
        self.assertFalse(with_other_owner)

        self.assertFalse(
            Product.with_context(lot_id=1).search(
                [("qty_available", ">", 0), ("id", "in", self.product_3.ids)]
            )
        )
        self.assertFalse(
            Product.with_context(package_id=1).search(
                [("qty_available", ">", 0), ("id", "in", self.product_3.ids)]
            )
        )

    def test_search_qty_available_unsupported_operator(self):
        self.env["product.product"].search([("qty_available", "ilike", "3")])

    def test_search_qty_available_includes_zero_non_storable(self):
        nonstore = self.env["product.product"].create(
            {"name": "Zero nonstore", "type": "consu", "is_storable": False}
        )
        service = self.env["product.product"].create(
            {"name": "Zero service", "type": "service"}
        )
        both = nonstore + service
        for op, val in [("=", 0.0), ("<=", 0.0), (">=", 0.0), ("<", 1.0), ("!=", 5.0)]:
            found = self.env["product.product"].search(
                ["&", ("id", "in", both.ids), ("qty_available", op, val)]
            )
            self.assertEqual(
                set(found.ids),
                set(both.ids),
                f"qty_available {op} {val} should include zero-on-hand products",
            )

    def test_search_product_quantity_candidate_set(self):
        Product = self.env["product.product"]
        stocked = Product.create({"name": "SPQ stocked", "is_storable": True})
        self.env["stock.quant"].create(
            {
                "product_id": stocked.id,
                "location_id": self.stock_location.id,
                "quantity": 15,
            }
        )
        empty = Product.create({"name": "SPQ empty", "is_storable": True})
        service = Product.create({"name": "SPQ service", "type": "service"})
        scope = (stocked + empty + service).ids
        for field in ("qty_available_virtual", "qty_free"):
            positive = Product.search(["&", ("id", "in", scope), (field, ">", 0)])
            self.assertEqual(
                positive, stocked, f"{field} > 0 should match only the stocked product"
            )
            zero = Product.search(["&", ("id", "in", scope), (field, "<=", 0)])
            self.assertEqual(
                set(zero.ids),
                {empty.id, service.id},
                f"{field} <= 0 should match every product with no stock",
            )

    def test_search_product_template(self):
        self._enable_variants()
        template = self.env["product.template"].create(
            {
                "name": "Super Product",
            }
        )
        product01 = template.product_variant_id

        self.env["stock.lot"].create(
            {
                "name": "lot1",
                "product_id": product01.id,
            }
        )

        product_attribute = self.env["product.attribute"].create(
            {"name": "PA", "create_variant": "dynamic"}
        )

        self.env["product.attribute.value"].create(
            [
                {"name": "PAV" + str(i), "attribute_id": product_attribute.id}
                for i in range(2)
            ]
        )

        tmpl_attr_lines = self.env["product.template.attribute.line"].create(
            {
                "attribute_id": product_attribute.id,
                "product_tmpl_id": product01.product_tmpl_id.id,
                "value_ids": [(6, 0, product_attribute.value_ids.ids)],
            }
        )

        self.assertFalse(product01.active)
        self.assertTrue(template.active)
        self.assertFalse(template.product_variant_ids)

        res = self.env["product.template"].name_search(name="super", operator="ilike")
        res_ids = [r[0] for r in res]
        self.assertIn(template.id, res_ids)

        product02 = self.env["product.product"].create(
            {
                "default_code": "123",
                "product_tmpl_id": template.id,
                "product_template_attribute_value_ids": [
                    (6, 0, tmpl_attr_lines.product_template_value_ids[0].ids)
                ],
            }
        )

        self.assertFalse(product01.active)
        self.assertTrue(product02.active)
        self.assertTrue(template)
        self.assertEqual(template.product_variant_ids, product02)

        res = self.env["product.template"].name_search(name="123", operator="not ilike")
        res_ids = [r[0] for r in res]
        self.assertNotIn(template.id, res_ids)

    def test_product_qty_field_and_context(self):
        main_warehouse = self.warehouse_1
        other_warehouse = self.env["stock.warehouse"].search(
            [("id", "!=", main_warehouse.id)], limit=1
        )
        warehouses = main_warehouse | other_warehouse
        main_loc = main_warehouse.lot_stock_id
        other_loc = other_warehouse.lot_stock_id
        self.assertTrue(other_warehouse, "The test needs another warehouse")

        (main_loc | other_loc).name = "Stock"
        sub_loc01, sub_loc02, sub_loc03 = self.env["stock.location"].create(
            [
                {
                    "name": "Sub0%s" % (i + 1),
                    "location_id": main_loc.id,
                }
                for i in range(3)
            ]
        )

        self.env["stock.quant"].search(
            [("product_id", "=", self.product_3.id)]
        ).unlink()
        self.env["stock.quant"]._update_available_quantity(
            self.product_3, other_loc, 1000
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product_3, main_loc, 100
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product_3, sub_loc01, 10
        )
        self.env["stock.quant"]._update_available_quantity(self.product_3, sub_loc02, 1)

        for wh, loc, expected in [
            (False, False, 1111.0),
            (False, other_loc.id, 1000.0),
            (False, main_loc.id, 111.0),
            (False, sub_loc01.id, 10.0),
            (False, sub_loc01.name, 10.0),
            (False, "sub", 11.0),
            (False, main_loc.name, 1111.0),
            (False, (sub_loc01 | sub_loc02 | sub_loc03).ids, 11.0),
            (main_warehouse.id, main_loc.name, 111.0),
            (main_warehouse.id, main_loc.id, 111.0),
            (main_warehouse.id, (main_loc | other_loc).ids, 111.0),
            (main_warehouse.id, sub_loc01.id, 10.0),
            (main_warehouse.id, (sub_loc01 | sub_loc02).ids, 11.0),
            (other_warehouse.id, main_loc.name, 1000.0),
            (other_warehouse.id, main_loc.id, 0.0),
            (main_warehouse.name, False, 111.0),
            (main_warehouse.id, False, 111.0),
            (warehouses.ids, False, 1111.0),
            (warehouses.ids, (other_loc | sub_loc02).ids, 1001),
        ]:
            product_qty = self.product_3.with_context(
                warehouse_id=wh, location=loc
            ).qty_available
            self.assertEqual(product_qty, expected)

    def test_change_type_tracked_product(self):
        product = self.env["product.template"].create(
            {
                "name": "Brand new product",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        product_form = Form(product)
        product_form.type = "service"
        product = product_form.save()
        self.assertEqual(product.tracking, "none")

        product.type = "consu"
        product.is_storable = True
        product.tracking = "serial"
        self.assertEqual(product.tracking, "serial")
        product_form = Form(product.product_variant_id)
        product_form.type = "service"
        product = product_form.save()
        self.assertEqual(product.tracking, "none")

    def test_domain_locations_only_considers_selected_companies(self):
        product = self.env["product.product"].create(
            {"name": "Product", "is_storable": True}
        )
        company_a = self.env["res.company"].create({"name": "Company A"})
        company_b = self.env["res.company"].create({"name": "Company B"})
        warehouse_a = self.env["stock.warehouse"].search(
            [("company_id", "=", company_a.id)]
        )
        warehouse_b = self.env["stock.warehouse"].search(
            [("company_id", "=", company_b.id)]
        )
        self.env["stock.quant"].create(
            [
                {
                    "product_id": product.id,
                    "location_id": warehouse_a.lot_stock_id.id,
                    "quantity": 1,
                },
                {
                    "product_id": product.id,
                    "location_id": warehouse_b.lot_stock_id.id,
                    "quantity": 2,
                },
            ]
        )

        self.assertEqual(
            product.sudo()
            .with_context(allowed_company_ids=[company_a.id])
            .qty_available,
            1,
        )
        self.assertEqual(
            product.sudo()
            .with_context(allowed_company_ids=[company_b.id])
            .qty_available,
            2,
        )
        self.assertEqual(
            product.sudo()
            .with_context(allowed_company_ids=[company_a.id, company_b.id])
            .qty_available,
            3,
        )

    def test_change_product_type_archived_product(self):
        self.picking_out.action_confirm()
        self.picking_out.action_assign()
        self.product_3.active = False

        self.product_3.write({"is_storable": False})

        self.picking_out.button_validate()

        self.assertEqual(
            self.picking_out.state,
            "done",
            "the transfer ran without raising but did not complete",
        )

    def test_qty_available_values_on_product(self):
        product = self.env["product.product"].create(
            {
                "name": "Test Qty Available Product",
                "type": "consu",
                "is_storable": True,
            }
        )
        self.assertEqual(product.qty_available, 0.0)

        with Form(product) as product_form:
            product_form.qty_available = 10.0
        self.assertEqual(product.qty_available, 10.0)

        with Form(product) as product_form:
            product_form.qty_available = 0.0
        self.assertEqual(product.qty_available, 0.0)

    def test_template_qty_available_location_context(self):
        template = self.env["product.template"].create(
            {"name": "Ctx Template", "type": "consu", "is_storable": True}
        )
        product = template.product_variant_id
        sub_location = self.env["stock.location"].create(
            {"name": "Ctx Sub", "location_id": self.stock_location.id}
        )
        quant = self.env["stock.quant"]
        quant._update_available_quantity(product, self.stock_location, 7)
        quant._update_available_quantity(product, sub_location, 3)
        self.env.invalidate_all()

        self.assertEqual(
            template.with_context(location=self.stock_location.id).qty_available,
            10.0,
        )
        self.assertEqual(
            template.with_context(location=sub_location.id).qty_available,
            3.0,
            "template qty_available must be recomputed per location context",
        )

    def test_copy_multiple_templates_sharing_attribute_value(self):
        attribute = self.env["product.attribute"].create({"name": "Ctx Color"})
        red, blue = self.env["product.attribute.value"].create(
            [
                {"name": "Ctx Red", "attribute_id": attribute.id},
                {"name": "Ctx Blue", "attribute_id": attribute.id},
            ]
        )
        category = self.env["stock.storage.category"].create({"name": "Ctx Cat"})

        def create_template(name):
            return self.env["product.template"].create(
                {
                    "name": name,
                    "type": "consu",
                    "is_storable": True,
                    "attribute_line_ids": [
                        (
                            0,
                            0,
                            {
                                "attribute_id": attribute.id,
                                "value_ids": [(6, 0, (red + blue).ids)],
                            },
                        )
                    ],
                }
            )

        template_a = create_template("Ctx A")
        template_b = create_template("Ctx B")

        def red_variant(template):
            return template.product_variant_ids.filtered(
                lambda v: (
                    red
                    in v.product_template_attribute_value_ids.product_attribute_value_id
                )
            )

        self.env["stock.storage.category.capacity"].create(
            [
                {
                    "product_id": red_variant(template_a).id,
                    "storage_category_id": category.id,
                    "quantity": 111,
                },
                {
                    "product_id": red_variant(template_b).id,
                    "storage_category_id": category.id,
                    "quantity": 222,
                },
            ]
        )

        copy_a, copy_b = (template_a + template_b).copy()

        self.assertEqual(
            red_variant(copy_a).storage_category_capacity_ids.quantity, 111.0
        )
        self.assertEqual(
            red_variant(copy_b).storage_category_capacity_ids.quantity, 222.0
        )


class TestProductEdgeCases(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.product = cls.env["product.product"].create(
            {"name": "Audit Fix Product", "is_storable": True},
        )

    def _create_move(self, qty, location, location_dest, product=None, **extra_vals):
        product = product or self.product
        return self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": qty,
                "location_id": location.id,
                "location_dest_id": location_dest.id,
                **extra_vals,
            },
        )

    def test_replenishment_info_bare_wizard_computes(self):
        wizard = self.env["stock.replenishment.info"].create({})
        self.assertFalse(wizard.json_replenishment_graph)
        self.assertFalse(wizard.json_lead_days)
        self.assertFalse(wizard.wh_replenishment_option_ids)

    def test_replenishment_info_options_created_on_create(self):
        resupplied_wh = self.env["stock.warehouse"].create(
            {
                "name": "Resupplied WH",
                "code": "RSW",
                "resupply_wh_ids": [Command.set(self.warehouse.ids)],
            },
        )
        self.assertTrue(resupplied_wh.resupply_route_ids)
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.product.id,
                "warehouse_id": resupplied_wh.id,
                "location_id": resupplied_wh.lot_stock_id.id,
                "product_min_qty": 1,
                "product_max_qty": 5,
            },
        )
        wizard = self.env["stock.replenishment.info"].create(
            {"orderpoint_id": orderpoint.id},
        )
        options = wizard.wh_replenishment_option_ids
        self.assertEqual(len(options), len(resupplied_wh.resupply_route_ids))
        self.assertEqual(
            set(options.route_id.ids),
            set(resupplied_wh.resupply_route_ids.ids),
        )
        self.assertEqual(options.product_id, self.product)

    def test_quantities_owner_context_scopes_moves(self):
        owner = self.env["res.partner"].create({"name": "Quant Owner"})
        other = self.env["res.partner"].create({"name": "Other Owner"})
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            self.stock_location,
            quantity=10,
            owner_id=owner,
        )

        move_in = self._create_move(5, self.supplier_location, self.stock_location)
        move_in._action_confirm()
        move_out = self._create_move(2, self.stock_location, self.customer_location)
        move_out._action_confirm()
        for move in (move_in, move_out):
            move.move_line_ids.unlink()
            self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "quantity": move.product_uom_qty,
                    "owner_id": owner.id,
                },
            )
        self.assertIn(
            move_in.state,
            ("confirmed", "partially_available", "assigned", "waiting"),
        )

        product_as_owner = self.product.with_context(owners=[owner.id])
        self.assertEqual(product_as_owner.qty_available, 10)
        self.assertEqual(product_as_owner.qty_incoming, 5)
        self.assertEqual(product_as_owner.qty_outgoing, 2)
        self.assertEqual(product_as_owner.qty_available_virtual, 13)

        product_as_other = self.product.with_context(owners=[other.id])
        self.assertEqual(product_as_other.qty_available, 0)
        self.assertEqual(product_as_other.qty_incoming, 0)
        self.assertEqual(product_as_other.qty_outgoing, 0)
        self.assertEqual(product_as_other.qty_available_virtual, 0)

        product_unowned = self.product.with_context(owners=[])
        self.assertEqual(product_unowned.qty_available, 0)
        self.assertEqual(product_unowned.qty_incoming, 0)
        self.assertEqual(product_unowned.qty_outgoing, 0)

    def test_inverse_qty_available_batches(self):
        product_2 = self.env["product.product"].create(
            {"name": "Audit Fix Product 2", "is_storable": True},
        )
        (self.product | product_2).write({"qty_available": 4})
        self.assertEqual(self.product.qty_available, 4)
        self.assertEqual(product_2.qty_available, 4)
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "in", (self.product | product_2).ids),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        self.assertEqual(len(quants), 2)
        self.assertEqual(quants.mapped("quantity"), [4, 4])

    def test_is_storable_flip_scoped_clean_reservations(self):
        bystander = self.env["product.product"].create(
            {"name": "Bystander", "is_storable": True},
        )
        Quant = self.env["stock.quant"]
        Quant._update_available_quantity(bystander, self.stock_location, quantity=5)
        Quant._update_reserved_quantity(bystander, self.stock_location, 3)
        bystander_quant = Quant.search(
            [
                ("product_id", "=", bystander.id),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        self.assertEqual(bystander_quant.reserved_quantity, 3)

        template = self.env["product.template"].create(
            {"name": "Becomes storable", "type": "consu", "is_storable": False},
        )
        move = self._create_move(
            5,
            self.stock_location,
            self.customer_location,
            product=template.product_variant_id,
        )
        move._action_confirm()
        move.quantity = 5

        template.write({"is_storable": True})
        self.assertTrue(template.is_storable)
        flipped_quants = Quant.search(
            [
                ("product_id", "=", template.product_variant_id.id),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        self.assertEqual(sum(flipped_quants.mapped("reserved_quantity")), 5)
        self.assertEqual(bystander_quant.reserved_quantity, 3)

    def test_template_inverse_qty_available_multi_variant_raises(self):
        attribute = self.env["product.attribute"].create(
            {
                "name": "Size",
                "value_ids": [
                    Command.create({"name": "S"}),
                    Command.create({"name": "M"}),
                ],
            },
        )
        template = self.env["product.template"].create(
            {
                "name": "Multi variant",
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        },
                    ),
                ],
            },
        )
        self.assertGreater(template.product_variant_count, 1)
        with self.assertRaises(UserError):
            template.write({"qty_available": 5})

    def test_template_create_qty_available_negative_raises(self):
        with self.assertRaises(UserError):
            self.env["product.template"].create(
                {
                    "name": "Negative qty",
                    "is_storable": True,
                    "qty_available": -5,
                },
            )

    def test_template_create_qty_available_tracked_raises(self):
        with self.assertRaises(UserError):
            self.env["product.template"].create(
                {
                    "name": "Tracked qty",
                    "is_storable": True,
                    "tracking": "lot",
                    "qty_available": 5,
                },
            )

    def test_template_create_qty_available_applies(self):
        template = self.env["product.template"].create(
            {
                "name": "Created with qty",
                "is_storable": True,
                "qty_available": 7,
            },
        )
        self.assertEqual(template.product_variant_id.qty_available, 7)

    def test_action_view_routes_diagram_falls_back_to_self(self):
        template = self.product.product_tmpl_id
        action = template.action_view_routes_diagram()
        self.assertTrue(action)

    def test_action_view_routes_diagram_falls_back_to_active_id(self):
        template = self.product.product_tmpl_id
        action = (
            self.env["product.template"]
            .with_context(active_id=template.id)
            .action_view_routes_diagram()
        )
        self.assertTrue(action)

    def test_forecasted_report_no_product_raises_usererror(self):
        with self.assertRaises(UserError):
            self.env["stock.forecasted_product_product"]._get_report_data()

    def test_forecasted_report_header_matches_lines_warehouse(self):
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Second WH", "code": "SWH"},
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            warehouse_2.lot_stock_id,
            quantity=7,
        )
        Report = self.env["stock.forecasted_product_product"]
        res = Report._get_report_data(product_ids=self.product.ids)
        self.assertEqual(res["product"][self.product.id]["quantity_on_hand"], 0)
        res = Report.with_context(warehouse_id=warehouse_2.id)._get_report_data(
            product_ids=self.product.ids,
        )
        self.assertEqual(res["product"][self.product.id]["quantity_on_hand"], 7)

    def test_forecasted_report_survives_rule_loop(self):
        route = self.env["stock.route"].create(
            {
                "name": "Looping route",
                "product_selectable": True,
                "rule_ids": [
                    Command.create(
                        {
                            "name": "Loop rule",
                            "action": "pull",
                            "procure_method": "make_to_order",
                            "location_src_id": self.stock_location.id,
                            "location_dest_id": self.stock_location.id,
                            "picking_type_id": self.warehouse.int_type_id.id,
                        },
                    ),
                ],
            },
        )
        self.product.route_ids = route
        with self.assertRaises(UserError):
            self.product._get_rules_from_location(self.stock_location)
        res = self.env["stock.forecasted_product_product"]._get_report_data(
            product_ids=self.product.ids,
        )
        self.assertFalse(res["product"][self.product.id]["leadtime"])

    def test_prepare_report_line_read_gating(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.in_type_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_id": self.product.uom_id.id,
                            "product_uom_qty": 3,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        },
                    ),
                ],
            },
        )
        move_in = picking.move_ids
        Report = self.env["stock.forecasted_product_product"]

        line = Report._prepare_report_line(3, move_in=move_in, read=False)
        self.assertFalse(line["receipt_date"])
        self.assertEqual(line["move_in"], move_in)
        self.assertEqual(line["uom_id"], self.product.uom_id)
        self.assertEqual(line["document_in"]["_name"], "stock.picking")
        self.assertEqual(line["document_in"]["id"], picking.id)
        self.assertFalse(line["document_in"]["name"])

        line = Report._prepare_report_line(3, move_in=move_in, read=True)
        self.assertTrue(line["receipt_date"])
        self.assertIsInstance(line["move_in"], dict)
        self.assertIsInstance(line["uom_id"], dict)
        self.assertEqual(line["document_in"]["name"], picking.display_name)

    def test_reception_unassign_rejects_unlinked_move(self):
        out = self._create_move(2, self.stock_location, self.customer_location)
        out._action_confirm()
        report = self.env["report.stock.report_reception"]
        with self.assertRaises(UserError):
            report.action_unassign(out.id, 2, [])

    def test_reception_unassign_rejects_bad_state(self):
        out = self._create_move(2, self.stock_location, self.customer_location)
        out._action_confirm()
        out._action_cancel()
        report = self.env["report.stock.report_reception"]
        with self.assertRaises(UserError):
            report.action_unassign(out.id, 2, [])

    def test_traceability_allowed_models_no_mrp(self):
        if is_module_installed(self.env, "mrp"):
            self.skipTest("mrp adds mrp.production to the traceability report")
        report = self.env["stock.traceability.report"].create({})
        self.assertNotIn("mrp.production", report._get_models_allowed_line())
        self.assertEqual(
            report.get_lines(model_name="mrp.production", model_id=1),
            [],
        )

    def test_relocate_wizard_single_company(self):
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            self.stock_location,
            quantity=5,
        )
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        wizard = self.env["stock.quant.relocate"].create(
            {"quant_ids": [Command.set(quant.ids)]},
        )
        self.assertEqual(wizard.company_id, self.stock_location.company_id)

    def test_request_count_default_date_is_context_today(self):
        for tz in ("Pacific/Kiritimati", "Etc/GMT+12"):
            wizard = self.env["stock.request.count"].with_context(tz=tz).create({})
            self.assertEqual(
                wizard.inventory_date,
                fields.Date.context_today(wizard),
                f"inventory_date default must be the user-timezone today ({tz})",
            )

    def test_search_qty_available_from_quants_positive_only(self):
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            self.stock_location,
            quantity=6,
        )
        found = self.env["product.product"].search(
            [("qty_available", ">", 3), ("id", "in", self.product.ids)],
        )
        self.assertEqual(found, self.product)
        found = self.env["product.product"].search(
            [("qty_available", ">", 10), ("id", "in", self.product.ids)],
        )
        self.assertFalse(found)
