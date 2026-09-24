from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.stock.tests.common import TestStockCommon


class TestEditableQuant(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.Quant = cls.env["stock.quant"].with_context(inventory_mode=True)

        Product = cls.env["product.product"]
        Location = cls.env["stock.location"]
        cls.product = Product.create(
            {
                "name": "Product A",
                "is_storable": True,
            }
        )
        cls.product2 = Product.create(
            {
                "name": "Product B",
                "is_storable": True,
            }
        )
        cls.product_tracked_sn = Product.create(
            {
                "name": "Product tracked by SN",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        cls.warehouse = Location.create(
            {
                "name": "Warehouse",
                "usage": "internal",
            }
        )
        cls.stock = Location.create(
            {
                "name": "Stock",
                "usage": "internal",
                "location_id": cls.warehouse.id,
            }
        )
        cls.room1 = Location.create(
            {
                "name": "Room A",
                "usage": "internal",
                "location_id": cls.stock.id,
            }
        )
        cls.room2 = Location.create(
            {
                "name": "Room B",
                "usage": "internal",
                "location_id": cls.stock.id,
            }
        )
        cls.inventory_loss = cls.product.property_stock_inventory

    def test_create_quant_1(self):
        quants = self.env["stock.quant"].search([("product_id", "=", self.product.id)])
        self.assertEqual(len(quants), 0)
        self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": self.stock.id,
                "inventory_quantity": 24,
            }
        ).action_apply_inventory()
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("quantity", ">", 0),
            ]
        )
        self.assertEqual(len(quants), 1)
        self.assertEqual(quants.quantity, 24)

        stock_move = self.env["stock.move"].search(
            [
                ("product_id", "=", self.product.id),
            ]
        )
        self.assertEqual(stock_move.location_id.id, self.inventory_loss.id)
        self.assertEqual(stock_move.location_dest_id.id, self.stock.id)

    def test_create_quant_2(self):
        first_quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": self.room1.id,
                "quantity": 12,
            }
        )
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("quantity", ">", 0),
            ]
        )
        self.assertEqual(len(quants), 1)
        second_quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": self.room1.id,
                "inventory_quantity": 24,
            }
        )
        second_quant.action_apply_inventory()
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("quantity", ">", 0),
            ]
        )
        self.assertEqual(len(quants), 1)
        self.assertEqual(first_quant.quantity, 24)
        self.assertEqual(first_quant.id, second_quant.id)
        stock_move = self.env["stock.move"].search(
            [
                ("product_id", "=", self.product.id),
            ]
        )
        self.assertEqual(len(stock_move), 1)

    def test_create_quant_3(self):
        valid_quant = self.env["stock.quant"].create(
            {
                "product_id": self.product.id,
                "location_id": self.room1.id,
                "quantity": 10,
            }
        )
        invalid_quant = self.env["stock.quant"].create(
            {
                "product_id": self.product2.id,
                "location_id": self.room1.id,
                "inventory_quantity": 20,
            }
        )
        self.assertEqual(valid_quant.quantity, 10)
        self.assertEqual(invalid_quant.quantity, 0)

    def test_create_quant_4(self):
        valid_quant = (
            self.env["stock.quant"]
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": self.product.id,
                    "location_id": self.room1.id,
                    "quantity": 10,
                }
            )
        )
        inventoried_quant = (
            self.env["stock.quant"]
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": self.product2.id,
                    "location_id": self.room1.id,
                    "inventory_quantity": 20,
                }
            )
        )
        inventoried_quant.action_apply_inventory()
        with self.assertRaises(UserError):
            (
                self.env["stock.quant"]
                .with_context(inventory_mode=True)
                .create(
                    {
                        "product_id": self.product.id,
                        "location_id": self.room2.id,
                        "quantity": 10,
                        "inventory_quantity": 20,
                    }
                )
            )
        self.assertEqual(valid_quant.quantity, 10)
        self.assertEqual(inventoried_quant.quantity, 20)

    def test_edit_quant_1(self):
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": self.room1.id,
                "quantity": 12,
            }
        )
        quant.inventory_quantity = 24
        quant.action_apply_inventory()
        self.assertEqual(quant.quantity, 24)
        stock_move = self.env["stock.move"].search(
            [
                ("product_id", "=", self.product.id),
            ]
        )
        self.assertEqual(stock_move.location_id.id, self.inventory_loss.id)
        self.assertEqual(stock_move.location_dest_id.id, self.room1.id)

    def test_edit_quant_2(self):
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": self.room1.id,
                "quantity": 12,
            }
        )
        quant.inventory_quantity = 8
        quant.action_apply_inventory()
        self.assertEqual(quant.quantity, 8)
        stock_move = self.env["stock.move"].search(
            [
                ("product_id", "=", self.product.id),
            ]
        )
        self.assertEqual(stock_move.location_id.id, self.room1.id)
        self.assertEqual(stock_move.location_dest_id.id, self.inventory_loss.id)

    def test_edit_quant_3(self):
        self.demo_user = mail_new_test_user(
            self.env,
            name="Pauline Poivraisselle",
            login="pauline",
            email="p.p@example.com",
            groups="base.group_user",
        )
        user_admin = self.env.ref("base.user_admin")
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": self.room1.id,
                "quantity": 12,
            }
        )
        self.assertEqual(quant.quantity, 12)
        with self.assertRaises(AccessError):
            quant.with_user(self.demo_user).write({"inventory_quantity": 8})
        self.assertEqual(quant.quantity, 12)

        quant.with_user(user_admin).write({"inventory_quantity": 8})
        quant.action_apply_inventory()
        self.assertEqual(quant.quantity, 8)

    def test_edit_quant_4(self):
        default_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        default_stock_location = default_wh.lot_stock_id
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": default_stock_location.id,
                "inventory_quantity": 100,
            }
        )
        quant.action_apply_inventory()
        self.assertEqual(self.product.qty_available, 100)
        quant.with_context(
            inventory_report_mode=True
        ).inventory_quantity_auto_apply = 75
        self.assertEqual(self.product.qty_available, 75)
        quant.with_context(
            inventory_report_mode=True
        ).inventory_quantity_auto_apply = 75
        self.assertEqual(self.product.qty_available, 75)
        smls = self.env["stock.move.line"].search(
            [("product_id", "=", self.product.id)]
        )
        self.assertRecordValues(
            smls,
            [
                {"quantity": 100},
                {"quantity": 25},
            ],
        )

    def test_edit_quant_5(self):
        default_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        default_stock_location = default_wh.lot_stock_id
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": default_stock_location.id,
                "inventory_quantity": 1,
            }
        )
        form_wizard = Form(
            self.env["stock.inventory.adjustment.name"].with_context(
                default_quant_ids=quant.ids
            )
        )
        form_wizard.inventory_adjustment_name = "Inventory Adjustment - Test"
        form_wizard.save().action_apply()
        self.assertTrue(
            self.env["stock.move"].search(
                [("reference", "=", "Inventory Adjustment - Test")], limit=1
            )
        )

    def test_sn_warning(self):
        sn1 = self.env["stock.lot"].create(
            {
                "name": "serial1",
                "product_id": self.product_tracked_sn.id,
            }
        )

        self.Quant.create(
            {
                "product_id": self.product_tracked_sn.id,
                "location_id": self.room1.id,
                "inventory_quantity": 1,
                "lot_id": sn1.id,
            }
        ).action_apply_inventory()

        dupe_sn = self.Quant.create(
            {
                "product_id": self.product_tracked_sn.id,
                "location_id": self.room2.id,
                "inventory_quantity": 1,
                "lot_id": sn1.id,
            }
        )
        dupe_sn.action_apply_inventory()
        warning = False
        warning = dupe_sn._onchange_serial_number()
        self.assertTrue(warning, "Reuse of existing serial number not detected")
        self.assertEqual(
            list(warning.keys())[0], "warning", "Warning message was not returned"
        )

    def test_revert_inventory_adjustment(self):
        default_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        default_stock_location = default_wh.lot_stock_id
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": default_stock_location.id,
                "inventory_quantity": 0.4,
            }
        )
        quant.action_apply_inventory()
        move_lines = self.env["stock.move.line"].search(
            [("product_id", "=", self.product.id), ("is_inventory", "=", True)]
        )
        self.assertEqual(
            len(move_lines),
            1,
            "One inventory adjustment move lines should have been created",
        )
        self.assertEqual(
            self.product.qty_available,
            0.4,
            "Before revert inventory adjustment qty is 0.4",
        )
        move_lines.action_revert_inventory()
        self.assertEqual(
            self.product.qty_available,
            0,
            "After revert inventory adjustment qty is not zero",
        )

    def test_multi_revert_inventory_adjustment(self):
        default_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        default_stock_location = default_wh.lot_stock_id
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": default_stock_location.id,
                "inventory_quantity": 100,
            }
        )
        quant.action_apply_inventory()
        quant.inventory_quantity = 150
        quant.action_apply_inventory()
        move_lines = self.env["stock.move.line"].search(
            [("product_id", "=", self.product.id), ("is_inventory", "=", True)]
        )
        self.assertEqual(
            self.product.qty_available,
            150,
            "Before revert multi inventory adjustment qty is 150",
        )
        self.assertEqual(
            len(move_lines),
            2,
            "Two inventory adjustment move lines should have been created",
        )
        move_lines.action_revert_inventory()
        self.assertEqual(
            self.product.qty_available,
            0,
            "After revert multi inventory adjustment qty is not zero",
        )


@tagged("post_install", "-at_install")
class TestQuantCreateContract(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location
        cls.env.user.group_ids = [
            (4, cls.env.ref("stock.group_stock_user").id),
            (4, cls.env.ref("stock.group_stock_manager").id),
        ]

    def test_create_returns_one_record_per_vals(self):
        product = self.env["product.product"].create(
            {"name": "qaud-contract", "is_storable": True}
        )
        vals_list = [
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 3,
            },
            {
                "product_id": product.id,
                "location_id": self.env["stock.location"]
                .create(
                    {
                        "name": "qaud-contract-loc",
                        "usage": "internal",
                        "location_id": self.loc.id,
                    }
                )
                .id,
                "inventory_quantity": 4,
            },
        ]
        quants = self.Quant.with_context(inventory_mode=True).create(vals_list)
        self.assertEqual(
            len(quants),
            len(vals_list),
            "create() must return one record per vals, positionally aligned",
        )

    def test_two_counted_lines_for_one_quant_are_refused(self):
        product = self.env["product.product"].create(
            {"name": "qaud-dup", "is_storable": True}
        )
        vals_list = [
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 3,
            },
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 4,
            },
        ]
        with self.assertRaises(UserError):
            self.Quant.with_context(inventory_mode=True).create(vals_list)

    def test_a_data_file_collision_names_itself(self):
        product = self.env["product.product"].create(
            {"name": "qaud-load", "is_storable": True}
        )
        data = [
            {
                "xml_id": "stock.qaud_load_a",
                "values": {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity": 3,
                },
            },
            {
                "xml_id": "stock.qaud_load_b",
                "values": {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity": 4,
                },
            },
        ]
        with self.assertRaises(UserError):
            self.Quant._load_records(data)

    def test_the_web_importer_still_creates_a_row_per_line(self):
        product = self.env["product.product"].create(
            {"name": "qaud-import", "is_storable": True}
        )
        vals_list = [
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 3,
            },
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 4,
            },
        ]
        quants = self.Quant.with_context(inventory_mode=True, import_file=True).create(
            vals_list
        )
        self.assertEqual(len(quants), 2)

    def test_name_create_refuses_with_a_reason(self):
        with self.assertRaises(UserError):
            self.env["stock.quant"].name_create("anything")


@tagged("post_install", "-at_install")
class TestQuantInventoryWrite(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.inventory_loc = cls.env["stock.location"].search(
            [("usage", "=", "inventory")], limit=1
        )
        cls.product = cls.env["product.product"].create(
            {"name": "qiw-product", "is_storable": True}
        )
        cls.quant = cls.Quant.create(
            {
                "product_id": cls.product.id,
                "location_id": cls.inventory_loc.id,
                "quantity": 3.0,
            }
        )
        cls.env.user.group_ids = [(4, cls.env.ref("stock.group_stock_user").id)]

    def test_a_forbidden_field_does_not_take_the_permitted_ones_with_it(self):
        self.quant.with_context(inventory_mode=True).write(
            {"inventory_quantity": 99.0, "product_id": self.product.id}
        )
        self.env.flush_all()
        self.quant.invalidate_recordset()
        self.assertEqual(
            self.quant.inventory_quantity,
            99.0,
            "the counted quantity is the one thing inventory mode exists to"
            " set; a rejected product_id beside it must not discard it",
        )

    def test_the_forbidden_field_is_still_refused(self):
        other = self.env["product.product"].create(
            {"name": "qiw-other", "is_storable": True}
        )
        self.quant.with_context(inventory_mode=True).write(
            {"inventory_quantity": 5.0, "product_id": other.id}
        )
        self.env.flush_all()
        self.quant.invalidate_recordset()
        self.assertEqual(self.quant.product_id, self.product)

    def test_a_forbidden_only_write_is_still_a_silent_no_op(self):
        owner = self.env["res.partner"].create({"name": "qiw-owner"})
        self.assertTrue(
            self.quant.with_context(inventory_mode=True).write({"owner_id": owner.id})
        )
        self.env.invalidate_all()
        self.assertFalse(self.quant.owner_id)

    def test_the_import_path_no_longer_discards_the_count(self):
        self.quant._load_records_write(
            {"inventory_quantity": 42.0, "location_id": self.inventory_loc.id}
        )
        self.env.flush_all()
        self.quant.invalidate_recordset()
        self.assertEqual(
            self.quant.inventory_quantity,
            42.0,
            "_load_records_write forces inventory_mode, so a data file that"
            " names the location alongside the count lost the count",
        )

    def test_an_internal_location_still_raises(self):
        loc = (
            self.env["stock.warehouse"]
            .search([("company_id", "=", self.env.company.id)], limit=1)
            .lot_stock_id
        )
        quant = self.Quant.create(
            {
                "product_id": self.product.id,
                "location_id": loc.id,
                "quantity": 1.0,
            }
        )
        with self.assertRaises(UserError):
            quant.with_context(inventory_mode=True).write(
                {"product_id": self.product.id}
            )
