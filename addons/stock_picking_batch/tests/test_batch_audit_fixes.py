from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBatchAuditFixes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.picking_type = cls.env.ref("stock.picking_type_out")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Audit product",
                "is_storable": True,
                "weight": 2.0,
                "volume": 3.0,
            }
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 1000
        )

    def _picking(self, quantity=5):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": quantity,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _batch(self, pickings):
        return self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.picking_type.id,
                "picking_ids": [Command.set(pickings.ids)],
            }
        )

    def test_merging_batches_without_a_scheduled_date_is_refused_not_crashed(self):
        empty = self.env["stock.picking.batch"].create(
            [{"picking_type_id": self.picking_type.id} for _ in range(2)]
        )
        self.assertFalse(any(empty.mapped("date_planned")))
        empty.action_merge()
        self.assertEqual(len(empty.exists()), 1)

    def test_the_shipping_volume_survives_a_weighed_package(self):
        batch = self._batch(self._picking())
        batch.action_confirm()
        batch.move_line_ids.action_put_in_pack()
        package = batch.move_line_ids.result_package_id
        batch.invalidate_recordset()
        volume_unweighed = batch.estimated_shipping_volume
        package.shipping_weight = 99.0
        batch.invalidate_recordset()
        self.assertEqual(
            batch.estimated_shipping_volume,
            volume_unweighed,
            "weighing a package must not erase the volume of what it holds",
        )
        self.assertEqual(batch.estimated_shipping_volume, 5 * self.product.volume)

    def test_the_shipping_capacity_refreshes_when_its_quantities_move(self):
        batch = self._batch(self._picking())
        self.assertEqual(batch.estimated_shipping_weight, 5 * self.product.weight)
        batch.picking_ids.move_ids.move_line_ids.quantity = 1
        self.assertEqual(
            batch.estimated_shipping_weight,
            1 * self.product.weight,
            "the compute declares no dependency on the quantities it reads",
        )

    def test_show_lots_text_refreshes_when_transfers_are_added(self):
        batch = self.env["stock.picking.batch"].create(
            {"picking_type_id": self.picking_type.id}
        )
        self.assertIs(batch.show_lots_text, False)
        picking = self._picking()
        batch.picking_ids = [Command.link(picking.id)]
        self.assertEqual(batch.show_lots_text, picking.show_lots_text)

    def test_two_batches_inverted_together_keep_their_own_lines(self):
        first, second = self._batch(self._picking()), self._batch(self._picking())
        first_lines, second_lines = first.move_line_ids, second.move_line_ids
        first.move_line_ids = first_lines
        second.move_line_ids = second_lines
        self.env.flush_all()
        self.assertTrue(second_lines.exists())
        self.assertEqual(second.move_line_ids, second_lines)
        self.assertEqual(first.move_line_ids, first_lines)

    def test_a_sequence_without_a_slash_still_names_the_batch(self):
        self.env.ref("stock_picking_batch.seq_picking_batch").prefix = "BATCH-"
        name = self.env["stock.picking.batch"]._prepare_name(
            self.picking_type, "picking.batch", self.env.company.id
        )
        self.assertIn(self.picking_type.sequence_code, name)

    def test_negative_batch_limits_are_refused(self):
        picking_type = self.picking_type.copy({"sequence_code": "AUDIT"})
        with self.assertRaises(ValidationError):
            picking_type.batch_max_lines = -1
        with self.assertRaises(ValidationError):
            picking_type.batch_max_pickings = -1

    def test_auto_batch_cannot_be_left_without_any_grouping_key(self):
        picking_type = self.picking_type.copy({"sequence_code": "AUDIT2"})
        picking_type.write(
            {
                "auto_batch": True,
                "batch_group_by_partner": False,
                "batch_group_by_destination": False,
                "batch_group_by_src_loc": False,
                "batch_group_by_dest_loc": False,
                "wave_group_by_category": False,
                "wave_group_by_location": False,
                "wave_group_by_product": True,
            }
        )
        with self.assertRaises(ValidationError):
            picking_type.wave_group_by_product = False

    def test_an_auto_batch_of_two_transfers_keeps_the_responsible(self):
        picking_type = self.picking_type.copy({"sequence_code": "AUDIT3"})
        picking_type.write(
            {
                "auto_batch": True,
                "batch_auto_confirm": True,
                "batch_group_by_partner": True,
                "batch_group_by_destination": False,
                "batch_group_by_src_loc": False,
                "batch_group_by_dest_loc": False,
                "wave_group_by_product": False,
                "wave_group_by_category": False,
                "wave_group_by_location": False,
            }
        )
        picker = self.env["res.users"].create({"name": "Picker", "login": "audit_pick"})
        partner = self.env["res.partner"].create({"name": "Audit partner"})
        pickings = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": picking_type.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "partner_id": partner.id,
                    "user_id": picker.id,
                    "move_ids": [
                        Command.create(
                            {
                                "product_id": self.product.id,
                                "product_uom_qty": 1,
                                "location_id": self.stock_location.id,
                                "location_dest_id": self.customer_location.id,
                            }
                        )
                    ],
                }
                for _ in range(2)
            ]
        )
        pickings.action_confirm()
        pickings.action_assign()
        self.assertEqual(len(pickings.batch_id), 1)
        self.assertEqual(pickings.batch_id.user_id, picker)

    def test_the_grouping_criteria_drive_every_batch_path(self):
        criteria = self.picking_type._get_batch_grouping_criteria()
        self.assertEqual(list(criteria), self.picking_type._get_batch_group_by_keys())
        for criterion in criteria.values():
            self.assertTrue(criterion.picking_path)
            self.assertEqual(
                criterion.batch_path, f"picking_ids.{criterion.picking_path}"
            )

    def test_a_wave_criterion_reads_from_the_move_lines(self):
        for criterion in self.picking_type._get_wave_grouping_criteria().values():
            self.assertFalse(criterion.picking_path)
            self.assertEqual(
                criterion.batch_path, f"move_line_ids.{criterion.line_path}"
            )

    def test_each_batch_takes_its_operation_type_from_its_own_transfers(self):
        other_type = self.picking_type.copy({"sequence_code": "AUDIT4"})
        first = self._picking()
        second = self._picking()
        second.picking_type_id = other_type
        batches = self.env["stock.picking.batch"].create([{"name": "a"}, {"name": "b"}])
        batches[0].picking_ids = [Command.link(first.id)]
        batches[1].picking_ids = [Command.link(second.id)]
        self.assertEqual(batches[0].picking_type_id, self.picking_type)
        self.assertEqual(batches[1].picking_type_id, other_type)

    def test_an_empty_batch_cannot_be_confirmed(self):
        batch = self.env["stock.picking.batch"].create(
            {"picking_type_id": self.picking_type.id}
        )
        with self.assertRaises(UserError):
            batch.action_confirm()
