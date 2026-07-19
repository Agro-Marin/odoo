# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for the product/reports/wizards audit fixes (2026-07-17)."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


class TestAuditFixesProduct(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.product = cls.env["product.product"].create(
            {"name": "Audit Fix Product", "is_storable": True},
        )

    def _create_move(self, qty, location, location_dest, product=None, **extra_vals):
        product = product or self.product
        return self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": qty,
                "location_id": location.id,
                "location_dest_id": location_dest.id,
                **extra_vals,
            },
        )

    # ------------------------------------------------------------
    # Replenishment info wizard (#2 + record creation in compute)
    # ------------------------------------------------------------

    def test_replenishment_info_bare_wizard_computes(self):
        """A wizard without orderpoint/location must compute its JSON fields to
        False instead of crashing with 'Compute method failed to assign'."""
        wizard = self.env["stock.replenishment.info"].create({})
        self.assertFalse(wizard.json_replenishment_graph)
        self.assertFalse(wizard.json_lead_days)
        self.assertFalse(wizard.wh_replenishment_option_ids)

    def test_replenishment_info_options_created_on_create(self):
        """Warehouse replenishment options are real records created alongside
        the wizard (not from inside a compute)."""
        resupplied_wh = self.env["stock.warehouse"].create(
            {
                "name": "Resupplied WH",
                "code": "RSW",
                "resupply_wh_ids": [Command.set(self.warehouse.ids)],
            },
        )
        self.assertTrue(resupplied_wh.resupply_route_ids)
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.product.id,
                "warehouse_id": resupplied_wh.id,
                "location_id": resupplied_wh.lot_stock_id.id,
                "product_min_qty": 1,
                "product_max_qty": 5,
            },
        )
        wizard = self.env["stock.replenishment.info"].create(
            {"orderpoint_id": orderpoint.id},
        )
        options = wizard.wh_replenishment_option_ids
        self.assertEqual(len(options), len(resupplied_wh.resupply_route_ids))
        self.assertEqual(
            set(options.route_id.ids),
            set(resupplied_wh.resupply_route_ids.ids),
        )
        self.assertEqual(options.product_id, self.product)

    # ------------------------------------------------------------
    # Owners context on quantity fields (#34)
    # ------------------------------------------------------------

    def test_quantities_owner_context_scopes_moves(self):
        """The `owners` context must scope the move-based quantity fields
        (incoming/outgoing/virtual), not only the quant-based ones."""
        owner = self.env["res.partner"].create({"name": "Quant Owner"})
        other = self.env["res.partner"].create({"name": "Other Owner"})
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            self.stock_location,
            quantity=10,
            owner_id=owner,
        )

        move_in = self._create_move(5, self.supplier_location, self.stock_location)
        move_in._action_confirm()
        move_out = self._create_move(2, self.stock_location, self.customer_location)
        move_out._action_confirm()
        for move in (move_in, move_out):
            move.move_line_ids.unlink()
            self.env["stock.move.line"].create(
                {
                    "move_id": move.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.product.uom_id.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "quantity": move.product_uom_qty,
                    "owner_id": owner.id,
                },
            )
        self.assertIn(
            move_in.state,
            ("confirmed", "partially_available", "assigned", "waiting"),
        )

        product_as_owner = self.product.with_context(owners=[owner.id])
        self.assertEqual(product_as_owner.qty_available, 10)
        self.assertEqual(product_as_owner.qty_incoming, 5)
        self.assertEqual(product_as_owner.qty_outgoing, 2)
        self.assertEqual(product_as_owner.qty_available_virtual, 13)

        product_as_other = self.product.with_context(owners=[other.id])
        self.assertEqual(product_as_other.qty_available, 0)
        self.assertEqual(product_as_other.qty_incoming, 0)
        self.assertEqual(product_as_other.qty_outgoing, 0)
        self.assertEqual(product_as_other.qty_available_virtual, 0)

        # Empty owners list means "unowned stock only": neither the owned quant
        # nor the owner-scoped moves may count.
        product_unowned = self.product.with_context(owners=[])
        self.assertEqual(product_unowned.qty_available, 0)
        self.assertEqual(product_unowned.qty_incoming, 0)
        self.assertEqual(product_unowned.qty_outgoing, 0)

    # ------------------------------------------------------------
    # Batch qty_available inverse (#37)
    # ------------------------------------------------------------

    def test_inverse_qty_available_batches(self):
        """Setting qty_available on several products at once applies a single
        batched inventory adjustment covering all of them."""
        product_2 = self.env["product.product"].create(
            {"name": "Audit Fix Product 2", "is_storable": True},
        )
        (self.product | product_2).write({"qty_available": 4})
        self.assertEqual(self.product.qty_available, 4)
        self.assertEqual(product_2.qty_available, 4)
        quants = self.env["stock.quant"].search(
            [
                ("product_id", "in", (self.product | product_2).ids),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        self.assertEqual(len(quants), 2)
        self.assertEqual(quants.mapped("quantity"), [4, 4])

    # ------------------------------------------------------------
    # Scoped _clean_reservations on is_storable flip (#38)
    # ------------------------------------------------------------

    def test_is_storable_flip_scoped_clean_reservations(self):
        """Flipping is_storable only realigns the transitioning products'
        quants; unrelated products' (stale) reservations are left alone."""
        bystander = self.env["product.product"].create(
            {"name": "Bystander", "is_storable": True},
        )
        Quant = self.env["stock.quant"]
        Quant._update_available_quantity(bystander, self.stock_location, quantity=5)
        Quant._update_reserved_quantity(bystander, self.stock_location, 3)
        bystander_quant = Quant.search(
            [
                ("product_id", "=", bystander.id),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        self.assertEqual(bystander_quant.reserved_quantity, 3)

        template = self.env["product.template"].create(
            {"name": "Becomes storable", "type": "consu", "is_storable": False},
        )
        # Open picked move on the still-consumable product: the flip must
        # create its reserved quant even though the product has no quant row
        # yet (the move-line-only side of the realignment).
        move = self._create_move(
            5,
            self.stock_location,
            self.customer_location,
            product=template.product_variant_id,
        )
        move._action_confirm()
        move.quantity = 5

        template.write({"is_storable": True})
        self.assertTrue(template.is_storable)
        flipped_quants = Quant.search(
            [
                ("product_id", "=", template.product_variant_id.id),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        self.assertEqual(sum(flipped_quants.mapped("reserved_quantity")), 5)
        # The bystander's stale reservation (no move line backs it) must NOT
        # have been healed by a global clean pass.
        self.assertEqual(bystander_quant.reserved_quantity, 3)

    # ------------------------------------------------------------
    # Template inverse / create hardening (#41, create alignment)
    # ------------------------------------------------------------

    def test_template_inverse_qty_available_multi_variant_raises(self):
        attribute = self.env["product.attribute"].create(
            {
                "name": "Size",
                "value_ids": [
                    Command.create({"name": "S"}),
                    Command.create({"name": "M"}),
                ],
            },
        )
        template = self.env["product.template"].create(
            {
                "name": "Multi variant",
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        },
                    ),
                ],
            },
        )
        self.assertGreater(template.product_variant_count, 1)
        with self.assertRaises(UserError):
            template.write({"qty_available": 5})

    def test_template_create_qty_available_negative_raises(self):
        with self.assertRaises(UserError):
            self.env["product.template"].create(
                {
                    "name": "Negative qty",
                    "is_storable": True,
                    "qty_available": -5,
                },
            )

    def test_template_create_qty_available_tracked_raises(self):
        with self.assertRaises(UserError):
            self.env["product.template"].create(
                {
                    "name": "Tracked qty",
                    "is_storable": True,
                    "tracking": "lot",
                    "qty_available": 5,
                },
            )

    def test_template_create_qty_available_applies(self):
        template = self.env["product.template"].create(
            {
                "name": "Created with qty",
                "is_storable": True,
                "qty_available": 7,
            },
        )
        self.assertEqual(template.product_variant_id.qty_available, 7)

    # ------------------------------------------------------------
    # Routes diagram fallback (low)
    # ------------------------------------------------------------

    def test_action_view_routes_diagram_falls_back_to_self(self):
        template = self.product.product_tmpl_id
        action = template.action_view_routes_diagram()
        self.assertTrue(action)

    def test_action_view_routes_diagram_falls_back_to_active_id(self):
        template = self.product.product_tmpl_id
        action = (
            self.env["product.template"]
            .with_context(active_id=template.id)
            .action_view_routes_diagram()
        )
        self.assertTrue(action)

    # ------------------------------------------------------------
    # Forecasted report (#36, #40, #42, assert -> UserError)
    # ------------------------------------------------------------

    def test_forecasted_report_no_product_raises_usererror(self):
        with self.assertRaises(UserError):
            self.env["stock.forecasted_product_product"]._get_report_data()

    def test_forecasted_report_header_matches_lines_warehouse(self):
        """Header quantities must be computed for the same warehouse as the
        report lines (the resolved one), not under the ambient context."""
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Second WH", "code": "SWH"},
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            warehouse_2.lot_stock_id,
            quantity=7,
        )
        Report = self.env["stock.forecasted_product_product"]
        # No warehouse in context: the report resolves the company's first
        # warehouse; the header must show that warehouse's (empty) stock, not
        # the all-warehouses total.
        res = Report._get_report_data(product_ids=self.product.ids)
        self.assertEqual(res["product"][self.product.id]["quantity_on_hand"], 0)
        res = Report.with_context(warehouse_id=warehouse_2.id)._get_report_data(
            product_ids=self.product.ids,
        )
        self.assertEqual(res["product"][self.product.id]["quantity_on_hand"], 7)

    def test_forecasted_report_survives_rule_loop(self):
        """A misconfigured rule cycle on one product must not kill the whole
        report; the affected product simply gets no lead time."""
        route = self.env["stock.route"].create(
            {
                "name": "Looping route",
                "product_selectable": True,
                "rule_ids": [
                    Command.create(
                        {
                            "name": "Loop rule",
                            "action": "pull",
                            "procure_method": "make_to_order",
                            "location_src_id": self.stock_location.id,
                            "location_dest_id": self.stock_location.id,
                            "picking_type_id": self.warehouse.int_type_id.id,
                        },
                    ),
                ],
            },
        )
        self.product.route_ids = route
        # The loop must raise for a direct resolution ...
        with self.assertRaises(UserError):
            self.product._get_rules_from_location(self.stock_location)
        # ... but the report must survive it.
        res = self.env["stock.forecasted_product_product"]._get_report_data(
            product_ids=self.product.ids,
        )
        self.assertFalse(res["product"][self.product.id]["leadtime"])

    def test_prepare_report_line_read_gating(self):
        """read=False lines keep the resolved documents (consumed by mrp's MO
        overview) but skip the UI-only formatting."""
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.in_type_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_id": self.product.uom_id.id,
                            "product_uom_qty": 3,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        },
                    ),
                ],
            },
        )
        move_in = picking.move_ids
        Report = self.env["stock.forecasted_product_product"]

        line = Report._prepare_report_line(3, move_in=move_in, read=False)
        self.assertFalse(line["receipt_date"])
        self.assertEqual(line["move_in"], move_in)  # record, not read() dict
        self.assertEqual(line["uom_id"], self.product.uom_id)
        self.assertEqual(line["document_in"]["_name"], "stock.picking")
        self.assertEqual(line["document_in"]["id"], picking.id)
        self.assertFalse(line["document_in"]["name"])

        line = Report._prepare_report_line(3, move_in=move_in, read=True)
        self.assertTrue(line["receipt_date"])
        self.assertIsInstance(line["move_in"], dict)
        self.assertIsInstance(line["uom_id"], dict)
        self.assertEqual(line["document_in"]["name"], picking.display_name)

    # ------------------------------------------------------------
    # Reception report action_unassign hardening (#35)
    # ------------------------------------------------------------

    def test_reception_unassign_rejects_unlinked_move(self):
        out = self._create_move(2, self.stock_location, self.customer_location)
        out._action_confirm()
        report = self.env["report.stock.report_reception"]
        with self.assertRaises(UserError):
            report.action_unassign(out.id, 2, [])

    def test_reception_unassign_rejects_bad_state(self):
        out = self._create_move(2, self.stock_location, self.customer_location)
        out._action_confirm()
        out._action_cancel()
        report = self.env["report.stock.report_reception"]
        with self.assertRaises(UserError):
            report.action_unassign(out.id, 2, [])

    # ------------------------------------------------------------
    # Traceability allowed models (low)
    # ------------------------------------------------------------

    def test_traceability_allowed_models_no_mrp(self):
        report = self.env["stock.traceability.report"].create({})
        self.assertNotIn("mrp.production", report._get_line_allowed_models())
        # A client payload naming mrp.production must be refused gracefully
        # (no env KeyError 500 when mrp is not installed).
        self.assertEqual(
            report.get_lines(model_name="mrp.production", model_id=1),
            [],
        )

    # ------------------------------------------------------------
    # Relocation wizard company handling (low)
    # ------------------------------------------------------------

    def test_relocate_wizard_single_company(self):
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            self.stock_location,
            quantity=5,
        )
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", self.product.id),
                ("location_id", "=", self.stock_location.id),
            ],
        )
        wizard = self.env["stock.quant.relocate"].create(
            {"quant_ids": [Command.set(quant.ids)]},
        )
        self.assertEqual(wizard.company_id, self.stock_location.company_id)

    # ------------------------------------------------------------
    # Request count default date (low)
    # ------------------------------------------------------------

    def test_request_count_default_date_is_context_today(self):
        # UTC+14 and UTC-12: at any moment, at least one of them is on a
        # different calendar day than naive UTC, so a regression to
        # `Datetime.now` (UTC date) always fails one of the two assertions.
        for tz in ("Pacific/Kiritimati", "Etc/GMT+12"):
            wizard = self.env["stock.request.count"].with_context(tz=tz).create({})
            self.assertEqual(
                wizard.inventory_date,
                fields.Date.context_today(wizard),
                f"inventory_date default must be the user-timezone today ({tz})",
            )

    # ------------------------------------------------------------
    # Quant-only search path invariant (#39)
    # ------------------------------------------------------------

    def test_search_qty_available_new_positive_only(self):
        """The quant-only fast path only ever serves searches that 0 does not
        match (zero-matching ones are pre-routed); it must keep returning the
        right positive matches."""
        self.env["stock.quant"]._update_available_quantity(
            self.product,
            self.stock_location,
            quantity=6,
        )
        found = self.env["product.product"].search(
            [("qty_available", ">", 3), ("id", "in", self.product.ids)],
        )
        self.assertEqual(found, self.product)
        found = self.env["product.product"].search(
            [("qty_available", ">", 10), ("id", "in", self.product.ids)],
        )
        self.assertFalse(found)


@tagged("post_install", "-at_install")
class TestAuditProductMultiCompany(TransactionCase):
    """Company-creating tests run post-install: ``res.company.create``
    provisions payment providers whose selection fields need the full
    registry (e.g. ``delivery``'s ``custom_mode`` extension)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.product = cls.env["product.product"].create(
            {"name": "Audit MC Product", "is_storable": True},
        )
        cls.company_b = cls.env["res.company"].create({"name": "Audit Co B"})
        cls.env.user.company_ids |= cls.company_b
        cls.env_b = cls.env(
            context=dict(
                cls.env.context,
                allowed_company_ids=[cls.env.company.id, cls.company_b.id],
            ),
        )
        cls.warehouse_b = cls.env_b["stock.warehouse"].search(
            [("company_id", "=", cls.company_b.id)],
            limit=1,
        )

    def test_reception_unassign_rejects_cross_company(self):
        in_b = self.env_b["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 2,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.warehouse_b.lot_stock_id.id,
                "company_id": self.company_b.id,
            },
        )
        out = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 2,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        out._action_confirm()
        out.move_orig_ids = in_b
        report = self.env_b["report.stock.report_reception"]
        with self.assertRaises(UserError):
            report.action_unassign(out.id, 2, in_b.ids)

    def test_relocate_wizard_multi_company_raises(self):
        Quant = self.env_b["stock.quant"]
        Quant._update_available_quantity(
            self.product,
            self.stock_location,
            quantity=5,
        )
        Quant._update_available_quantity(
            self.product,
            self.warehouse_b.lot_stock_id,
            quantity=5,
        )
        quants = Quant.search(
            [
                ("product_id", "=", self.product.id),
                (
                    "location_id",
                    "in",
                    (self.stock_location | self.warehouse_b.lot_stock_id).ids,
                ),
            ],
        )
        self.assertEqual(len(quants.company_id), 2)
        with self.assertRaises(UserError):
            self.env_b["stock.quant.relocate"].create(
                {"quant_ids": [Command.set(quants.ids)]},
            )


@tagged("post_install", "-at_install")
class TestAuditLotPreview(TransactionCase):
    def test_preview_next_lot_does_not_consume(self):
        """The generator dialog preview must match the next real draw without
        advancing the sequence (legends interpolated server-side)."""
        product = self.env["product.product"].create(
            {"name": "Preview Product", "is_storable": True, "tracking": "serial"},
        )
        sequence = self.env["ir.sequence"].create(
            {"name": "Audit Lot Seq", "prefix": "LOT-%(year)s-", "padding": 4},
        )
        product.product_tmpl_id.lot_sequence_id = sequence
        number_before = sequence.number_next_actual
        preview = product.preview_next_lot()
        year = fields.Date.today().year
        self.assertEqual(preview, f"LOT-{year}-{number_before:04d}")
        self.assertEqual(
            sequence.number_next_actual,
            number_before,
            "preview must not consume the sequence",
        )
        self.assertEqual(
            sequence.next_by_id(),
            preview,
            "the next real draw must yield exactly the previewed value",
        )
