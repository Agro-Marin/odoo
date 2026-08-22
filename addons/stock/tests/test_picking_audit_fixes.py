from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestPickingAuditFixes(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids = [
            (4, cls.env.ref("stock.group_production_lot").id),
            (4, cls.env.ref("stock.group_warning_stock").id),
        ]

    def _storable(self, **vals):
        return self.env["product.product"].create(
            {"name": "Picking audit product", "is_storable": True, **vals},
        )

    def _picking(self, product, qty=5, picking_type=None, assign=True):
        picking_type = picking_type or self.picking_type_out
        picking = self.env["stock.picking"].create(
            {"picking_type_id": picking_type.id},
        )
        self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": qty,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            },
        )
        picking.action_confirm()
        if assign:
            picking.action_assign()
        return picking

    def test_shipping_weight_follows_the_move_quantity(self):
        product = self._storable(weight=2.0)
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=5)
        picking.move_ids.quantity = 5
        self.env.flush_all()
        self.assertEqual(picking.shipping_weight, 10.0)

        picking.move_ids.quantity = 3
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.shipping_weight, 6.0)

    def test_shipping_weight_follows_the_product_weight(self):
        product = self._storable(weight=2.0)
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=5)
        picking.move_ids.quantity = 5
        self.env.flush_all()
        self.assertEqual(picking.shipping_weight, 10.0)

        product.weight = 10.0
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.weight_bulk, 50.0)
        self.assertEqual(picking.shipping_weight, 50.0)

    def test_weight_and_volume_of_an_unsaved_picking(self):
        product = self._storable(weight=3.0, volume=2.0)
        picking = self.env["stock.picking"].new(
            {"picking_type_id": self.picking_type_out.id},
        )
        picking.move_line_ids = [
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "quantity": 4,
                    "location_id": picking.location_id.id,
                    "location_dest_id": picking.location_dest_id.id,
                },
            ),
        ]
        picking.move_ids = [
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "product_uom_qty": 4,
                    "quantity": 4,
                    "location_id": picking.location_id.id,
                    "location_dest_id": picking.location_dest_id.id,
                },
            ),
        ]
        self.assertEqual(picking.weight_bulk, 12.0)
        self.assertEqual(picking.shipping_volume, 8.0)

    def test_cancelled_moveless_picking_survives_a_write(self):
        picking = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id},
        )
        picking.action_cancel()
        self.env.flush_all()
        self.assertEqual(picking.state, "cancel")

        picking.write({"location_id": picking.location_id.id})
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.state, "cancel")

    def test_moveless_picking_without_a_cancel_is_still_draft(self):
        picking = self.env["stock.picking"].create(
            {"picking_type_id": self.picking_type_out.id},
        )
        self.env.flush_all()
        picking.invalidate_recordset()
        self.assertEqual(picking.state, "draft")

    def test_lot_check_covers_lines_that_will_be_autopicked(self):
        self.picking_type_in.write(
            {"use_create_lots": True, "use_existing_lots": False},
        )
        tracked = self._storable(tracking="lot")
        picking = self._picking(
            tracked,
            qty=4,
            picking_type=self.picking_type_in,
            assign=False,
        )
        picking.move_ids.quantity = 4
        self.env.flush_all()
        self.assertFalse(picking.move_ids.picked)
        self.assertTrue(picking._get_lot_move_lines_for_sanity_check())

    def test_multi_picking_lot_error_names_the_transfers(self):
        vals = {"use_create_lots": True, "use_existing_lots": False}
        if "auto_batch" in self.picking_type_in._fields:
            vals["auto_batch"] = False
        self.picking_type_in.write(vals)
        pickings = self.env["stock.picking"]
        for _index in range(2):
            picking = self._picking(
                self._storable(tracking="lot"),
                qty=2,
                picking_type=self.picking_type_in,
                assign=False,
            )
            picking.move_ids.quantity = 2
            pickings |= picking
        self.env.flush_all()
        with self.assertRaises(UserError) as caught:
            pickings.button_validate()
        message = str(caught.exception)
        for name in pickings.mapped("name"):
            self.assertIn(name, message)

    def test_autopick_still_ignores_a_pre_picked_scrap_move(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=5)
        picking.move_ids.quantity = 5
        self.env.flush_all()
        self.assertIn(picking, picking._get_pickings_to_autopick())

    def test_unchanged_picking_type_write_on_a_done_picking(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=2)
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        self.env.flush_all()
        self.assertEqual(picking.state, "done")

        picking.write({"picking_type_id": picking.picking_type_id.id})
        self.assertEqual(picking.picking_type_id, self.picking_type_out)

    def test_changing_the_picking_type_of_a_done_picking_is_still_refused(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=2)
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        self.env.flush_all()
        with self.assertRaises(UserError):
            picking.write({"picking_type_id": self.picking_type_in.id})

    def test_backorders_are_created_for_every_picking(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            1000,
        )
        pickings = self.env["stock.picking"]
        for _index in range(3):
            pickings |= self._picking(product, qty=6)
        pickings.move_ids.quantity = 2
        pickings.move_ids.picked = True
        self.env.flush_all()

        backorders = pickings._create_backorder()
        self.assertEqual(len(backorders), 3)
        self.assertEqual(backorders.mapped("backorder_id"), pickings)
        self.assertFalse(
            [name for name in backorders.mapped("name") if not name or name == "/"],
            "each backorder takes its own sequence number",
        )
        self.assertFalse(backorders.user_id)
        for picking, backorder in zip(pickings, backorders, strict=True):
            self.assertEqual(backorder.picking_type_id, picking.picking_type_id)
            self.assertEqual(backorder.location_id, picking.location_id)

    def test_post_create_backorder_hook_runs_once_per_picking(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            1000,
        )
        pickings = self.env["stock.picking"]
        for _index in range(2):
            pickings |= self._picking(product, qty=6)
        pickings.move_ids.quantity = 2
        pickings.move_ids.picked = True
        self.env.flush_all()

        seen = []
        original = type(pickings)._post_create_backorder

        def _record(self, backorder):
            seen.append((self.id, backorder.id))
            return original(self, backorder)

        self.patch(type(pickings), "_post_create_backorder", _record)
        backorders = pickings._create_backorder()
        self.assertEqual(
            seen,
            list(zip(pickings.ids, backorders.ids, strict=True)),
        )

    def test_log_activity_get_documents_tolerates_no_changes(self):
        self.assertEqual(
            self.env["stock.picking"]._log_activity_get_documents(
                {},
                "move_dest_ids",
                "UP",
            ),
            {},
        )

    def test_picking_warning_text_follows_the_partner_message(self):
        partner = self.env["res.partner"].create({"name": "Audit partner"})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "partner_id": partner.id,
            },
        )
        self.assertEqual(picking.picking_warning_text, "")
        partner.picking_warn_msg = "Ring the bell"
        self.assertEqual(picking.picking_warning_text, "Ring the bell\n")

    def test_has_tracking_follows_the_moves(self):
        picking = self._picking(self._storable(), qty=1, assign=False)
        self.assertFalse(picking.has_tracking)
        self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self._storable(tracking="lot").id,
                "product_uom_qty": 1,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
            },
        )
        self.assertTrue(picking.has_tracking)

    def test_is_date_editable_follows_the_lock(self):
        product = self._storable()
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_location,
            100,
        )
        picking = self._picking(product, qty=2)
        picking.move_ids.quantity = 2
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        self.env.flush_all()
        self.assertFalse(picking.is_date_editable)
        picking.action_toggle_is_locked()
        self.assertTrue(picking.is_date_editable)
