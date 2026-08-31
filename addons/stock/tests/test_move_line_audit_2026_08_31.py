from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.stock.models.stock_move_line import (
    LOGGED_RELATIONS,
    RENDERED_KEYS,
    RESERVATION_KEY_FIELDS,
)
from odoo.addons.stock.tests.common import TestStockCommon


class MoveLineAuditCase(TestStockCommon):
    """Fixtures for the audit findings.

    Every attempt runs as a real `stock.group_stock_user`, never the class
    environment: `TransactionCase.env` is SUPERUSER_ID and several guards in this
    area open with `if self.env.su: return`, so a su-bound fixture exercises a
    method that returns on its first line.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_user = cls.env["res.users"].create(
            {
                "name": "Audit Stock User",
                "login": "audit_stock_user_20260831",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("stock.group_stock_user").id,
                        ],
                    )
                ],
            }
        )
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.src = cls.warehouse.lot_stock_id
        cls.customer = cls.env.ref("stock.stock_location_customers")
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")

    def test_the_fixture_is_not_a_superuser(self):
        """Control. Everything else here is worthless if this fails."""
        self.assertFalse(self.env(user=self.stock_user).su)
        self.assertTrue(self.stock_user.has_group("stock.group_stock_user"))

    def _product(self, name, tracking="none"):
        return self.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "type": "consu",
                "tracking": tracking,
            }
        )

    def _stock(self, product, location, qty, lot=None):
        return self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "lot_id": lot.id if lot else False,
                "quantity": qty,
            }
        )

    def _outgoing(self, product, qty, user=None):
        env = self.env(user=user) if user else self.env
        picking = env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.src.id,
                "location_dest_id": self.customer.id,
            }
        )
        env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": qty,
                "location_id": self.src.id,
                "location_dest_id": self.customer.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        return picking


@tagged("post_install", "-at_install")
class TestWriteSurvivesAFreedSibling(MoveLineAuditCase):
    """`write()` must not read move lines that `write()` itself deleted.

    `_free_reservation`, reached from the settlements after `super().write()`,
    resolves an over-allocation by unlinking competing reservations, and its
    candidate search spans the table rather than only lines outside the batch.
    """

    def _done_line_and_open_line(self, open_qty, on_hand=10.0):
        product = self._product("Freed Sibling")
        self._stock(product, self.src, on_hand)
        open_picking = self._outgoing(product, open_qty)
        open_line = open_picking.move_line_ids
        done_picking = self._outgoing(product, 1.0)
        done_picking.move_line_ids.quantity = 1.0
        done_picking.move_ids.picked = True
        done_picking.button_validate()
        return done_picking.move_ids.move_line_ids, open_line

    def test_a_batch_mixing_a_done_and_an_open_line_does_not_raise_missing(self):
        done_line, open_line = self._done_line_and_open_line(2.0)
        batch = done_line | open_line
        self.assertEqual(sorted(batch.mapped("state")), ["assigned", "done"])

        batch.write({"quantity": 10.0})

        self.assertTrue(done_line.exists(), "the written done line must survive")

    def test_the_freed_sibling_really_is_unlinked(self):
        """Control. Proves the scenario reaches `_free_reservation` at all.

        Without it, the test above passes when nothing was ever freed.
        """
        done_line, open_line = self._done_line_and_open_line(2.0)
        (done_line | open_line).write({"quantity": 10.0})
        self.assertFalse(
            open_line.exists(),
            "the competing reservation should have been freed; if it survives, "
            "this fixture no longer exercises the read-after-delete path",
        )

    def test_an_ordinary_batch_write_is_untouched(self):
        """Control on the honest path: no freeing, nothing deleted."""
        product = self._product("Ordinary Batch")
        self._stock(product, self.src, 50.0)
        picking = self._outgoing(product, 5.0)
        lines = picking.move_line_ids
        lines.write({"quantity": 3.0})
        self.assertTrue(lines.exists())
        self.assertEqual(lines.quantity, 3.0)


@tagged("post_install", "-at_install")
class TestArchivedLotsAreNamed(MoveLineAuditCase):
    """A receipt naming an archived lot must say so, not accuse the user.

    `_resolve_done_lots` searched with `active_test` on while
    `stock.lot._check_unique_lot` and the UNIQUE index both consider archived
    rows, so the line fell through to creation and the user was told they had
    made a duplicate of a lot no view shows them.
    """

    def _receipt_with_lot_name(self, product, lot_name, qty=3.0):
        picking_type = self.warehouse.in_type_id
        picking_type.write({"use_create_lots": True, "use_existing_lots": True})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": qty,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        picking.action_confirm()
        move.move_line_ids.write({"quantity": qty, "lot_name": lot_name})
        move.picked = True
        return picking

    def test_an_archived_lot_is_named_in_the_error(self):
        product = self._product("Archived Lot Product", tracking="lot")
        lot = self.env["stock.lot"].create(
            {
                "name": "AUDIT-ARCHIVED",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        lot.active = False
        picking = self._receipt_with_lot_name(product, "AUDIT-ARCHIVED")

        with self.assertRaises(UserError) as caught:
            picking.button_validate()

        message = str(caught.exception)
        self.assertIn("AUDIT-ARCHIVED", message)
        self.assertIn("archived", message.lower())
        self.assertNotIn(
            "unique",
            message.lower(),
            "the user did not create a duplicate; they named an archived lot",
        )

    def test_a_fresh_lot_name_still_creates_the_lot(self):
        """Control: the ordinary path must be untouched by the archived branch."""
        product = self._product("Fresh Lot Product", tracking="lot")
        picking = self._receipt_with_lot_name(product, "AUDIT-FRESH")

        picking.button_validate()

        lot = self.env["stock.lot"].search(
            [("product_id", "=", product.id), ("name", "=", "AUDIT-FRESH")]
        )
        self.assertEqual(len(lot), 1)
        self.assertTrue(lot.active)

    def test_an_active_lot_of_the_same_name_is_reused_not_recreated(self):
        """Control: an existing ACTIVE lot must still resolve, not raise."""
        product = self._product("Active Lot Product", tracking="lot")
        lot = self.env["stock.lot"].create(
            {
                "name": "AUDIT-ACTIVE",
                "product_id": product.id,
                "company_id": self.env.company.id,
            }
        )
        picking = self._receipt_with_lot_name(product, "AUDIT-ACTIVE")

        picking.button_validate()

        self.assertEqual(picking.move_line_ids.lot_id, lot)


@tagged("post_install", "-at_install")
class TestSerialOnchangeDoesNotCollideWithItself(MoveLineAuditCase):
    """A line must not be compared against its own saved serial.

    In an onchange `self` is a NewId while `picking.move_line_ids` are the stored
    rows, so subtracting `self` removed nothing and the line warned about a
    duplicate of itself.
    """

    def _serial_receipt(self):
        product = self._product("Serial Product", tracking="serial")
        picking_type = self.warehouse.in_type_id
        picking_type.write({"use_create_lots": True, "use_existing_lots": True})
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": product.id,
                "product_uom_qty": 1.0,
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        picking.action_confirm()
        line = move.move_line_ids
        line.write({"quantity": 1.0, "lot_name": "SN-1"})
        return picking, move, line

    def _warning_for(self, line, move, picking, serial):
        values = {
            "id": line.id,
            "product_id": line.product_id.id,
            "quantity": 1.0,
            "picking_id": picking.id,
            "move_id": move.id,
            "lot_id": False,
            "lot_name": serial,
        }
        spec = dict.fromkeys(
            ["lot_name", "lot_id", "product_id", "quantity", "picking_id", "move_id"],
            "1",
        )
        result = line.onchange(values, ["lot_name"], spec)
        return (result.get("warning") or {}).get("message")

    def test_re_entering_a_lines_own_serial_does_not_warn(self):
        picking, move, line = self._serial_receipt()
        self.assertIsNone(self._warning_for(line, move, picking, "SN-1"))

    def test_a_genuinely_new_serial_does_not_warn(self):
        """Control on the honest path."""
        picking, move, line = self._serial_receipt()
        self.assertIsNone(self._warning_for(line, move, picking, "SN-9"))

    def test_a_real_duplicate_across_two_lines_still_warns(self):
        """Control: the check must keep catching what it exists to catch."""
        picking, move, line = self._serial_receipt()
        second = self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "picking_id": picking.id,
                "product_id": line.product_id.id,
                "product_uom_id": line.product_uom_id.id,
                "quantity": 1.0,
                "lot_name": "SN-2",
                "location_id": self.supplier.id,
                "location_dest_id": self.src.id,
            }
        )
        warning = self._warning_for(second, move, picking, "SN-1")
        self.assertIsNotNone(warning)
        self.assertIn("same serial number twice", warning)


@tagged("post_install", "-at_install")
class TestReservationKeyHasOneDefinition(MoveLineAuditCase):
    """`_reservation_key` is the only place the key's shape is spelled out."""

    def test_overrides_replace_only_the_named_fields(self):
        product = self._product("Key Product")
        self._stock(product, self.src, 10.0)
        picking = self._outgoing(product, 2.0)
        line = picking.move_line_ids

        stored = line._reservation_key()
        moved = line._reservation_key({"location_id": self.customer})

        self.assertEqual(len(stored), len(RESERVATION_KEY_FIELDS))
        self.assertEqual(stored[0], moved[0], "product must be untouched")
        self.assertEqual(moved[1], self.customer)
        self.assertEqual(stored[2:], moved[2:], "lot/package/owner untouched")

    def test_an_unrelated_override_key_is_ignored(self):
        """`updates` also carries location_dest_id and product_uom_id."""
        product = self._product("Key Product Two")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids

        self.assertEqual(
            line._reservation_key(),
            line._reservation_key({"location_dest_id": self.customer}),
        )

    def test_rendered_keys_tracks_logged_relations(self):
        """The set the chatter gate reads is derived, not a second copy."""
        for _field, rendered in LOGGED_RELATIONS:
            self.assertIn(rendered, RENDERED_KEYS)
        self.assertIn("quantity", RENDERED_KEYS)
        self.assertNotIn(
            "product_uom_qty",
            RENDERED_KEYS,
            "stock.move.line has no such field; it was a leftover",
        )


@tagged("post_install", "-at_install")
class TestSynchronizeQuantSignature(MoveLineAuditCase):
    """`_synchronize_quant` names its overrides instead of collecting kwargs."""

    def _line(self):
        product = self._product("Sync Product")
        self._stock(product, self.src, 10.0)
        return self._outgoing(product, 2.0).move_line_ids

    def test_a_misspelled_override_is_a_type_error(self):
        line = self._line()
        with self.assertRaises(TypeError):
            line._synchronize_quant(-1.0, self.src, packge=False)

    def test_the_named_override_still_works(self):
        """Control: the one override production uses must keep working."""
        line = self._line()
        available, _in_date = line._synchronize_quant(-1.0, self.src, package=False)
        self.assertIsNotNone(available)

    def test_no_caller_asks_for_the_removed_action(self):
        line = self._line()
        with self.assertRaises(TypeError):
            line._synchronize_quant(-1.0, self.src, action="reserved")


@tagged("post_install", "-at_install")
class TestWriteGuardsStillHold(MoveLineAuditCase):
    """Regression net for the two guards fixed earlier in this audit.

    Not this change, but the same file: keeping them here means a later edit to
    `write()` cannot quietly reopen either without a red test.
    """

    def test_changing_a_bound_lines_product_is_refused(self):
        product = self._product("Bound Product")
        other = self._product("Other Product")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids
        with self.assertRaises(UserError):
            line.with_user(self.stock_user).write({"product_id": other.id})

    def test_a_supplied_draft_state_does_not_lift_the_refusal(self):
        product = self._product("Bound Product Two")
        other = self._product("Other Product Two")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids
        with self.assertRaises(UserError):
            line.with_user(self.stock_user).write(
                {"product_id": other.id, "state": "draft"}
            )

    def test_writing_the_same_product_still_succeeds(self):
        """Control: the guard fires on a change, not on the field's presence."""
        product = self._product("Same Product")
        self._stock(product, self.src, 10.0)
        line = self._outgoing(product, 2.0).move_line_ids
        line.with_user(self.stock_user).write({"product_id": product.id})
        self.assertEqual(line.product_id, product)
