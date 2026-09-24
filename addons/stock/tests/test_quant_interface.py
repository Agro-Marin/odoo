from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tests import tagged

from odoo.addons.stock.const import (
    CONTEXT_BLOCK_COMPLETING,
    CONTEXT_BLOCK_EXCLUDED_TYPES,
    INTERNAL_CONTEXT_FLAG,
    get_internal_payload,
    is_internal_flag,
    read_internal_payload,
)
from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestQuantDisplayName(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = (
            cls.env["stock.warehouse"]
            .search([("company_id", "=", cls.env.company.id)], limit=1)
            .lot_stock_id
        )
        cls.product = cls.env["product.product"].create(
            {"name": "qdn-product", "is_storable": True, "tracking": "lot"}
        )
        cls.lot = cls.env["stock.lot"].create(
            {"name": "QDN-LOT", "product_id": cls.product.id}
        )
        cls.quant = cls.Quant.create(
            {
                "product_id": cls.product.id,
                "location_id": cls.loc.id,
                "lot_id": cls.lot.id,
                "quantity": 1.0,
            }
        )

    def _both(self):
        return (
            self.quant.display_name,
            self.quant.with_context(formatted_display_name=True).display_name,
        )

    def test_display_name_does_not_depend_on_which_context_was_read_first(self):
        self.env.flush_all()
        self.env.invalidate_all()
        plain_first, formatted_after = self._both()
        self.env.invalidate_all()
        formatted_first = self.quant.with_context(
            formatted_display_name=True
        ).display_name
        plain_after = self.quant.display_name
        self.assertEqual(
            plain_first,
            plain_after,
            "the plain display_name must not change because a formatted read"
            " happened first in the same transaction",
        )
        self.assertEqual(
            formatted_after,
            formatted_first,
            "the formatted display_name must not change because a plain read"
            " happened first in the same transaction",
        )
        self.assertNotEqual(
            plain_first,
            formatted_first,
            "the fixture must actually distinguish the two renderings, or this"
            " test passes for the wrong reason",
        )

    def test_the_two_renderings_are_the_documented_ones(self):
        self.env.invalidate_all()
        self.assertEqual(
            self.quant.display_name, f"{self.loc.display_name} - {self.lot.name}"
        )
        self.env.invalidate_all()
        self.assertEqual(
            self.quant.with_context(formatted_display_name=True).display_name,
            f"{self.loc.name}\t--{self.lot.name}--",
        )

    def test_an_unsaved_quant_has_no_name_in_either_context(self):
        values = {"product_id": self.product.id, "location_id": self.loc.id}
        self.assertEqual(self.Quant.new(values).display_name, "")
        self.assertEqual(
            self.Quant.with_context(formatted_display_name=True)
            .new(values)
            .display_name,
            "",
            "an unsaved quant named itself after its location in the formatted"
            " branch only, because the guard sat inside the other one",
        )

    def test_a_formatted_read_does_not_poison_a_user_facing_error(self):
        self.env.user.group_ids = [(4, self.env.ref("stock.group_stock_user").id)]
        self.env.invalidate_all()
        self.quant.with_context(formatted_display_name=True).display_name
        line = {
            "product_id": self.product.id,
            "location_id": self.loc.id,
            "lot_id": self.lot.id,
            "inventory_quantity": 1.0,
        }
        with self.assertRaises(UserError) as caught:
            self.Quant.with_context(inventory_mode=True).create([line, dict(line)])
        message = str(caught.exception)
        self.assertNotIn(
            "\t", message, "the formatted rendering leaked into an error dialog"
        )
        self.assertIn(self.loc.display_name, message)


@tagged("post_install", "-at_install")
class TestQuantBlockedContextProtocol(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]

    def test_the_payload_round_trips_through_the_shared_helpers(self):
        context = {CONTEXT_BLOCK_EXCLUDED_TYPES: get_internal_payload(("soft_out",))}
        self.assertEqual(
            read_internal_payload(context, CONTEXT_BLOCK_EXCLUDED_TYPES),
            ("soft_out",),
        )

    def test_an_empty_payload_is_distinguishable_from_an_absent_one(self):
        context = {CONTEXT_BLOCK_EXCLUDED_TYPES: get_internal_payload(())}
        self.assertEqual(
            read_internal_payload(context, CONTEXT_BLOCK_EXCLUDED_TYPES), ()
        )
        self.assertIsNone(read_internal_payload({}, CONTEXT_BLOCK_EXCLUDED_TYPES))

    def test_a_forged_payload_is_refused(self):
        for forged in ((True, ["soft_out"]), ["soft_out"], "soft_out", True):
            with self.subTest(forged=forged):
                self.assertIsNone(
                    read_internal_payload(
                        {CONTEXT_BLOCK_EXCLUDED_TYPES: forged},
                        CONTEXT_BLOCK_EXCLUDED_TYPES,
                    ),
                    "only a value written by get_internal_payload() may be trusted",
                )

    def test_the_two_shapes_stay_distinct(self):
        flagged = {CONTEXT_BLOCK_COMPLETING: INTERNAL_CONTEXT_FLAG}
        self.assertTrue(is_internal_flag(flagged, CONTEXT_BLOCK_COMPLETING))
        self.assertIsNone(
            read_internal_payload(flagged, CONTEXT_BLOCK_COMPLETING),
            "a bare marker carries no payload and must not read as one",
        )
        carried = {CONTEXT_BLOCK_EXCLUDED_TYPES: get_internal_payload(())}
        self.assertFalse(
            is_internal_flag(carried, CONTEXT_BLOCK_EXCLUDED_TYPES),
            "a payload is deliberately not a bare marker",
        )

    def test_the_model_uses_the_shared_protocol(self):
        scoped = self.Quant._with_block_gather_context()
        self.assertEqual(
            scoped._get_block_types_excluded(),
            read_internal_payload(scoped.env.context, CONTEXT_BLOCK_EXCLUDED_TYPES),
        )
        self.assertIsNone(self.Quant._get_block_types_excluded())


@tagged("post_install", "-at_install")
class TestQuantContracts(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = (
            cls.env["stock.warehouse"]
            .search([("company_id", "=", cls.env.company.id)], limit=1)
            .lot_stock_id
        )

    def test_action_view_orderpoints_names_the_quant_when_given_several(self):
        products = self.env["product.product"].create(
            [{"name": f"qc-avo-{i}", "is_storable": True} for i in range(2)]
        )
        quants = self.Quant.create(
            [
                {"product_id": p.id, "location_id": self.loc.id, "quantity": 1.0}
                for p in products
            ]
        )
        with self.assertRaises(ValueError) as caught:
            quants.action_view_orderpoints()
        self.assertIn(
            "stock.quant",
            str(caught.exception),
            "the guard must name the receiver, not whatever field it read first",
        )
        self.assertTrue(quants[0].action_view_orderpoints())

    def test_the_serial_check_is_private(self):
        self.assertFalse(
            hasattr(self.Quant, "check_quantity"),
            "check_quantity had one caller -- stock.move._check_quantity -- and"
            " no XML reference, so a public spelling only widens the API",
        )
        self.assertTrue(hasattr(self.Quant, "_check_quantity"))

    def test_the_create_allowlist_holds_only_settable_fields(self):
        for name in self.Quant._get_inventory_fields_create():
            if name.startswith("x_"):
                continue
            field = self.Quant._fields[name]
            with self.subTest(field=name):
                self.assertTrue(
                    field.store or field.inverse,
                    f"{name} can never be persisted, so permitting it at create"
                    f" only widens the allowlist",
                )

    def test_the_aggregate_barcode_follows_the_order_it_was_given(self):
        self.env["ir.config_parameter"].sudo().set_param("stock.barcode_separator", ";")
        products = self.env["product.product"].create(
            [
                {
                    "name": f"qc-agg-{i}",
                    "is_storable": True,
                    "tracking": "serial",
                    "barcode": f"QCAGG-P{i}",
                }
                for i in range(2)
            ]
        )
        quants = self.Quant
        for index, product in enumerate(products):
            for suffix in range(2):
                lot = self.env["stock.lot"].create(
                    {"name": f"qcagg-{index}{suffix}", "product_id": product.id}
                )
                quants |= self.Quant.create(
                    {
                        "product_id": product.id,
                        "location_id": self.loc.id,
                        "lot_id": lot.id,
                        "quantity": 1.0,
                    }
                )
        self.env.flush_all()
        grouped = quants.get_aggregate_barcodes()[0]
        self.assertEqual(
            grouped.count("QCAGG-P0"),
            1,
            "a product barcode is written once per contiguous run of its quants",
        )
        interleaved = self.Quant.browse(
            [quants[0].id, quants[2].id, quants[1].id, quants[3].id]
        ).get_aggregate_barcodes()[0]
        self.assertEqual(
            interleaved.count("QCAGG-P0"),
            2,
            "an interleaved recordset repeats the product barcode -- the caller"
            " owns the order, and this is the documented consequence of not"
            " grouping by product before calling",
        )
        self.assertLess(
            grouped.index("qcagg-01"),
            grouped.index("QCAGG-P1"),
            "the emitted sequence must follow the recordset, not a re-sort",
        )

    def test_the_reservation_lock_follows_the_removal_order(self):
        lifo = self.env["product.removal"].search([("method", "=", "lifo")], limit=1)
        category = self.env["product.category"].create(
            {"name": "qc-lifo", "removal_strategy_id": lifo.id}
        )
        product = self.env["product.product"].create(
            {"name": "qc-lifo-product", "is_storable": True, "categ_id": category.id}
        )
        older = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 1.0}
        )
        self.env.flush_all()
        newer = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 1.0}
        )
        self.env.flush_all()
        older.sudo().in_date = "2020-01-01 00:00:00"
        newer.sudo().in_date = "2025-01-01 00:00:00"
        self.env.flush_all()
        gathered = self.Quant.sudo()._gather(product, self.loc, strict=True)
        self.assertEqual(
            gathered.ids[0],
            newer.id,
            "LIFO must gather the newest quant first, or the rest of this test"
            " is asserting nothing",
        )
        self.assertEqual(
            gathered._lock_one_for_reservation(0).ids,
            [newer.id],
            "the lock takes the first row of the RECORDSET, which is the"
            " removal-strategy order; if _as_query ever stopped preserving that"
            " order, reservation would silently move to the lowest id",
        )


@tagged("post_install", "-at_install")
class TestQuantExpirationBoundary(TestStockCommon):
    def test_stock_never_names_a_product_expiry_field(self):
        import inspect

        from odoo.addons.stock.models import stock_quant, stock_quant_reservation

        for module in (stock_quant, stock_quant_reservation):
            self.assertNotIn(
                "removal_date",
                inspect.getsource(module),
                f"{module.__name__} must reach expiry through "
                "_get_domain_expiration / _filtered_not_expired, not by name",
            )

    def test_the_base_hooks_are_neutral(self):
        quant = self.env["stock.quant"]
        self.assertEqual(quant._get_domain_expiration(), Domain.TRUE)
        product = self.env["product.product"].create(
            {"name": "qaud-expiry", "is_storable": True}
        )
        quant._update_available_quantity(product, self.stock_location, quantity=1)
        self.env.flush_all()
        quants = quant.search([("product_id", "=", product.id)])
        self.assertEqual(quants._filtered_not_expired(), quants)


@tagged("post_install", "-at_install")
class TestQuantActionDomain(TestStockCommon):
    def test_the_quants_action_keeps_the_action_domain(self):
        action = self.env.ref("stock.stock_quant_action").sudo()
        action.domain = "[('quantity', '>', 0)]"
        self.env.flush_all()
        built = (
            self.env["stock.quant"]
            .with_context(skip_quant_tasks=True)
            ._prepare_action_quants()
        )
        conditions = [
            (condition.field_expr, condition.operator, condition.value)
            for condition in Domain(built["domain"]).iter_conditions()
        ]
        self.assertIn(
            ("quantity", ">", 0),
            conditions,
            "the company narrowing must be added to the action's domain, not "
            "written over it",
        )
        self.assertIn(
            "product_id.company_id",
            [field for field, _operator, _value in conditions],
        )


@tagged("post_install", "-at_install")
class TestQuantFormLookups(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def test_dropping_the_lot_reads_the_on_hand_without_it(self):
        untracked = self.env["product.product"].create(
            {"name": "qaud-form-untracked", "is_storable": True}
        )
        tracked = self.env["product.product"].create(
            {"name": "qaud-form-tracked", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-form-lot", "product_id": tracked.id}
        )
        self.Quant._update_available_quantity(tracked, self.loc, quantity=7, lot_id=lot)
        self.Quant._update_available_quantity(untracked, self.loc, quantity=3)
        self.env.flush_all()
        self.env.invalidate_all()

        form = self.Quant.new(
            {
                "location_id": self.loc.id,
                "product_id": untracked.id,
                "lot_id": lot.id,
            }
        )
        form._onchange_location_or_product_id()

        self.assertFalse(form.lot_id, "a lot of another product must be dropped")
        self.assertEqual(
            form.quantity,
            3.0,
            "the on hand must be read for the identity the form ends up with, "
            "not for the lot that was just removed",
        )

    def test_keeping_the_lot_still_reads_that_lot(self):
        tracked = self.env["product.product"].create(
            {"name": "qaud-form-keep", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-form-keep-lot", "product_id": tracked.id}
        )
        self.Quant._update_available_quantity(tracked, self.loc, quantity=7, lot_id=lot)
        self.Quant._update_available_quantity(tracked, self.loc, quantity=99)
        self.env.flush_all()
        self.env.invalidate_all()

        form = self.Quant.new(
            {
                "location_id": self.loc.id,
                "product_id": tracked.id,
                "lot_id": lot.id,
            }
        )
        form._onchange_location_or_product_id()
        self.assertEqual(form.lot_id, lot)
        self.assertEqual(
            form.quantity,
            7.0,
            "a kept lot reads its own quantity, not the untracked stock beside it",
        )

    def test_history_is_scoped_to_the_quant_owner(self):
        owner = self.env["res.partner"].create({"name": "qaud-history-owner"})
        product = self.env["product.product"].create(
            {"name": "qaud-history", "is_storable": True}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=4, owner_id=owner
        )
        self.env.flush_all()
        quant = self.Quant.search(
            [("product_id", "=", product.id), ("owner_id", "=", owner.id)]
        )
        action = quant.action_view_stock_moves()
        conditions = {
            condition.field_expr
            for condition in Domain(action["domain"]).iter_conditions()
        }
        self.assertIn(
            "owner_id",
            conditions,
            "owner_id is part of the quant's identity in _get_move_line_match_key and "
            "_get_reservation_key; history cannot be the one place it is dropped",
        )

    def test_the_constraint_methods_are_named_and_scoped_as_constraints(self):
        model = type(self.env["stock.quant"])
        for name in ("_check_location_id", "_check_product_id", "_check_lot_id"):
            self.assertTrue(
                hasattr(model, name), f"{name} must exist under the §2.4 spelling"
            )
        for name in ("check_location_id", "check_product_id", "check_lot_id"):
            self.assertFalse(
                hasattr(model, name),
                f"{name} must not survive as a public alias -- a public method is "
                "callable over RPC",
            )
        constrained = {
            method.__name__ for method in self.env["stock.quant"]._constraint_methods
        }
        for name in ("_check_location_id", "_check_product_id", "_check_lot_id"):
            self.assertIn(
                name, constrained, f"{name} must still be registered as a constraint"
            )
