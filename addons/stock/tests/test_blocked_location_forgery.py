from odoo.exceptions import UserError
from odoo.tests import tagged

from .blocked_location_common import BlockedLocationCase
from .common import LocationCase


class TestContextForgery(BlockedLocationCase):
    def test_completing_flag_cannot_be_forged_at_the_quant_layer(self):
        self._add_stock(self.soft_out_location, 100.0)
        with self.assertRaises(UserError):
            self.Quant.with_user(self.normal_user).with_context(
                stock_blocked_completing=True
            )._update_available_quantity(self.product, self.soft_out_location, -50.0)
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_completing_flag_cannot_be_forged_at_the_line_layer(self):
        self._add_stock(self.soft_out_location, 100.0)
        picking = self._create_delivery(self.normal_user, self.soft_out_location, 10.0)
        picking.action_unreserve()
        with self.assertRaises(UserError):
            picking.with_user(self.normal_user).with_context(
                stock_blocked_completing=True
            ).move_ids.quantity = 10.0
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_is_inventory_flag_cannot_be_forged(self):
        self._add_stock(self.soft_out_location, 100.0)
        with self.assertRaises(UserError):
            self.Quant.with_user(self.normal_user).with_context(
                stock_blocked_is_inventory=True
            )._update_available_quantity(self.product, self.soft_out_location, -50.0)
        self.assertEqual(self._on_hand(self.soft_out_location), 100.0)

    def test_excluded_types_cannot_be_forged(self):
        self._add_stock(self.soft_out_location, 100.0)
        quants = (
            self.Quant.with_user(self.normal_user)
            .with_context(stock_blocked_excluded_types=())
            ._gather(self.product, self.stock_location)
        )
        self.assertFalse(
            quants.filtered(lambda q: q.location_id == self.soft_out_location),
            "an empty exclusion sent by the client must not un-filter gathering",
        )

    def test_excluded_types_cannot_be_forged_through_available_quantity(self):
        self._add_stock(self.soft_out_location, 100.0)
        self._add_stock(self.normal_location, 50.0)
        available = (
            self.Quant.with_user(self.normal_user)
            .with_context(stock_blocked_excluded_types=())
            ._get_available_quantity(self.product, self.stock_location)
        )
        self.assertEqual(available, 50.0)

    def test_skip_hooks_flag_cannot_be_forged(self):
        with self.assertRaises(UserError):
            self.hard_block_location.with_user(self.manager_user).with_context(
                stock_blocked_skip_hooks=True
            ).write({"block_type": "none"})
        self.assertEqual(self.hard_block_location.block_type, "hard")

    def test_visibility_bypass_cannot_be_forged(self):
        self._add_stock(self.soft_out_location, 100.0)
        product = self.product.with_user(self.vendor_user).with_context(
            bypass_blocked_locations=True,
        )
        product.invalidate_recordset(["qty_available"])
        self.assertEqual(product.qty_available, 0.0)


@tagged("post_install", "-at_install")
class TestTheBlockSurvivesAQuantIdWrite(LocationCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.blocked_product = cls._create_product("Quant Bypass Product")
        cls.free_location = cls._create_location("Bypass Free")
        cls.blocked_location = cls._create_location(
            "Bypass Blocked",
            block_type="soft_out",
        )
        cls.env["stock.quant"].create(
            [
                {
                    "product_id": cls.blocked_product.id,
                    "location_id": cls.free_location.id,
                    "quantity": 50,
                },
                {
                    "product_id": cls.blocked_product.id,
                    "location_id": cls.blocked_location.id,
                    "quantity": 50,
                },
            ],
        )
        cls.blocked_quant = cls.env["stock.quant"].search(
            [
                ("location_id", "=", cls.blocked_location.id),
                ("product_id", "=", cls.blocked_product.id),
            ],
        )
        cls.stock_user = cls.env["res.users"].create(
            {
                "name": "Hardening Stock User",
                "login": "hardening_block_stock_user",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("stock.group_stock_user").id,
                            cls.env.ref("stock.group_stock_multi_locations").id,
                        ],
                    ),
                ],
            },
        )
        cls.env.flush_all()

    def test_the_fixture_is_not_a_superuser(self):
        self.assertFalse(self._reserved_line().env.su)
        self.assertEqual(
            self.blocked_location.effective_block_type,
            "soft_out",
        )

    def _reserved_line(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.free_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self.blocked_product.id,
                "product_uom_qty": 5,
                "location_id": self.free_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        picking.action_confirm()
        picking.action_assign()
        self.assertTrue(
            move.move_line_ids,
            "nothing reserved, so there is no line to redirect and the tests "
            "below would pass for the wrong reason",
        )
        return move.move_line_ids[0].with_user(self.stock_user)

    def test_naming_the_blocked_location_outright_is_refused(self):
        with self.assertRaises(UserError):
            self._reserved_line().write({"location_id": self.blocked_location.id})

    def test_naming_a_quant_that_lives_there_is_refused_too(self):
        with self.assertRaises(UserError):
            self._reserved_line().write({"quant_id": self.blocked_quant.id})

    def test_the_same_holds_through_web_save(self):
        with self.assertRaises(UserError):
            self._reserved_line().web_save(
                {"quant_id": self.blocked_quant.id},
                {"id": {}, "location_id": {}},
            )

    def test_creating_a_line_on_a_blocked_quant_is_still_refused(self):
        line = self._reserved_line()
        with self.assertRaises(UserError):
            self.env["stock.move.line"].with_user(self.stock_user).create(
                {
                    "move_id": line.move_id.id,
                    "product_id": self.blocked_product.id,
                    "product_uom_id": self.blocked_product.uom_id.id,
                    "quantity": 1,
                    "quant_id": self.blocked_quant.id,
                    "location_dest_id": self.customer_location.id,
                },
            )

    def test_an_unblocked_quant_is_still_reachable_by_quant_id(self):
        free_quant = self.env["stock.quant"].search(
            [
                ("location_id", "=", self.free_location.id),
                ("product_id", "=", self.blocked_product.id),
            ],
        )
        line = self._reserved_line()
        line.write({"quant_id": free_quant.id})
        self.assertEqual(line.location_id, self.free_location)
