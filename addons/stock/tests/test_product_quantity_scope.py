"""Regression tests for the `product.product` quantity/scope audit (2026-08-12).

Each test names the defect it pins. The audit that produced them is
`agromarin-knowledge/research/2026-08-12-stock-product-product-audit.md`; every case
here failed before the corresponding fix and none was covered by an existing test.
"""

import datetime

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductQuantityScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.product = cls.env["product.product"].create(
            {"name": "Scope Test Product", "is_storable": True, "type": "consu"},
        )

    def _stock_up(self, product, qty, location=None):
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": product.id,
                "location_id": (location or self.stock_location).id,
                "inventory_quantity": qty,
            }
        )._apply_inventory()

    def test_boolean_location_context_is_rejected_in_python(self):
        """A boolean reached the recursive CTE as `id = ANY(true)`.

        `isinstance(True, int)` holds, so the unguarded int test let a boolean into
        the id set and Postgres answered with
        `UndefinedFunction: operator does not exist: integer = boolean`.
        """
        for key in ("location", "warehouse_id", "search_location", "search_warehouse"):
            with self.subTest(context_key=key):
                with self.assertRaises(ValueError):
                    self.product.with_context(**{key: True}).qty_available

    def test_unresolvable_location_context_never_raises_missing_error(self):
        """Every unresolvable filter must reach the same empty scope.

        A nonexistent id used to be silent on its own but fatal alongside
        `warehouse_id`, because only that branch dereferenced the browsed record.
        """
        self._stock_up(self.product, 7)
        self.assertEqual(self.product.qty_available, 7)
        cases = (
            {"location": "No Such Location"},
            {"location": 999_999_999},
            {"warehouse_id": 999_999_999},
            {"warehouse_id": self.warehouse.id, "location": 999_999_999},
            {"warehouse_id": 999_999_999, "location": self.stock_location.id},
        )
        for context in cases:
            with self.subTest(context=context):
                product = self.product.with_context(**context)
                product.invalidate_recordset()
                self.assertEqual(product.qty_available, 0.0)

    def test_valid_location_context_still_resolves(self):
        """The `.exists()` filter must not drop ids that do exist."""
        self._stock_up(self.product, 7)
        for context in (
            {"location": self.stock_location.id},
            {"location": self.stock_location.name},
            {"warehouse_id": self.warehouse.id},
        ):
            with self.subTest(context=context):
                product = self.product.with_context(**context)
                product.invalidate_recordset()
                self.assertEqual(product.qty_available, 7.0)

    def test_strict_scope_already_skips_in_progress(self):
        """`skip_in_progress` is a no-op under `strict` by construction.

        The strict branch never introduces the `location_final_id` reasoning that
        `skip_in_progress` exists to remove, so its default output already equals the
        shortcut's. Pinned because it reads like a dropped context key.
        """
        Product = self.env["product.product"]
        location_ids = self.stock_location.ids
        strict = Product.with_context(strict=True)._get_domain_locations_new(
            location_ids
        )
        strict_skipping = Product.with_context(
            strict=True, skip_in_progress=True
        )._get_domain_locations_new(location_ids)
        self.assertEqual(repr(strict), repr(strict_skipping))
        self.assertNotIn("location_final_id", repr(strict))
        plain = Product._get_domain_locations_new(location_ids)
        skipping = Product.with_context(
            skip_in_progress=True
        )._get_domain_locations_new(location_ids)
        self.assertIn("location_final_id", repr(plain))
        self.assertNotIn("location_final_id", repr(skipping))

    def test_inverse_qty_available_uses_the_products_own_company(self):
        """The adjustment must land in the product's company, not the active one.

        Resolving the warehouse from `self.env.company` paired a company-B product
        with company-A's stock location, which the multi-company check rejected with
        a message blaming the warehouse setup.
        """
        company_b = self.env["res.company"].create({"name": "Scope Co B"})
        warehouse_b = self.env["stock.warehouse"].search(
            [("company_id", "=", company_b.id)], limit=1
        ) or self.env["stock.warehouse"].create(
            {"name": "Scope WH B", "code": "SWB", "company_id": company_b.id}
        )
        product_b = self.env["product.product"].create(
            {
                "name": "Scope Co B Product",
                "is_storable": True,
                "type": "consu",
                "company_id": company_b.id,
            }
        )
        self.assertNotEqual(self.env.company, company_b)
        product_b.with_context(
            allowed_company_ids=[self.env.company.id, company_b.id]
        ).qty_available = 3.0
        product_b.flush_recordset()
        quant = self.env["stock.quant"].search(
            [
                ("product_id", "=", product_b.id),
                ("location_id.usage", "=", "internal"),
            ]
        )
        self.assertEqual(quant.location_id, warehouse_b.lot_stock_id)
        self.assertEqual(quant.company_id, company_b)

    def test_inverse_qty_available_batches_two_companies_at_once(self):
        """A mixed-company batch resolves one warehouse per company, not per product."""
        company_b = self.env["res.company"].create({"name": "Scope Co B2"})
        warehouse_b = self.env["stock.warehouse"].search(
            [("company_id", "=", company_b.id)], limit=1
        ) or self.env["stock.warehouse"].create(
            {"name": "Scope WH B2", "code": "SB2", "company_id": company_b.id}
        )
        product_b = self.env["product.product"].create(
            {
                "name": "Scope B2 Product",
                "is_storable": True,
                "type": "consu",
                "company_id": company_b.id,
            }
        )
        products = self.product | product_b
        products.with_context(
            allowed_company_ids=[self.env.company.id, company_b.id]
        ).qty_available = 5.0
        products.flush_recordset()
        by_product = {
            quant.product_id: quant.location_id
            for quant in self.env["stock.quant"].search(
                [
                    ("product_id", "in", products.ids),
                    ("location_id.usage", "=", "internal"),
                ]
            )
        }
        self.assertEqual(by_product[self.product], self.stock_location)
        self.assertEqual(by_product[product_b], warehouse_b.lot_stock_id)

    def test_inverse_qty_available_still_refuses_negative(self):
        with self.assertRaises(UserError):
            self.product.qty_available = -1.0
            self.product.flush_recordset()

    def test_count_moves_is_invalidated_by_a_receipt(self):
        """`count_moves_in` declared no depends, so it stayed stale in-transaction."""
        self.assertEqual(self.product.count_moves_in, 0)
        supplier = self.env.ref("stock.stock_location_suppliers")
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "incoming"), ("warehouse_id", "=", self.warehouse.id)],
            limit=1,
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": supplier.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 4,
                            "location_id": supplier.id,
                            "location_dest_id": self.stock_location.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.move_ids.quantity = 4
        picking.button_validate()
        self.assertEqual(self.product.count_moves_in, 1)

    def test_count_lot_ids_is_invalidated_by_a_new_lot(self):
        tracked = self.env["product.product"].create(
            {
                "name": "Scope Tracked",
                "is_storable": True,
                "type": "consu",
                "tracking": "lot",
            }
        )
        self.assertEqual(tracked.count_lot_ids, 0)
        self.env["stock.lot"].create({"name": "SCOPE-L1", "product_id": tracked.id})
        self.assertEqual(tracked.count_lot_ids, 1)

    def test_count_reordering_rules_is_invalidated_by_a_new_rule(self):
        self.assertEqual(self.product.count_reordering_rules, 0)
        self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.product.id,
                "warehouse_id": self.warehouse.id,
                "location_id": self.stock_location.id,
                "product_min_qty": 2,
                "product_max_qty": 9,
            }
        )
        self.assertEqual(self.product.count_reordering_rules, 1)
        self.assertEqual(self.product.reordering_qty_min, 2)
        self.assertEqual(self.product.reordering_qty_max, 9)

    def test_filter_to_unlink_excludes_products_the_database_will_refuse(self):
        """Quant- and move-bound products drove the savepoint/dichotomy retry path.

        `_unlink_or_archive` recovers, so this is about query count, not correctness:
        a blocked product turns one statement into a binary search over the batch.
        """
        with_stock = self.env["product.product"].create(
            {"name": "Scope Stocked", "is_storable": True, "type": "consu"}
        )
        self._stock_up(with_stock, 5)
        clean = self.env["product.product"].create(
            {"name": "Scope Clean", "is_storable": True, "type": "consu"}
        )
        unlinkable = (with_stock | clean)._filter_to_unlink()
        self.assertIn(clean, unlinkable)
        self.assertNotIn(with_stock, unlinkable)

    def test_unlink_or_archive_archives_a_product_with_stock(self):
        with_stock = self.env["product.product"].create(
            {"name": "Scope Stocked 2", "is_storable": True, "type": "consu"}
        )
        self._stock_up(with_stock, 5)
        with_stock._unlink_or_archive()
        self.assertTrue(with_stock.exists())
        self.assertFalse(with_stock.active)

    def test_get_picking_description_declares_its_singleton(self):
        other = self.env["product.product"].create(
            {"name": "Scope Other", "is_storable": True, "type": "consu"}
        )
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "incoming")], limit=1
        )
        with self.assertRaises(ValueError):
            (self.product | other)._get_picking_description(picking_type)

    def test_action_view_orderpoints_tolerates_an_empty_context(self):
        """`literal_eval` raised on an empty context string (SyntaxError)."""
        action = self.env.ref("stock.action_orderpoint")
        for context in ("{'search_default_trigger': 'auto'}", "{}", ""):
            with self.subTest(context=context):
                action.context = context
                result = self.product.action_view_orderpoints()
                self.assertIsInstance(result["context"], dict)
                self.assertNotIn("search_default_trigger", result["context"])
                self.assertTrue(result["context"]["search_default_filter_not_snoozed"])

    def test_prepare_quantities_scope_carries_the_dates_without_reading(self):
        """The scope phase decides what to read; only `_read_quantities` reads it."""
        location_domains = self.env["product.product"]._get_domain_locations()
        self.env.flush_all()
        past = fields.Datetime.now() - datetime.timedelta(days=5)
        queries_before = self.env.cr.sql_log_count
        scope = self.product._prepare_quantities_scope(
            None, None, None, to_date=past, location_domains=location_domains
        )
        self.assertEqual(
            self.env.cr.sql_log_count,
            queries_before,
            "assembling the scope must not hit the database",
        )
        self.assertTrue(scope.dates_in_the_past)
        self.assertIsNone(scope.expired_quant)
        self.assertNotEqual(scope.move_in_done, Domain.FALSE)

        future = fields.Datetime.now() + datetime.timedelta(days=5)
        scope = self.product._prepare_quantities_scope(
            None, None, None, to_date=future, location_domains=location_domains
        )
        self.assertFalse(scope.dates_in_the_past)
        self.assertEqual(scope.move_in_done, Domain.FALSE)
        self.assertEqual(scope.move_out_done, Domain.FALSE)

    def test_prepare_quantities_scope_honours_the_to_date_parameter_for_expiry(self):
        """The expiry cutoff follows the parameter, not `context['to_date']`.

        Every other window in the method honours the parameter, so an override that
        rewrites it -- `purchase_stock` does -- must not be ignored here.
        """
        context_date = "2020-01-01 00:00:00"
        param_date = fields.Datetime.now() + datetime.timedelta(days=30)
        scope = self.product.with_context(
            with_expiration=datetime.date.today(),
            fresh_qty_forecast=True,
            to_date=context_date,
        )._prepare_quantities_scope(None, None, None, to_date=param_date)
        self.assertIsNotNone(scope.expired_quant)
        rendered = repr(scope.expired_quant)
        self.assertIn("removal_date", rendered)
        self.assertNotIn("2020-01-01", rendered)

    def test_normalize_to_date_widens_a_bare_date_to_the_whole_day(self):
        Product = self.env["product.product"]
        day = datetime.date(2020, 1, 15)
        normalized, in_the_past = Product._normalize_quantities_to_date(day)
        self.assertTrue(in_the_past)
        self.assertEqual(normalized.date(), day)
        self.assertEqual((normalized.hour, normalized.minute), (23, 59))
        normalized, _ = Product._normalize_quantities_to_date("2020-01-15")
        self.assertEqual((normalized.hour, normalized.minute), (23, 59))
        normalized, in_the_past = Product._normalize_quantities_to_date(False)
        self.assertFalse(normalized)
        self.assertFalse(in_the_past)

    def test_prepare_quantities_vals_accepts_preresolved_location_domains(self):
        """The search path resolves the location triple once and hands it to both
        `_get_quantity_search_candidates` and `_prepare_quantities_vals`."""
        self._stock_up(self.product, 6)
        Product = self.env["product.product"]
        location_domains = Product._get_domain_locations()
        vals = self.product._prepare_quantities_vals(
            None, None, None, location_domains=location_domains
        )
        self.assertEqual(vals[self.product.id]["qty_available"], 6.0)
        candidates = Product._get_quantity_search_candidates(
            location_domains=location_domains
        )
        self.assertIn(self.product, candidates)

    def test_quantity_search_resolves_location_domains_once_per_condition(self):
        """Pins the de-duplication: two resolutions per condition became one."""
        self._stock_up(self.product, 6)
        Product = self.env["product.product"]
        cls = type(Product)
        calls = []
        original = cls._get_domain_locations

        def counting(records):
            calls.append(1)
            return original(records)

        cls._get_domain_locations = counting
        try:
            Product.search([("qty_free", ">", 0)])
        finally:
            cls._get_domain_locations = original
        self.assertEqual(
            len(calls),
            1,
            "the location triple should be resolved once per quantity condition",
        )

    # ------------------------------------------------------------------
    # Extracted helpers -- now directly testable, which is the point of extracting them
    # ------------------------------------------------------------------

    def test_resolve_context_record_ids_accepts_ids_and_names(self):
        resolve = self.env["product.product"]._resolve_context_record_ids
        self.assertEqual(
            resolve("stock.location", [self.stock_location.id]),
            {self.stock_location.id},
        )
        self.assertIn(
            self.stock_location.id,
            resolve("stock.location", [self.stock_location.name]),
        )
        self.assertEqual(resolve("stock.location", [999_999_999]), set())
        self.assertEqual(resolve("stock.location", ["No Such Location"]), set())

    def test_resolve_context_record_ids_rejects_booleans(self):
        resolve = self.env["product.product"]._resolve_context_record_ids
        for value in (True, False):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve("stock.location", [value])

    def test_narrow_quantity_domains_leaves_unfiltered_domains_alone(self):
        """`None` means unfiltered; `False` is a real value selecting "no lot/owner"."""
        product = self.env["product.product"]
        base = (Domain.TRUE, Domain.TRUE, Domain.TRUE)
        untouched = product._narrow_quantity_domains(*base, None, None, None)
        self.assertEqual([repr(d) for d in untouched], [repr(d) for d in base])
        quant, move_in, __ = product._narrow_quantity_domains(*base, False, None, None)
        self.assertIn("lot_id", repr(quant))
        self.assertIn("move_line_ids.lot_id", repr(move_in))

    def test_descendant_locations_query_covers_children(self):
        child = self.env["stock.location"].create(
            {"name": "Scope Child", "location_id": self.stock_location.id}
        )
        product = self.env["product.product"].create(
            {"name": "Scope Child Product", "is_storable": True, "type": "consu"}
        )
        self._stock_up(product, 4, location=child)
        # non-strict sees the child; strict does not
        self.assertEqual(
            product.with_context(location=self.stock_location.id).qty_available, 4.0
        )
        product.invalidate_recordset()
        self.assertEqual(
            product.with_context(
                location=self.stock_location.id, strict=True
            ).qty_available,
            0.0,
        )
