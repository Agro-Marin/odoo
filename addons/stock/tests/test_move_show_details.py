from odoo import Command
from odoo.tests import new_test_user, tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestShowDetailsVisible(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Groups = cls.env["res.groups"]
        for xmlid in (
            "stock.group_stock_multi_locations",
            "stock.group_tracking_owner",
        ):
            grp = cls.env.ref(xmlid)
            Groups.search([("implied_ids", "in", grp.id)]).write(
                {"implied_ids": [Command.unlink(grp.id)]},
            )
            grp.write({"user_ids": [Command.clear()]})

        cls.pack_user = new_test_user(
            cls.env,
            login="show_details_pack_user",
            groups="base.group_user,stock.group_stock_user,stock.group_tracking_lot",
        )
        cls.plain_user = new_test_user(
            cls.env,
            login="show_details_plain_user",
            groups="base.group_user,stock.group_stock_user",
        )

        cls.product_no_track = cls.env["product.product"].create(
            {"name": "No Track", "is_storable": True, "tracking": "none"},
        )
        cls.internal_type = cls.env["stock.picking.type"].search(
            [("code", "=", "internal")],
            limit=1,
        )
        cls.internal_type.write(
            {"use_create_lots": False, "use_existing_lots": False},
        )

    def _make_move(self, user):
        loc = self.env.ref("stock.stock_location_stock")
        move = self.env["stock.move"].create(
            {
                "product_id": self.product_no_track.id,
                "product_uom_qty": 1.0,
                "location_id": loc.id,
                "location_dest_id": loc.id,
                "picking_type_id": self.internal_type.id,
            },
        )
        move.state = "confirmed"
        move = move.with_user(user)
        move.invalidate_recordset(["show_details_visible"])
        return move

    def test_setup_is_discriminating(self):
        self.assertTrue(self.pack_user.has_group("stock.group_tracking_lot"))
        self.assertFalse(self.pack_user.has_group("stock.group_stock_multi_locations"))
        self.assertFalse(self.pack_user.has_group("stock.group_tracking_owner"))
        self.assertFalse(self.plain_user.has_group("stock.group_tracking_lot"))
        self.assertFalse(self.plain_user.has_group("stock.group_stock_multi_locations"))
        self.assertFalse(self.plain_user.has_group("stock.group_tracking_owner"))

    def test_packages_group_reveals_details_on_non_lot_type(self):
        move = self._make_move(self.pack_user)
        self.assertTrue(
            move.show_details_visible,
            "The Packages group must reveal the detailed operations button even "
            "when the picking type manages no lots.",
        )

    def test_no_revealing_group_hides_details_on_non_lot_type(self):
        move = self._make_move(self.plain_user)
        self.assertFalse(
            move.show_details_visible,
            "Without any of the packages/multi-location/owner groups, a non-lot "
            "picking type should not show the detailed operations button.",
        )
