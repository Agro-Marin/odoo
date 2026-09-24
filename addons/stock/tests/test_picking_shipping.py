from odoo import Command
from odoo.tests import Form, tagged

from odoo.addons.stock.tests.common import PickingCase, WarehousePickingCase


class TestAggregatesDoNotReadTheLines(PickingCase):
    def test_shipping_volume_aggregates_without_loading_the_moves(self):
        pickings = self.env["stock.picking"].concat(
            *(self._picking() for _ in range(5)),
        )
        self.env.flush_all()
        self.env.invalidate_all()

        move_ids_field = self.env["stock.picking"]._fields["move_ids"]
        self.assertFalse(
            self.env.cache.get_records(pickings, move_ids_field),
            "the fixture must start with no line ids cached",
        )

        pickings.mapped("shipping_volume")

        self.assertFalse(
            self.env.cache.get_records(pickings, move_ids_field),
            "_read_group aggregates in SQL, so reaching the comodel must not"
            " pull every line id of every transfer",
        )

    def test_shipping_volume_is_still_right(self):
        picking = self._picking(quantity=4.0)
        picking.move_ids.product_id.volume = 2.5
        picking.action_confirm()
        picking.move_ids.quantity = 4.0
        self.env.flush_all()
        self.assertAlmostEqual(
            picking.shipping_volume,
            10.0,
            msg="shipping_volume sums the done quantity, not the demand",
        )


@tagged("post_install", "-at_install")
class TestShippingPolicyFollowsARealTypeChange(WarehousePickingCase):
    def test_a_new_picking_takes_the_policy_of_the_type_chosen_in_the_form(self):
        self.type_in.move_type = "direct"
        self.type_out.move_type = "one"
        form = Form(
            self.env["stock.picking"].with_context(
                default_picking_type_id=self.type_in.id
            )
        )
        self.assertEqual(form.move_type, "direct")
        form.picking_type_id = self.type_out
        self.assertEqual(form.move_type, "one")
        self.assertEqual(form.save().move_type, "one")

    def test_a_stored_picking_takes_the_policy_of_its_new_type(self):
        self.type_in.move_type = "direct"
        self.type_int.move_type = "one"
        picking = self.env["stock.picking"].create({"picking_type_id": self.type_in.id})
        self.env.flush_all()

        picking.picking_type_id = self.type_int
        self.env.flush_all()

        self.assertEqual(picking.move_type, "one")

    def test_an_explicit_policy_in_the_same_write_wins(self):
        self.type_int.move_type = "one"
        picking = self.env["stock.picking"].create({"picking_type_id": self.type_in.id})

        picking.write({"picking_type_id": self.type_int.id, "move_type": "direct"})

        self.assertEqual(picking.move_type, "direct")


@tagged("post_install", "-at_install")
class TestStoredComputesFollowWhatTheyRead(WarehousePickingCase):
    def test_a_package_type_weight_reaches_the_shipping_weight(self):
        box = self.env["stock.package.type"].create(
            {"name": "Audit box", "base_weight": 1.0}
        )
        picking = self._assigned(self.type_out, quantity=2)
        picking.move_line_ids.result_package_id = self.env["stock.package"].create(
            {"name": "Weighed box", "package_type_id": box.id}
        )
        self.env.flush_all()
        self.assertEqual(picking.shipping_weight, 3.0)

        box.base_weight = 10.0
        self.env.flush_all()

        self.assertEqual(picking.shipping_weight, 12.0)

    def test_a_wave_location_follows_the_operation_type(self):
        picking = self._assigned(self.type_out)
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.type_out.id,
                "picking_ids": [Command.link(picking.id)],
            }
        )
        self.env.flush_all()
        self.assertFalse(batch.wave_location_id)

        self.type_out.wave_location_ids = [Command.set(self.stock.ids)]
        self.env.flush_all()

        self.assertEqual(batch.wave_location_id, self.stock)
