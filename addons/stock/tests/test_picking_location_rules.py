from datetime import datetime

from odoo import Command
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestPickingLocationRules(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.type_in = cls.env["stock.picking.type"].search(
            [("code", "=", "incoming"), ("warehouse_id", "=", cls.warehouse.id)],
            limit=1,
        )
        cls.type_out = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing"), ("warehouse_id", "=", cls.warehouse.id)],
            limit=1,
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Location rules product", "is_storable": True}
        )
        cls.env["stock.quant"]._update_available_quantity(
            cls.product, cls.warehouse.lot_stock_id, 100
        )
        Location = cls.env["stock.location"]
        cls.shelf = Location.create(
            {
                "name": "Rules shelf",
                "location_id": cls.warehouse.lot_stock_id.id,
                "usage": "internal",
            }
        )
        cls.customer_a = Location.create({"name": "Rules cust A", "usage": "customer"})
        cls.customer_b = Location.create({"name": "Rules cust B", "usage": "customer"})
        cls.supplier_a = Location.create({"name": "Rules sup A", "usage": "supplier"})
        cls.supplier_b = Location.create({"name": "Rules sup B", "usage": "supplier"})
        Partner = cls.env["res.partner"]
        cls.partner_a = Partner.create(
            {
                "name": "Rules partner A",
                "property_stock_customer": cls.customer_a.id,
                "property_stock_supplier": cls.supplier_a.id,
            }
        )
        cls.partner_b = Partner.create(
            {
                "name": "Rules partner B",
                "property_stock_customer": cls.customer_b.id,
                "property_stock_supplier": cls.supplier_b.id,
            }
        )

    def _picking(self, picking_type, **kwargs):
        vals = {
            "picking_type_id": picking_type.id,
            "move_ids": [
                Command.create({"product_id": self.product.id, "product_uom_qty": 2})
            ],
        }
        vals.update(kwargs)
        return self.env["stock.picking"].create([vals])

    def test_partner_change_carries_both_locations(self):
        picking = self._picking(self.type_out, partner_id=self.partner_a.id)
        picking.flush_recordset()
        self.assertEqual(picking.location_dest_id, self.customer_a)

        picking.write({"partner_id": self.partner_b.id, "location_id": self.shelf.id})
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.location_id, self.shelf)
        self.assertEqual(picking.location_dest_id, self.customer_b)

    def test_partner_change_carries_the_source_on_a_receipt(self):
        picking = self._picking(self.type_in, partner_id=self.partner_a.id)
        picking.flush_recordset()
        self.assertEqual(picking.location_id, self.supplier_a)

        picking.write(
            {"partner_id": self.partner_b.id, "location_dest_id": self.shelf.id}
        )
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.location_dest_id, self.shelf)
        self.assertEqual(picking.location_id, self.supplier_b)

    def test_operation_type_change_redefaults_the_other_location(self):
        for explicit, expected_src, expected_dest in (
            (
                {},
                self.type_out.default_location_src_id,
                self.type_out.default_location_dest_id,
            ),
            (
                {"location_id": self.shelf.id},
                self.shelf,
                self.type_out.default_location_dest_id,
            ),
            (
                {"location_dest_id": self.shelf.id},
                self.type_out.default_location_src_id,
                self.shelf,
            ),
        ):
            with self.subTest(explicit=sorted(explicit)):
                picking = self._picking(self.type_in)
                picking.flush_recordset()
                picking.write({"picking_type_id": self.type_out.id, **explicit})
                picking.flush_recordset()
                picking.invalidate_recordset()
                self.assertEqual(picking.location_id, expected_src)
                self.assertEqual(picking.location_dest_id, expected_dest)

    def test_operation_type_change_carries_the_source_to_the_moves(self):
        picking = self._picking(self.type_in)
        picking.action_confirm()
        picking.flush_recordset()
        move = picking.move_ids
        self.assertEqual(move.location_id, self.type_in.default_location_src_id)

        picking.write({"picking_type_id": self.type_out.id})
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.location_id, self.type_out.default_location_src_id)
        self.assertEqual(move.location_id, picking.location_id)

    def test_operation_type_change_moves_the_reservation_with_the_source(self):
        other_type = self.env["stock.picking.type"].create(
            {
                "name": "Rules out from shelf",
                "code": "outgoing",
                "sequence_code": "RULESOUT",
                "warehouse_id": self.warehouse.id,
                "default_location_src_id": self.shelf.id,
                "default_location_dest_id": self.customer_a.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(self.product, self.shelf, 5)
        picking = self._picking(self.type_out)
        picking.action_confirm()
        picking.action_assign()
        picking.flush_recordset()
        move = picking.move_ids
        self.assertEqual(move.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(move.quantity, 2)

        picking.write({"picking_type_id": other_type.id})
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.location_id, self.shelf)
        self.assertEqual(move.location_id, self.shelf)
        self.assertEqual(
            self._reserved(self.warehouse.lot_stock_id),
            0,
            "the reservation must not stay in a location the transfer left",
        )
        self.assertEqual(
            self._reserved(self.shelf),
            2,
            "the reservation must follow the transfer to its new source",
        )

    def _reserved(self, location):
        return sum(
            self.env["stock.quant"]
            .search(
                [
                    ("product_id", "=", self.product.id),
                    ("location_id", "=", location.id),
                ]
            )
            .mapped("reserved_quantity")
        )

    def test_partner_change_carries_the_source_to_the_moves_of_a_receipt(self):
        picking = self._picking(self.type_in, partner_id=self.partner_a.id)
        picking.action_confirm()
        picking.flush_recordset()
        move = picking.move_ids
        self.assertEqual(move.location_id, self.supplier_a)

        picking.write({"partner_id": self.partner_b.id})
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.location_id, self.supplier_b)
        self.assertEqual(move.location_id, self.supplier_b)

    def test_partner_change_carries_the_destination_to_the_moves(self):
        picking = self._picking(self.type_out, partner_id=self.partner_a.id)
        picking.action_confirm()
        picking.flush_recordset()
        move = picking.move_ids
        self.assertEqual(move.location_dest_id, self.customer_a)

        picking.write({"partner_id": self.partner_b.id})
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.location_dest_id, self.customer_b)
        self.assertEqual(move.location_dest_id, self.customer_b)

    def _validate(self, picking):
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.write(
            {"quantity": picking.move_ids.product_uom_qty, "picked": True}
        )
        picking.button_validate()
        return picking

    def test_a_done_transfer_keeps_its_moves_locations(self):
        picking = self._validate(self._picking(self.type_out))
        self.assertEqual(picking.state, "done")
        source_before = picking.move_ids.location_id

        picking.write({"location_id": self.shelf.id})
        picking.flush_recordset()
        picking.invalidate_recordset()

        self.assertEqual(picking.location_id, self.shelf)
        self.assertEqual(picking.move_ids.location_id, source_before)

    def test_a_cancelled_transfer_keeps_its_moves_locations(self):
        picking = self._picking(self.type_out)
        picking.action_confirm()
        picking.action_assign()
        picking.action_cancel()
        picking.flush_recordset()
        self.assertEqual(picking.move_ids.state, "cancel")
        source_before = picking.move_ids.location_id

        picking.write({"location_id": self.shelf.id})
        picking.flush_recordset()
        picking.invalidate_recordset()

        self.assertEqual(picking.location_id, self.shelf)
        self.assertEqual(picking.move_ids.location_id, source_before)

    def test_an_open_transfer_still_carries_locations_to_its_moves(self):
        picking = self._picking(self.type_out)
        picking.action_confirm()
        picking.action_assign()
        picking.flush_recordset()
        self.assertTrue(picking.move_line_ids)

        picking.write({"location_dest_id": self.customer_b.id})
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.move_ids.location_dest_id, self.customer_b)
        self.assertEqual(picking.move_line_ids.location_dest_id, self.customer_b)

    def test_a_scrap_keeps_its_inventory_destination(self):
        picking = self._picking(self.type_out)
        picking.action_confirm()
        picking.action_assign()
        scrap = self.env["stock.scrap"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "scrap_qty": 1,
                "picking_id": picking.id,
                "location_id": self.warehouse.lot_stock_id.id,
            }
        )
        scrap.do_scrap()
        scrap_move = scrap.move_ids
        self.assertEqual(scrap_move.location_dest_usage, "inventory")
        scrap_destination = scrap_move.location_dest_id

        picking.write({"location_dest_id": self.customer_b.id})
        picking.flush_recordset()
        scrap_move.invalidate_recordset()

        self.assertEqual(scrap_move.location_dest_id, scrap_destination)

    def test_a_done_move_keeps_its_destination(self):
        picking = self._validate(self._picking(self.type_out))
        destination_before = picking.move_ids.location_dest_id

        picking.write({"location_dest_id": self.customer_b.id})
        picking.flush_recordset()
        picking.move_ids.invalidate_recordset()

        self.assertEqual(picking.location_dest_id, self.customer_b)
        self.assertEqual(picking.move_ids.location_dest_id, destination_before)

    def test_the_availability_badge_and_the_search_share_one_rule(self):
        pickings = self.env["stock.picking"]
        for picking_type, quantity in (
            (self.type_out, 1),
            (self.type_out, 99_999),
            (self.type_in, 1),
        ):
            for confirm in (True, False):
                picking = self._picking(picking_type)
                picking.move_ids.product_uom_qty = quantity
                if confirm:
                    picking.action_confirm()
                pickings |= picking
        mixed = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": self.type_out.id,
                    "move_ids": [
                        Command.create(
                            {"product_id": self.product.id, "product_uom_qty": 1}
                        ),
                        Command.create(
                            {
                                "product_id": self.product.id,
                                "product_uom_qty": 99_999,
                            }
                        ),
                    ],
                }
            ]
        )
        mixed.action_confirm()
        pickings |= mixed
        pickings |= self.env["stock.picking"].create(
            [{"picking_type_id": self.type_out.id}]
        )
        pickings.flush_recordset()
        pickings.invalidate_recordset()

        for picking in pickings:
            with self.subTest(picking=picking.name):
                moves = picking.move_ids
                if moves:
                    moves._fields["forecast_availability"].compute_value(moves)
                qualifies = picking.state in (
                    "waiting",
                    "confirmed",
                    "assigned",
                ) and picking.picking_type_code in ("outgoing", "internal")
                expected = (
                    moves._get_availability_state(picking.date_planned)
                    if qualifies
                    else False
                )
                self.assertEqual(picking.products_availability_state, expected)


class TestPickingCreateValues(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.type_in = cls.env["stock.picking.type"].search(
            [("code", "=", "incoming"), ("warehouse_id", "=", cls.warehouse.id)],
            limit=1,
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Create values product", "is_storable": True}
        )

    def test_create_leaves_the_caller_values_alone(self):
        vals = {
            "picking_type_id": self.type_in.id,
            "date_planned": datetime(2030, 1, 1),
        }
        before = dict(vals)
        self.env["stock.picking"].create([vals])
        self.assertEqual(vals, before)

    @mute_logger("odoo.sql_db")
    def test_creating_twice_from_one_dict_gives_two_references(self):
        vals = {"picking_type_id": self.type_in.id}
        pickings = self.env["stock.picking"].create([vals, vals])
        pickings.flush_recordset()
        self.assertEqual(len(set(pickings.mapped("name"))), 2)

    @mute_logger("odoo.sql_db")
    def test_a_default_reference_does_not_collide_on_a_batch(self):
        pickings = (
            self.env["stock.picking"]
            .with_context(default_name="BATCH/0001")
            .create([{"picking_type_id": self.type_in.id}] * 2)
        )
        pickings.flush_recordset()
        self.assertEqual(len(set(pickings.mapped("name"))), 2)

    def test_a_default_reference_still_wins_for_a_single_record(self):
        picking = (
            self.env["stock.picking"]
            .with_context(default_name="SINGLE/0001")
            .create([{"picking_type_id": self.type_in.id}])
        )
        self.assertEqual(picking.name, "SINGLE/0001")

    def test_creating_a_transfer_keeps_the_dates_its_moves_asked_for(self):
        scheduled = datetime(2031, 5, 5, 12, 0, 0)
        picking = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": self.type_in.id,
                    "move_ids": [
                        Command.create(
                            {
                                "product_id": self.product.id,
                                "product_uom_qty": 1,
                                "date": scheduled,
                            }
                        )
                    ],
                }
            ]
        )
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.move_ids.date, scheduled)
        self.assertEqual(picking.date_planned, scheduled)

    def test_a_transfer_with_no_moves_is_still_scheduled(self):
        picking = self.env["stock.picking"].create(
            [{"picking_type_id": self.type_in.id}]
        )
        picking.flush_recordset()
        self.assertTrue(picking.date_planned)

    def test_an_explicit_scheduled_date_still_reaches_the_moves(self):
        scheduled = datetime(2031, 7, 7, 7, 0, 0)
        picking = self.env["stock.picking"].create(
            [
                {
                    "picking_type_id": self.type_in.id,
                    "date_planned": scheduled,
                    "move_ids": [
                        Command.create(
                            {"product_id": self.product.id, "product_uom_qty": 1}
                        )
                    ],
                }
            ]
        )
        picking.flush_recordset()
        picking.invalidate_recordset()
        self.assertEqual(picking.date_planned, scheduled)
        self.assertEqual(picking.move_ids.date, scheduled)


class TestPickingUserDependentFields(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.type_out = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing"), ("warehouse_id", "=", warehouse.id)],
            limit=1,
        )
        base_groups = [
            cls.env.ref("base.group_user").id,
            cls.env.ref("stock.group_stock_user").id,
        ]
        cls.privileged = cls.env["res.users"].create(
            {
                "name": "Warned user",
                "login": "picking_warned_user",
                "group_ids": [
                    Command.set(
                        [*base_groups, cls.env.ref("stock.group_warning_stock").id]
                    )
                ],
            }
        )
        cls.plain = cls.env["res.users"].create(
            {
                "name": "Plain user",
                "login": "picking_plain_user",
                "group_ids": [Command.set(base_groups)],
            }
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Warned partner", "picking_warn_msg": "Ring the bell twice"}
        )

    def _picking(self):
        picking = self.env["stock.picking"].create(
            [{"picking_type_id": self.type_out.id, "partner_id": self.partner.id}]
        )
        picking.flush_recordset()
        picking.invalidate_recordset()
        return picking

    def test_the_warning_does_not_leak_to_a_user_outside_the_group(self):
        picking = self._picking()
        self.assertIn(
            "Ring the bell twice",
            picking.with_user(self.privileged).picking_warning_text,
        )
        self.assertFalse(picking.with_user(self.plain).picking_warning_text)

    def test_the_warning_is_not_suppressed_by_an_earlier_reader(self):
        picking = self._picking()
        self.assertFalse(picking.with_user(self.plain).picking_warning_text)
        self.assertIn(
            "Ring the bell twice",
            picking.with_user(self.privileged).picking_warning_text,
        )
