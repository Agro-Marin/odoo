from odoo.exceptions import UserError

from .blocked_location_common import BlockedLocationCase


class TestQuantityVisibility(BlockedLocationCase):
    QTY_FIELDS = (
        "qty_available",
        "qty_free",
        "qty_available_virtual",
        "qty_incoming",
        "qty_outgoing",
    )

    def _qty_for(self, user, fname="qty_available", product=None, **context):
        product = (product or self.product).with_user(user).with_context(**context)
        product.invalidate_recordset(list(self.QTY_FIELDS))
        return product[fname]

    def _pending_move(self, reference, quantity, source, destination, final=None):
        vals = {
            "reference": reference,
            "product_id": self.product.id,
            "product_uom_qty": quantity,
            "product_uom_id": self.product.uom_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
        }
        if final is not None:
            vals["location_final_id"] = final.id
        move = self.Move.sudo().create(vals)
        move._action_confirm()
        return move

    def test_outgoing_blocked_stock_is_hidden(self):
        for location in (
            self.soft_out_location,
            self.soft_both_location,
            self.hard_block_location,
        ):
            with self.subTest(block_type=location.block_type):
                self._add_stock(location, 100.0)
                self.assertEqual(self._qty_for(self.vendor_user), 0.0)
                self._add_stock(location, -100.0)

    def test_soft_in_stock_stays_visible(self):
        self._add_stock(self.soft_in_location, 100.0)
        self.assertEqual(self._qty_for(self.vendor_user), 100.0)

    def test_children_of_a_blocked_zone_are_hidden(self):
        shelf = self._make_location("Hidden Shelf", parent=self.soft_out_location)
        self._add_stock(shelf, 77.0)
        self.assertEqual(self._qty_for(self.vendor_user), 0.0)
        self.assertEqual(self._qty_for(self.normal_user), 77.0)

    def test_stock_users_see_everything(self):
        self._add_stock(self.soft_out_location, 50.0)
        self._add_stock(self.hard_block_location, 30.0)
        self._add_stock(self.normal_location, 20.0)
        self.assertEqual(self._qty_for(self.normal_user), 100.0)

    def _sudo_qty(self, **context):
        product = (
            self.product.with_user(self.vendor_user).sudo().with_context(**context)
        )
        product.invalidate_recordset(list(self.QTY_FIELDS))
        return product.qty_available

    def test_bypass_context_disables_the_filter_for_system_flows(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.assertEqual(self._sudo_qty(bypass_blocked_locations=True), 100.0)

    def test_su_alone_does_not_disable_the_filter(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.assertEqual(self._sudo_qty(), 0.0)

    def test_bypass_context_is_ignored_for_a_plain_reader(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.assertEqual(
            self._qty_for(self.vendor_user, bypass_blocked_locations=True), 0.0
        )

    def test_every_computed_quantity_field_is_filtered(self):
        self._add_stock(self.soft_out_location, 100.0)
        self._pending_move(
            "incoming-blocked", 25.0, self.supplier_location, self.soft_out_location
        )
        self._pending_move(
            "outgoing-blocked", 10.0, self.soft_out_location, self.customer_location
        )
        for fname in self.QTY_FIELDS:
            with self.subTest(field=fname):
                self.assertEqual(self._qty_for(self.vendor_user, fname), 0.0)

    def test_no_blocked_locations_means_no_filtering(self):
        self.Location.sudo().search([("block_type", "!=", "none")]).write(
            {"block_type": "none"},
        )
        self._add_stock(self.normal_location, 42.0)
        self.assertEqual(self._qty_for(self.vendor_user), 42.0)

    def test_incoming_to_a_blocked_final_destination_is_hidden(self):
        self._pending_move(
            "two-step",
            33.0,
            self.supplier_location,
            self.normal_location,
            final=self.soft_out_location,
        )
        self.assertEqual(self._qty_for(self.normal_user, "qty_incoming"), 33.0)
        self.assertEqual(self._qty_for(self.vendor_user, "qty_incoming"), 0.0)

    def test_skip_in_progress_still_filters_done_destinations(self):
        self._add_stock(self.soft_out_location, 100.0)
        self.assertEqual(
            self._qty_for(self.vendor_user, skip_in_progress=True),
            0.0,
        )
        self._add_stock(self.normal_location, 25.0)
        self.assertEqual(
            self._qty_for(self.vendor_user, skip_in_progress=True),
            25.0,
        )

    def test_skip_in_progress_ignores_a_blocked_final_destination(self):
        self._pending_move(
            "skip-two-step",
            33.0,
            self.supplier_location,
            self.normal_location,
            final=self.soft_out_location,
        )
        self.assertEqual(
            self._qty_for(self.vendor_user, "qty_incoming", skip_in_progress=True),
            33.0,
            "with skip_in_progress core looks at location_dest_id only, so an "
            "unblocked current destination must stay visible",
        )

    def test_incoming_merely_passing_through_a_blocked_step_is_visible(self):
        self._pending_move(
            "through",
            33.0,
            self.supplier_location,
            self.soft_out_location,
            final=self.normal_location,
        )
        self.assertEqual(self._qty_for(self.vendor_user, "qty_incoming"), 33.0)


class TestInventoryCount(BlockedLocationCase):
    def _count(self, location, counted, user=None):
        return (
            self.Quant.with_user(user or self.normal_user)
            .with_context(inventory_mode=True)
            .create(
                {
                    "product_id": self.product.id,
                    "location_id": location.id,
                    "inventory_quantity": counted,
                },
            )
        )

    def _quant_rows(self, location):
        return self.Quant.sudo().search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", location.id),
            ],
        )

    def test_counting_a_blocked_location_does_not_duplicate_the_quant(self):
        for block_type in ("none", "soft_in", "soft_out", "soft_both", "hard"):
            with self.subTest(block_type=block_type):
                location = self._make_location(
                    f"Counted {block_type}", block_type=block_type
                )
                self._add_stock(location, 100.0)
                self.env.flush_all()

                counted = self._count(location, 100.0)

                self.assertEqual(
                    len(self._quant_rows(location)),
                    1,
                    f"{block_type}: counting created a duplicate quant row",
                )
                self.assertEqual(counted.inventory_diff_quantity, 0.0)

    def test_applying_a_count_in_a_blocked_location_keeps_the_quantity(self):
        location = self._make_location("Applied Count", block_type="soft_out")
        self._add_stock(location, 100.0)
        self.env.flush_all()

        counted = self._count(location, 100.0)
        counted.sudo().with_context(inventory_mode=True).action_apply_inventory()
        self.env.flush_all()

        self.assertEqual(self._on_hand(location), 100.0)

    def test_auto_apply_count_keeps_the_quantity(self):
        location = self._make_location("Auto Applied", block_type="soft_out")
        self._add_stock(location, 100.0)
        self.env.flush_all()

        self.Quant.with_user(self.normal_user).with_context(inventory_mode=True).create(
            {
                "product_id": self.product.id,
                "location_id": location.id,
                "inventory_quantity_auto_apply": 100.0,
            },
        )
        self.env.flush_all()

        self.assertEqual(len(self._quant_rows(location)), 1)
        self.assertEqual(self._on_hand(location), 100.0)

    def test_a_real_count_difference_still_applies(self):
        location = self._make_location("Real Difference", block_type="soft_out")
        self._add_stock(location, 100.0)
        self.env.flush_all()

        counted = self._count(location, 80.0)
        self.assertEqual(counted.inventory_diff_quantity, -20.0)
        counted.sudo().with_context(inventory_mode=True).action_apply_inventory()
        self.env.flush_all()

        self.assertEqual(self._on_hand(location), 80.0)

    def test_counting_a_hard_block_still_needs_the_override_to_apply(self):
        location = self._make_location("Hard Counted", block_type="hard")
        self._add_stock(location, 100.0)
        self.env.flush_all()

        counted = self._count(location, 80.0)
        with self.assertRaises(UserError):
            counted.with_user(self.normal_user).with_context(
                inventory_mode=True
            ).action_apply_inventory()
        self.assertEqual(self._on_hand(location), 100.0)


class TestTranslatedLabels(BlockedLocationCase):
    def test_error_label_uses_the_translated_selection(self):
        self.env["res.lang"]._activate_lang("es_MX")
        selection = (
            self.env["ir.model.fields.selection"]
            .sudo()
            .search(
                [
                    ("field_id.model", "=", "stock.location"),
                    ("field_id.name", "=", "block_type"),
                    ("value", "=", "hard"),
                ],
            )
        )
        selection.with_context(lang="es_MX").write({"name": "Bloqueo Duro"})
        self.env.flush_all()
        self.env.registry.clear_cache()

        spanish_user = self._make_user("Usuario ES", self.group_stock_user)
        spanish_user.lang = "es_MX"
        self._add_stock(self.hard_block_location, 50.0)

        quant = self.Quant.with_user(spanish_user).with_context(lang="es_MX")
        with self.assertRaises(UserError) as caught:
            quant._update_available_quantity(
                self.product, self.hard_block_location, -5.0
            )
        self.assertIn("Bloqueo Duro", str(caught.exception))
        self.assertNotIn("Hard Block", str(caught.exception))

    def test_reserved_quantity_uses_the_product_unit_precision(self):
        precision = (
            self.env["decimal.precision"]
            .sudo()
            .search(
                [("name", "=", "Product Unit")],
            )
        )
        precision.digits = 5
        self.env.invalidate_all()
        digits = self.Location._fields["reserved_qty_when_blocked"].get_digits(self.env)
        self.assertEqual(digits[1], 5)
