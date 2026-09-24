from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestStockActivity(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.productA.responsible_id = cls.env.user
        cls.pick = cls.PickingObj.create(
            {
                "picking_type_id": cls.picking_type_int.id,
                "location_id": cls.stock_location.id,
                "location_dest_id": cls.output_location.id,
            }
        )
        cls.ship = cls.PickingObj.create(
            {
                "picking_type_id": cls.picking_type_out.id,
                "location_id": cls.output_location.id,
                "location_dest_id": cls.customer_location.id,
            }
        )

    def _move(self, picking, qty, **values):
        return self.MoveObj.create(
            {
                "product_id": self.productA.id,
                "product_uom_qty": qty,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                **values,
            }
        )

    def _documents(self, changes):
        return self.env["mixin.stock.activity"]._get_log_activity_documents(
            changes,
            "move_dest_ids",
            "DOWN",
            lambda move: (move.picking_id, move.product_id.responsible_id),
        )

    def _warning_notes(self, record):
        return record.activity_ids.filtered(
            lambda activity: (
                activity.activity_type_id
                == self.env.ref("mail.mail_activity_data_warning")
            )
        ).mapped("note")

    def test_every_origin_of_one_destination_reaches_the_document(self):
        first = self._move(self.pick, 5.0)
        second = self._move(self.pick, 4.0)
        self._move(self.ship, 9.0, move_orig_ids=[(6, 0, (first | second).ids)])
        changes = {first: (2.0, 5.0), second: (3.0, 4.0)}

        documents = self._documents(changes)

        self.assertEqual(list(documents), [(self.ship, self.env.user)])
        self.assertEqual(documents[self.ship, self.env.user].changes, changes)

    def test_the_note_lists_every_short_origin_of_one_destination(self):
        first = self._move(self.pick, 5.0)
        second = self._move(self.pick, 4.0)
        self._move(self.ship, 9.0, move_orig_ids=[(6, 0, (first | second).ids)])

        self.pick._log_less_quantities_than_expected(
            {first: (2.0, 5.0), second: (3.0, 4.0)}
        )

        [note] = self._warning_notes(self.ship)
        self.assertEqual(note.count("<li"), 2, note)
        self.assertIn("instead of 5.0", note)
        self.assertIn("instead of 4.0", note)

    def test_an_origin_split_over_two_destinations_is_listed_once(self):
        origin = self._move(self.pick, 5.0)
        dests = self._move(self.ship, 3.0) | self._move(self.ship, 2.0)
        origin.move_dest_ids = dests

        documents = self._documents({origin: (1.0, 5.0)})
        document = documents[self.ship, self.env.user]
        self.assertEqual(document.records, dests)
        self.assertEqual(document.changes, {origin: (1.0, 5.0)})

        self.pick._log_less_quantities_than_expected({origin: (1.0, 5.0)})
        [note] = self._warning_notes(self.ship)
        self.assertEqual(note.count("<li"), 1, note)
