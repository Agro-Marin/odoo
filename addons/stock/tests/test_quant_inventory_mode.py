from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase

from odoo.addons.mail.tests.common import mail_new_test_user


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
