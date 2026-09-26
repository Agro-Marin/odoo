from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTrip(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.out_type = cls.warehouse.out_type_id
        cls.out_type.write(
            {"dispatch_management": True, "dispatch_batch_required": True}
        )

        cls.driver_user = cls.env["res.users"].create(
            {
                "name": "Driver",
                "login": "trip_driver",
                "group_ids": [
                    Command.set([cls.env.ref("stock_fleet.group_trip_driver").id])
                ],
            }
        )
        cls.supervisor = cls.env["res.users"].create(
            {
                "name": "Supervisor",
                "login": "trip_supervisor",
                "group_ids": [Command.set([cls.env.ref("stock.group_stock_user").id])],
            }
        )
        cls.driver = cls.env["hr.employee"].create(
            {"name": "Driver", "user_id": cls.driver_user.id}
        )
        cls.other_driver = cls.env["hr.employee"].create({"name": "Other Driver"})
        cls.model = cls.env["product.product"].create(
            {
                "name": "Test Truck",
                "type": "consu",
                "asset_kind_id": cls.env.ref("resource_asset.kind_vehicle").id,
            }
        )
        cls.vehicle = cls.env["resource.asset"].create(
            {
                "name": "Truck",
                "kind_id": cls.env.ref("resource_asset.kind_vehicle").id,
                "product_id": cls.model.id,
                "operator_id": cls.driver.resource_id.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Freight", "is_storable": True, "weight": 10.0}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.stock_location, 1000
        )

    def _picking(self, quantity=1, product=None):
        product = product or self.product
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.out_type.id,
                "partner_id": self.env["res.partner"].create({"name": "Customer"}).id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
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

    def _trip(self, pickings, **vals):
        return self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.out_type.id,
                "picking_ids": [Command.set(pickings.ids)],
                "vehicle_id": self.vehicle.id,
                "operator_id": self.driver.id,
                "supervisor_id": self.supervisor.id,
                "odometer_departure": 1000.0,
                **vals,
            }
        )

    def test_the_operator_is_chosen_per_trip_not_taken_from_the_vehicle(self):
        # The vehicle's holder (self.driver) takes it home; who drives a trip is
        # chosen for that trip.
        trip = self._trip(self._picking(), operator_id=False)
        self.assertFalse(trip.operator_id)
        self.assertFalse(trip.driver_id)
        self.assertEqual(trip.trip_state, "planned")
        with self.assertRaisesRegex(UserError, "Operator"):
            trip.action_depart()
        trip.operator_id = self.other_driver
        self.assertEqual(trip.driver_id, self.other_driver.partner_id)

    def test_a_custody_change_does_not_reach_the_trip(self):
        trip = self._trip(self._picking())
        trip.action_depart()
        self.vehicle.operator_id = self.other_driver.resource_id
        trip.invalidate_recordset()
        self.assertEqual(trip.operator_id, self.driver)
        self.assertEqual(trip.driver_id, self.driver.partner_id)

    def test_departure_stamps_and_freezes_the_trip(self):
        trip = self._trip(self._picking())
        trip.action_depart()
        self.assertTrue(trip.date_departure)
        self.assertEqual(trip.departed_uid, self.env.user)
        self.assertEqual(trip.trip_state, "in_transit")
        with self.assertRaises(UserError):
            trip.write({"operator_id": self.other_driver.id})
        with self.assertRaises(UserError):
            trip.write({"odometer_departure": 1500.0})
        trip.write({"odometer_departure": 1000.0})  # same value: not a change

    def test_departure_lists_what_is_missing(self):
        trip = self._trip(self._picking(), supervisor_id=False, odometer_departure=0.0)
        with self.assertRaisesRegex(UserError, "Supervisor"):
            trip.action_depart()

    def test_the_supervisor_cannot_be_the_operator(self):
        trip = self._trip(self._picking(), supervisor_id=self.driver_user.id)
        with self.assertRaisesRegex(UserError, "cannot be its operator"):
            trip.action_depart()

    def test_a_trip_does_not_leave_with_transfers_that_are_not_ready(self):
        missing = self.env["product.product"].create(
            {"name": "Out of stock", "is_storable": True}
        )
        picking = self._picking(product=missing)
        self.assertEqual(picking.state, "confirmed")
        trip = self._trip(picking)
        with self.assertRaisesRegex(UserError, "not ready"):
            trip.action_depart()

    def test_a_transfer_outside_a_departed_trip_is_not_validated(self):
        loose = self._picking()
        with self.assertRaisesRegex(UserError, "must be delivered from a trip"):
            loose.button_validate()
        picking = self._picking()
        self._trip(picking)
        with self.assertRaisesRegex(UserError, "has not departed"):
            picking.button_validate()

    def test_a_type_without_the_rule_validates_freely(self):
        self.out_type.dispatch_batch_required = False
        picking = self._picking()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")

    def test_the_driver_delivers_and_the_transfer_stays_on_the_trip(self):
        picking = self._picking()
        trip = self._trip(picking)
        trip.action_depart()
        picking.action_deliver()
        self.assertEqual(picking.state, "done")
        self.assertEqual(picking.batch_id, trip)
        self.assertEqual(trip.trip_delivered_count, 1)

    def test_an_undelivered_stop_leaves_the_trip_with_its_reason(self):
        delivered, failed = self._picking(), self._picking()
        trip = self._trip(delivered | failed)
        trip.action_depart()
        wizard = self.env["stock.picking.delivery.failure"].create(
            {"picking_id": failed.id, "reason": "Customer absent"}
        )
        wizard.action_confirm()
        self.assertFalse(failed.batch_id)
        self.assertEqual(failed.delivery_failure_reason, "Customer absent")
        self.assertEqual(failed.state, "assigned")
        self.assertEqual(trip.picking_ids, delivered)

    def test_the_return_closes_the_trip_and_logs_the_odometer(self):
        trip = self._trip(self._picking())
        trip.action_depart()
        with self.assertRaisesRegex(UserError, "odometer at return"):
            trip.action_return()
        with self.assertRaises(ValidationError):
            trip.odometer_return = 900.0
        trip.odometer_return = 1250.0
        trip.action_return()
        self.assertEqual(trip.trip_state, "closed")
        log = self.env["resource.asset.log"].search(
            [("picking_batch_id", "=", trip.id)]
        )
        self.assertEqual(log.odometer, 1250.0)
        self.assertEqual(log.source, "delivery")
        with self.assertRaises(UserError):
            trip.odometer_return = 1300.0

    def test_a_batch_that_does_not_dispatch_has_no_trip_state(self):
        in_type = self.warehouse.in_type_id
        in_type.dispatch_management = False
        batch = self.env["stock.picking.batch"].create({"picking_type_id": in_type.id})
        self.assertFalse(batch.trip_state)

    def test_a_done_batch_that_never_left_is_not_a_trip(self):
        picking = self._picking()
        batch = self._trip(picking)
        picking.move_ids.picked = True
        self.out_type.dispatch_batch_required = False
        batch.action_done()
        self.assertEqual(batch.state, "done")
        self.assertFalse(batch.trip_state)

    def test_the_batch_validates_its_transfers_inside_a_departed_trip(self):
        pickings = self._picking() | self._picking()
        trip = self._trip(pickings)
        trip.action_depart()
        pickings.move_ids.picked = True
        trip.action_done()
        self.assertEqual(set(pickings.mapped("state")), {"done"})
        self.assertEqual(trip.trip_state, "in_transit")

    def test_no_transfer_boards_a_trip_that_already_left(self):
        trip = self._trip(self._picking())
        trip.action_depart()
        late = self._picking()
        with self.assertRaisesRegex(UserError, "cannot be added"):
            late.batch_id = trip
        with self.assertRaisesRegex(UserError, "cannot be added"):
            trip.picking_ids |= late
        self.assertFalse(late.batch_id)

    def test_a_departed_trip_cannot_be_deleted(self):
        trip = self._trip(self._picking())
        trip.action_depart()
        with self.assertRaisesRegex(UserError, "cannot be deleted"):
            trip.unlink()

    def test_the_driver_closes_the_trip_the_supervisor_dispatched(self):
        picking = self._picking()
        trip = self._trip(picking)
        driver_trip = trip.with_user(self.driver_user)
        with self.assertRaisesRegex(UserError, "not by its operator"):
            driver_trip.action_depart()
        trip.with_user(self.supervisor).action_depart()
        picking.with_user(self.driver_user).action_deliver()
        driver_trip.odometer_return = 1180.0
        driver_trip.action_return()
        self.assertEqual(trip.trip_state, "closed")
        log = (
            self.env["resource.asset.log"]
            .sudo()
            .search([("picking_batch_id", "=", trip.id)])
        )
        self.assertEqual(log.odometer, 1180.0)
