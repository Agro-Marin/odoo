from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tests import TransactionCase, tagged

from odoo.addons.stock.models.stock_quant_reservation import LOCKED_QUANTS_CACHE_KEY
from odoo.addons.stock.tests.common import TestStockCommon
from odoo.addons.stock.tools.reservation import (
    LeastPackagesPriorityQueue,
    QuantsCache,
    RemovalStrategy,
    ReservationCandidate,
    distribute_reservation,
    get_least_packages,
)


@tagged("post_install", "-at_install")
class TestLeastPackagesSearch(TransactionCase):
    def _num_packages(self, taken):
        return len(taken)

    def test_exact_single_package(self):
        taken = get_least_packages([(10, 5), (11, 3)], 5)
        self.assertEqual(taken, ((10, 5),))

    def test_prefers_fewer_packages_over_exactness(self):
        taken = get_least_packages([(10, 8), (11, 5), (12, 3)], 8)
        self.assertEqual(taken, ((10, 8),))

    def test_multi_single_exact_cover(self):
        taken = get_least_packages([(10, 9), (None, 1), (None, 1)], 2)
        self.assertEqual(taken, ((None, 1), (None, 1)))

    def test_overselect_fallback_when_no_exact(self):
        taken = get_least_packages([(10, 5)], 4)
        self.assertEqual(taken, ((10, 5),))
        self.assertEqual(self._num_packages(taken), 1)

    def test_insufficient_stock_returns_closest_leaf(self):
        taken = get_least_packages([(10, 2)], 5)
        self.assertEqual(taken, ((10, 2),))

    def test_priority_queue_never_compares_items_on_tie(self):
        class Explodes:
            def __lt__(self, other):
                raise AssertionError("frontier items must never be compared")

            __gt__ = __lt__
            __le__ = __lt__
            __ge__ = __lt__

        pq = LeastPackagesPriorityQueue()
        first, second, third = Explodes(), Explodes(), Explodes()
        pq.put(first, 1.0)
        pq.put(second, 1.0)
        pq.put(third, 1.0)
        self.assertIs(pq.get(), first)
        self.assertIs(pq.get(), second)
        self.assertIs(pq.get(), third)
        self.assertTrue(pq.is_empty())


@tagged("post_install", "-at_install")
class TestDistributeReservation(TransactionCase):
    ROUNDING = 0.01

    def _cand(self, handle, on_hand, reserved, key=None):
        return ReservationCandidate(handle, on_hand, reserved, key or handle)

    def test_zero_quantity_is_noop(self):
        cands = [self._cand("a", 10, 0)]
        self.assertEqual(distribute_reservation(cands, 0, self.ROUNDING), [])

    def test_reserve_stops_at_quantity(self):
        cands = [self._cand("a", 10, 0), self._cand("b", 10, 0)]
        res = distribute_reservation(cands, 8, self.ROUNDING)
        self.assertEqual(res, [("a", 8)])

    def test_reserve_spans_multiple_candidates(self):
        cands = [self._cand("a", 5, 0), self._cand("b", 5, 0)]
        res = distribute_reservation(cands, 8, self.ROUNDING)
        self.assertEqual(res, [("a", 5), ("b", 3)])

    def test_reserve_skips_fully_reserved(self):
        cands = [self._cand("a", 5, 5), self._cand("b", 5, 0)]
        res = distribute_reservation(cands, 3, self.ROUNDING)
        self.assertEqual(res, [("b", 3)])

    def test_reserve_exactly_all_available_slack(self):
        cands = [self._cand("a", 4, 1), self._cand("b", 5, 0)]
        res = distribute_reservation(cands, 8, self.ROUNDING)
        self.assertEqual(res, [("a", 3), ("b", 5)])

    def test_reserve_not_truncated_by_unrelated_negative_quant(self):
        cands = [
            self._cand("a", 4, 0, key="ka"),
            self._cand("b", 8, 0, key="kb"),
            self._cand("c", 1, 9, key="kc"),
        ]
        res = distribute_reservation(cands, 12, self.ROUNDING)
        self.assertEqual(res, [("a", 4), ("b", 8)])
        self.assertEqual(sum(qty for _handle, qty in res), 12)

    def test_negative_available_absorbed_within_group(self):
        cands = [self._cand("a", 2, 5, key="g"), self._cand("b", 10, 0, key="g")]
        res = distribute_reservation(cands, 4, self.ROUNDING)
        self.assertEqual(res, [("b", 4)])

    def test_negative_available_not_absorbed_across_groups(self):
        cands = [self._cand("a", 2, 5, key="g1"), self._cand("b", 10, 0, key="g2")]
        res = distribute_reservation(cands, 4, self.ROUNDING)
        self.assertEqual(res, [("b", 4)])

    def test_non_positive_quantity_allocates_nothing(self):
        cands = [self._cand("a", 10, 0), self._cand("b", 10, 4)]
        for quantity in (0, -4, -0.0001):
            self.assertEqual(distribute_reservation(cands, quantity, self.ROUNDING), [])

    def test_negative_reserved_candidate_never_yields_a_negative_delta(self):
        cands = [self._cand("neg", 0, -5, key="g"), self._cand("pos", 10, 6, key="g")]
        res = distribute_reservation(cands, 6, self.ROUNDING)
        self.assertTrue(res)
        self.assertTrue(all(amount > 0 for _handle, amount in res), res)
        self.assertAlmostEqual(sum(amount for _handle, amount in res), 6.0)

    def test_whole_units_skips_a_candidate_that_cannot_supply_one(self):
        candidates = [
            ReservationCandidate("a", 1.0, 0.0, "k"),
            ReservationCandidate("b", 0.5, 0.0, "k"),
            ReservationCandidate("c", 1.0, 0.0, "k"),
        ]
        self.assertEqual(
            distribute_reservation(candidates, 3.0, 0.01, whole_units=True),
            [("a", 1.0), ("c", 1.0)],
        )

    def test_whole_units_floors_a_partial_candidate(self):
        candidates = [ReservationCandidate("a", 2.5, 0.0, "k")]
        self.assertEqual(
            distribute_reservation(candidates, 2.0, 0.01, whole_units=True),
            [("a", 2.0)],
        )
        self.assertEqual(
            distribute_reservation(candidates, 5.0, 0.01, whole_units=True),
            [("a", 2.0)],
        )

    def test_whole_units_survives_float_representation(self):
        candidates = [ReservationCandidate("a", 0.30000000000000004 * 10 / 3, 0.0, "k")]
        self.assertEqual(
            distribute_reservation(candidates, 1.0, 0.01, whole_units=True),
            [("a", 1.0)],
        )

    def test_whole_units_off_is_unchanged(self):
        candidates = [ReservationCandidate("a", 0.5, 0.0, "k")]
        self.assertEqual(distribute_reservation(candidates, 1.0, 0.01), [("a", 0.5)])


@tagged("post_install", "-at_install")
class TestQuantGatherAndReserve(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location
        cls.products = cls.env["product.product"].create(
            [{"name": f"qimp-{i}", "is_storable": True} for i in range(5)]
        )

    def test_create_batches_non_inventory_rows(self):
        vals_list = [
            {"product_id": p.id, "location_id": self.loc.id, "quantity": 3.0}
            for p in self.products
        ]
        insert_count = {"n": 0}
        cursor_cls = type(self.env.cr)
        original_execute = cursor_cls.execute

        def counting_execute(cr, query, params=None, **kw):
            code = query if isinstance(query, str) else getattr(query, "code", "")
            if (
                "INSERT INTO" in str(code).upper()
                and "STOCK_QUANT" in str(code).upper()
            ):
                insert_count["n"] += 1
            return original_execute(cr, query, params, **kw)

        cursor_cls.execute = counting_execute
        try:
            quants = self.Quant.create(vals_list)
            self.env.cr.flush()
        finally:
            cursor_cls.execute = original_execute

        self.assertEqual(
            insert_count["n"],
            1,
            "5 non-inventory quant vals must be created with a single INSERT, "
            "not one INSERT per row.",
        )
        self.assertEqual(quants.product_id, self.products)
        self.assertEqual(set(quants.mapped("quantity")), {3.0})

    def test_create_preserves_order_mixed(self):
        vals_list = [
            {"product_id": p.id, "location_id": self.loc.id, "quantity": float(i + 1)}
            for i, p in enumerate(self.products)
        ]
        quants = self.Quant.create(vals_list)
        self.assertEqual(quants.product_id.ids, self.products.ids)
        self.assertEqual(quants.mapped("quantity"), [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_inventory_keys_no_cross_contamination(self):
        product = self.products[0]
        quant = self.Quant.with_context(inventory_mode=True).create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity_auto_apply": 0.0,
                    "inventory_quantity": 5.0,
                }
            ]
        )
        self.assertEqual(quant.quantity, 0.0)

    def test_sn_duplicated_scoped_to_self(self):
        serial = self.env["product.product"].create(
            {"name": "qimp-sn", "is_storable": True, "tracking": "serial"}
        )
        loc2 = self.env["stock.location"].create(
            {
                "name": "qimp-loc2",
                "usage": "internal",
                "location_id": self.loc.location_id.id,
            }
        )
        lot = self.env["stock.lot"].create(
            {"name": "QIMP-SN-1", "product_id": serial.id}
        )
        qa = self.Quant.create(
            {
                "product_id": serial.id,
                "location_id": self.loc.id,
                "lot_id": lot.id,
                "quantity": 1.0,
            }
        )
        qb = self.Quant.create(
            {
                "product_id": serial.id,
                "location_id": loc2.id,
                "lot_id": lot.id,
                "quantity": 1.0,
            }
        )
        self.env.invalidate_all()
        _ = qa.sn_duplicated
        self.assertFalse(
            self.env.cache.contains(qb, type(qb).sn_duplicated),
            "computing sn_duplicated on qa must not write it onto qb (outside self)",
        )
        self.assertTrue(qa.sn_duplicated)
        self.env.invalidate_all()
        self.assertTrue(qb.sn_duplicated)

    def test_unlink_zero_quants_scoping(self):
        px, py = self.products[0], self.products[1]
        qx = self.Quant.create(
            {"product_id": px.id, "location_id": self.loc.id, "quantity": 0.0}
        )
        qy = self.Quant.create(
            {"product_id": py.id, "location_id": self.loc.id, "quantity": 0.0}
        )
        self.env.cr.flush()
        qx._remove_zero_quants()
        self.assertFalse(
            qx.exists(), "scoped call should remove the in-scope zero quant"
        )
        self.assertTrue(
            qy.exists(), "scoped call must not touch out-of-scope zero quants"
        )
        self.env["stock.quant"]._remove_zero_quants()
        self.assertFalse(qy.exists(), "model-level call should sweep all zero quants")

    def test_inventory_mode_create_can_set_what_write_forbids(self):
        creatable = set(self.Quant._get_inventory_fields_create())
        forbidden_to_write = set(self.Quant._get_forbidden_fields_write())
        self.assertTrue(
            forbidden_to_write <= creatable,
            "a field write refuses must be settable at creation, or it is settable"
            f" nowhere: {sorted(forbidden_to_write - creatable)}",
        )
        self.assertFalse(
            forbidden_to_write
            & {
                "inventory_quantity",
                "inventory_quantity_auto_apply",
                "inventory_diff_quantity",
                "inventory_quantity_set",
                "inventory_date",
                "user_id",
            },
            "inventory mode has to be able to record a count, which is the one thing"
            " it exists to do",
        )

    def test_one_corrupt_half_serial_does_not_block_the_whole_ones(self):
        product = self.env["product.product"].create(
            {"name": "qimp-halfserial", "is_storable": True, "tracking": "serial"}
        )
        good_a, good_b, corrupt = self.env["stock.lot"].create(
            [
                {"name": f"qimp-hs-{index}", "product_id": product.id}
                for index in range(3)
            ]
        )
        self.Quant._update_available_quantity(product, self.loc, 1.0, lot_id=good_a)
        self.Quant._update_available_quantity(product, self.loc, 1.0, lot_id=good_b)
        self.Quant._update_available_quantity(product, self.loc, 0.5, lot_id=corrupt)
        self.env.invalidate_all()

        self.assertEqual(self.Quant._get_available_quantity(product, self.loc), 2.5)
        reserved = self.Quant._get_reserve_quantity(product, self.loc, 3.0)
        self.assertEqual(
            sum(quantity for _quant, quantity in reserved),
            2.0,
            "the two whole serials are reservable and must be reserved",
        )
        self.assertNotIn(
            corrupt,
            [quant.lot_id for quant, _quantity in reserved],
            "half a serial number is not a thing that can be picked",
        )
        for _quant, quantity in reserved:
            self.assertEqual(quantity, 1.0, "one serial per quant, whole")

    def test_a_fractional_serial_request_is_still_refused_outright(self):
        product = self.env["product.product"].create(
            {"name": "qimp-fracreq", "is_storable": True, "tracking": "serial"}
        )
        lots = self.env["stock.lot"].create(
            [
                {"name": f"qimp-fr-{index}", "product_id": product.id}
                for index in range(2)
            ]
        )
        for lot in lots:
            self.Quant._update_available_quantity(product, self.loc, 1.0, lot_id=lot)
        self.env.invalidate_all()

        self.assertEqual(
            self.Quant._get_reserve_quantity(product, self.loc, 1.1),
            [],
            "a request for a fraction of a serial number is refused, not rounded",
        )
        self.assertEqual(
            sum(
                q
                for _quant, q in self.Quant._get_reserve_quantity(
                    product, self.loc, 2.0
                )
            ),
            2.0,
            "a whole request against whole stock is unaffected",
        )

    def test_quantity_is_never_null(self):
        product = self.env["product.product"].create(
            {"name": "qimp-notnull", "is_storable": True}
        )
        self.Quant._update_reserved_quantity(product, self.loc, 5.0)
        self.env.flush_all()

        quant = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(len(quant), 1, "the reservation provisioned a quant")
        self.assertEqual(quant.reserved_quantity, 5.0)
        self.assertEqual(quant.quantity, 0.0, "and gave it a real on-hand, not NULL")

        self.env.cr.execute("SELECT count(*) FROM stock_quant WHERE quantity IS NULL")
        self.assertEqual(
            self.env.cr.fetchone()[0], 0, "no quant anywhere may hold a NULL on-hand"
        )
        self.env.cr.execute(
            """SELECT is_nullable FROM information_schema.columns
                WHERE table_name = 'stock_quant' AND column_name = 'quantity'"""
        )
        self.assertEqual(
            self.env.cr.fetchone()[0],
            "NO",
            "the column itself must refuse NULL, so nothing has to guard for it",
        )

    def test_unlink_zero_quants_honours_a_one_sided_scope(self):
        px, py = self.products[0], self.products[1]
        other_loc = self.env["stock.location"].create(
            {"name": "qimp-zero-scope", "usage": "internal", "location_id": self.loc.id}
        )
        in_scope, out_of_product, out_of_location = self.Quant.create(
            [
                {"product_id": px.id, "location_id": self.loc.id, "quantity": 0.0},
                {"product_id": py.id, "location_id": self.loc.id, "quantity": 0.0},
                {"product_id": px.id, "location_id": other_loc.id, "quantity": 0.0},
            ]
        )
        self.env.cr.flush()

        self.Quant._remove_zero_quants(products=px)
        self.assertFalse(in_scope.exists(), "a products-only scope must still sweep")
        self.assertFalse(
            out_of_location.exists(),
            "a products-only scope covers that product in every location",
        )
        self.assertTrue(
            out_of_product.exists(),
            "a products-only scope must not reach another product",
        )

        self.Quant._remove_zero_quants(locations=other_loc)
        self.assertTrue(
            out_of_product.exists(),
            "a locations-only scope must not reach another location",
        )

    def test_is_outdated_compute_matches_search(self):
        product = self.products[2]
        quant = self.Quant.with_context(inventory_mode=True).create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity": 4.0,
                }
            ]
        )
        self.env.flush_all()
        quant.sudo().write({"quantity": 9.0})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertTrue(quant.is_outdated)
        found = self.env["stock.quant"].search([("is_outdated", "in", [True])])
        self.assertIn(quant, found, "search(is_outdated) must agree with the compute")

        all_quants = self.env["stock.quant"].search([])
        outdated = self.env["stock.quant"].search([("is_outdated", "=", True)])
        not_outdated = self.env["stock.quant"].search([("is_outdated", "=", False)])
        self.assertIn(quant, outdated)
        self.assertNotIn(quant, not_outdated)
        self.assertFalse(outdated & not_outdated, "True/False sets must be disjoint")
        self.assertEqual(
            outdated | not_outdated, all_quants, "False must be the complement of True"
        )

    def test_is_outdated_follows_every_field_it_reads(self):
        product = self.env["product.product"].create(
            {"name": "qimp-outdated-depends", "is_storable": True}
        )
        quant = self.Quant.with_context(inventory_mode=True).create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity": 4.0,
                }
            ]
        )
        self.env.flush_all()
        quant.sudo().write({"quantity": 9.0})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertTrue(quant.is_outdated, "the on-hand drifted away from the count")

        quant.sudo().write({"inventory_quantity_set": False})
        self.assertFalse(
            quant.is_outdated,
            "nothing is counted any more, so nothing can be out of date",
        )
        self.assertNotIn(
            quant,
            self.env["stock.quant"].search([("is_outdated", "=", True)]),
            "the SQL search must not have to disagree with the compute",
        )

    def test_last_count_date_tracks_inventory_move(self):
        product = self.env["product.product"].create(
            {"name": "qimp-lastcount", "is_storable": True}
        )
        quant = self.Quant.with_context(inventory_mode=True).create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity_auto_apply": 7.0,
                }
            ]
        )
        self.env.flush_all()
        self.env.invalidate_all()
        move_lines = self.env["stock.move.line"].search(
            [
                ("product_id", "=", product.id),
                ("is_inventory", "=", True),
                ("state", "=", "done"),
            ]
        )
        self.assertTrue(
            move_lines, "applying a count must leave a done inventory move line"
        )
        self.assertEqual(
            quant.last_count_date,
            max(move_lines.mapped("date")).date(),
            "last_count_date must equal the newest done inventory move-line date",
        )

    def test_gather_cache_path_none_package_owner(self):
        product = self.products[3]
        self.Quant._update_available_quantity(product, self.loc, 2.0)
        self.env.cr.flush()
        cache = self.Quant._get_quants_by_products_locations(product, self.loc)
        res = self.Quant.with_context(quants_cache=cache)._gather(
            product, self.loc, strict=True
        )
        self.assertEqual(res.product_id, product)

    def test_gather_cache_miss_falls_back_to_search(self):
        covered, uncovered = self.products[0], self.products[1]
        self.Quant._update_available_quantity(covered, self.loc, 5.0)
        self.Quant._update_available_quantity(uncovered, self.loc, 7.0)
        self.env.cr.flush()
        cache = self.Quant._get_quants_by_products_locations(covered, self.loc)
        gather = self.Quant.with_context(quants_cache=cache)._gather
        self.assertFalse(cache.is_covering(uncovered, self.loc))
        self.assertTrue(cache.is_covering(covered, self.loc))
        self.assertEqual(gather(covered, self.loc, strict=True).quantity, 5.0)
        res = gather(uncovered, self.loc, strict=True)
        self.assertEqual(res.product_id, uncovered)
        self.assertEqual(res.quantity, 7.0)

        other_loc = self.env["stock.location"].create(
            {"name": "qimp-other", "usage": "internal", "location_id": self.loc.id}
        )
        self.Quant._update_available_quantity(covered, other_loc, 3.0)
        self.env.cr.flush()
        child_cache = self.Quant._get_quants_by_products_locations(
            covered,
            self.env["stock.location"].browse(),
        )
        self.assertFalse(child_cache.is_covering(covered, other_loc))
        res2 = self.Quant.with_context(quants_cache=child_cache)._gather(
            covered, other_loc, strict=True
        )
        self.assertEqual(res2.quantity, 3.0)

    def test_least_packages_multi_single_single_query(self):
        strat = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        categ = self.env["product.category"].create(
            {"name": "qimp-lp", "removal_strategy_id": strat.id}
        )
        product = self.env["product.product"].create(
            {"name": "qimp-lp-prod", "is_storable": True, "categ_id": categ.id}
        )
        pkg = self.env["stock.package"].create({"name": "QIMP-LP"})
        self.Quant._update_available_quantity(product, self.loc, 9.0, package_id=pkg)
        self.Quant._update_available_quantity(product, self.loc, 6.0)
        self.env.invalidate_all()

        cls = type(self.Quant)
        orig_search, orig_domain = cls.search, cls._get_domain_least_packages
        state = {"building": False, "singles_searches": 0}

        def counting_search(records, *args, **kwargs):
            if state["building"]:
                state["singles_searches"] += 1
            return orig_search(records, *args, **kwargs)

        def counting_domain(records, taken, dom):
            state["building"] = True
            try:
                return orig_domain(records, taken, dom)
            finally:
                state["building"] = False

        cls.search = counting_search
        cls._get_domain_least_packages = counting_domain
        try:
            res = self.Quant._gather(product, self.loc, qty=3)
        finally:
            cls.search = orig_search
            cls._get_domain_least_packages = orig_domain

        self.assertTrue(res, "gather must return the unpackaged quant")
        self.assertEqual(res.package_id.ids, [], "should pick the unpackaged quant")
        self.assertEqual(
            state["singles_searches"],
            1,
            "singles must be resolved with a single query, not one per unit",
        )

    def test_least_packages_input_is_ordered_by_available_quantity(self):
        strat = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        categ = self.env["product.category"].create(
            {"name": "qimp-lp-order", "removal_strategy_id": strat.id}
        )
        product = self.env["product.product"].create(
            {
                "name": "qimp-lp-order-prod",
                "is_storable": True,
                "categ_id": categ.id,
                "uom_id": self.env.ref("uom.product_uom_kgm").id,
            }
        )
        for index, amount in enumerate((8.0, 1.0, 0.75)):
            package = self.env["stock.package"].create(
                {"name": f"QIMP-LP-ORDER-{index}"}
            )
            self.Quant._update_available_quantity(
                product, self.loc, amount, package_id=package
            )
        self.Quant._update_available_quantity(product, self.loc, 3.0)
        self.env.invalidate_all()

        from odoo.addons.stock.models import stock_quant_reservation as _sq

        seen = {}
        original = _sq.get_least_packages

        def capture(qty_by_package, qty):
            seen["input"] = list(qty_by_package)
            return original(qty_by_package, qty)

        _sq.get_least_packages = capture
        try:
            self.Quant._gather(product, self.loc, qty=5.0)
        finally:
            _sq.get_least_packages = original

        entries = seen.get("input")
        self.assertTrue(entries, "the A* must have been reached")
        amounts = [amount for _key, amount in entries]
        self.assertEqual(
            amounts,
            sorted(amounts, reverse=True),
            "the search's input must be ordered by available quantity, descending"
            f" -- got {amounts}",
        )
        unit_slots = [index for index, (key, _a) in enumerate(entries) if key is None]
        unit_package = [
            index
            for index, (key, a) in enumerate(entries)
            if key is not None and a == 1.0
        ]
        self.assertTrue(unit_slots and unit_package)
        self.assertEqual(
            abs(min(unit_slots) - max(unit_package)),
            1,
            "a 1-unit package and the 1-unit slots are interchangeable and must be"
            " adjacent, or the search branches on the same amount twice",
        )

    def test_least_packages_reaches_sub_unit_loose_stock(self):
        strat = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        categ = self.env["product.category"].create(
            {"name": "qimp-lp-frac", "removal_strategy_id": strat.id}
        )
        product = self.env["product.product"].create(
            {
                "name": "qimp-lp-frac-prod",
                "is_storable": True,
                "categ_id": categ.id,
                "uom_id": self.env.ref("uom.product_uom_kgm").id,
            }
        )
        pkg = self.env["stock.package"].create({"name": "QIMP-LP-FRAC"})
        self.Quant._update_available_quantity(product, self.loc, 8.0, package_id=pkg)
        self.Quant._update_available_quantity(product, self.loc, 0.5)
        self.env.invalidate_all()

        available = self.Quant._get_available_quantity(product, self.loc)
        self.assertEqual(available, 8.5)

        reserved = self.Quant._get_reserve_quantity(product, self.loc, 8.5)
        self.assertEqual(
            sum(quantity for _quant, quantity in reserved),
            8.5,
            "what availability promised is what the reservation must reach",
        )
        self.assertIn(
            False,
            [quant.package_id.id for quant, _quantity in reserved],
            "the loose half-kilo has to be one of the reserved quants",
        )

    def test_least_packages_no_packages_is_noop(self):
        from odoo.addons.stock.models import stock_quant_reservation as _sq

        strat = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        categ = self.env["product.category"].create(
            {"name": "qimp-lp-noop", "removal_strategy_id": strat.id}
        )
        product = self.env["product.product"].create(
            {"name": "qimp-lp-noop-prod", "is_storable": True, "categ_id": categ.id}
        )
        self.Quant._update_available_quantity(product, self.loc, 5.0)
        self.env.invalidate_all()

        base_domain = [
            ("product_id", "=", product.id),
            ("location_id", "=", self.loc.id),
        ]
        calls = {"n": 0}
        original = _sq.get_least_packages

        def spy(qty_by_package, qty):
            calls["n"] += 1
            return original(qty_by_package, qty)

        _sq.get_least_packages = spy
        try:
            res = self.Quant._run_least_packages_removal_strategy_astar(base_domain, 3)
        finally:
            _sq.get_least_packages = original

        self.assertEqual(
            calls["n"], 0, "no real packages -> the A* solver must never run"
        )
        from odoo.fields import Domain

        self.assertEqual(res, Domain(base_domain).optimize(self.Quant))

    def test_gather_cache_path_matches_search_order(self):
        product = self.env["product.product"].create(
            {"name": "qimp-order", "is_storable": True}
        )
        self.Quant.create(
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "quantity": 5.0,
                "in_date": "2024-01-01 00:00:00",
            }
        )
        self.Quant.create(
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "quantity": 5.0,
                "in_date": "2020-01-01 00:00:00",
            }
        )
        self.env.cr.flush()

        search_order = self.Quant._gather(product, self.loc, strict=True).ids
        cache = self.Quant._get_quants_by_products_locations(product, self.loc)
        cache_order = (
            self.Quant.with_context(quants_cache=cache)
            ._gather(product, self.loc, strict=True)
            .ids
        )
        self.assertEqual(
            search_order,
            cache_order,
            "cache-path _gather must match the search-path fifo order",
        )

    def test_write_mixed_recordset_does_not_silently_drop(self):
        self.env.user.group_ids = [(4, self.env.ref("stock.group_stock_user").id)]
        inv_loc = self.env["stock.location"].search(
            [("usage", "=", "inventory")], limit=1
        )
        product = self.env["product.product"].create(
            {"name": "qimp-mixed", "is_storable": True}
        )
        owner = self.env["res.partner"].create({"name": "qimp-owner"})
        q_internal = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 1.0}
        )
        q_inv = self.Quant.create(
            {"product_id": product.id, "location_id": inv_loc.id, "quantity": 1.0}
        )
        with self.assertRaises(UserError):
            (q_internal | q_inv).with_context(inventory_mode=True).write(
                {"owner_id": owner.id}
            )
        self.env.invalidate_all()
        self.assertFalse(
            q_internal.owner_id, "the raise must have rolled back the whole write"
        )
        self.assertTrue(
            q_inv.with_context(inventory_mode=True).write({"owner_id": owner.id})
        )
        self.env.invalidate_all()
        self.assertFalse(
            q_inv.owner_id, "inventory-location forbidden write is a no-op"
        )

    def test_gather_signature_is_override_safe(self):
        import inspect

        import odoo.addons.stock.models.stock_quant_reservation as _sq

        gather_params = inspect.signature(_sq.StockQuantReservation._gather).parameters
        self.assertNotIn(
            "removal_strategy",
            gather_params,
            "_gather must not take removal_strategy as a param; thread it via the "
            "_gather_removal_strategy context key so fixed-signature overrides survive.",
        )
        avail_params = inspect.signature(
            _sq.StockQuantReservation._get_available_quantity
        ).parameters
        self.assertNotIn("removal_strategy", avail_params)
        self.assertNotIn(
            "gathered_quants",
            avail_params,
            "_get_available_quantity must not take gathered_quants; reuse a pre-gathered "
            "recordset through _get_available_quantity_from_quants instead.",
        )

    def _count_gather_calls(self, fn):
        import odoo.addons.stock.models.stock_quant_reservation as _sq

        orig = _sq.StockQuantReservation._gather
        calls = {"n": 0}

        def spy(records, *args, **kwargs):
            calls["n"] += 1
            return orig(records, *args, **kwargs)

        _sq.StockQuantReservation._gather = spy
        try:
            fn()
        finally:
            _sq.StockQuantReservation._gather = orig
        return calls["n"]

    def test_reserve_reuses_gather_for_fifo(self):
        product = self.env["product.product"].create(
            {"name": "qimp-reuse", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, 20.0)
        self.env.cr.flush()
        self.env.invalidate_all()
        n = self._count_gather_calls(
            lambda: self.Quant._get_reserve_quantity(
                product, self.loc, 5.0, strict=False
            )
        )
        self.assertEqual(n, 1, "fifo reservation must gather once, not twice")

    def test_reserve_regathers_for_least_packages(self):
        strat = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        categ = self.env["product.category"].create(
            {"name": "qimp-reuse-lp", "removal_strategy_id": strat.id}
        )
        product = self.env["product.product"].create(
            {"name": "qimp-reuse-lp-prod", "is_storable": True, "categ_id": categ.id}
        )
        pkg1 = self.env["stock.package"].create({"name": "QIMP-RLP1"})
        pkg2 = self.env["stock.package"].create({"name": "QIMP-RLP2"})
        self.Quant._update_available_quantity(product, self.loc, 5.0, package_id=pkg1)
        self.Quant._update_available_quantity(product, self.loc, 5.0, package_id=pkg2)
        self.env.cr.flush()
        self.env.invalidate_all()
        n = self._count_gather_calls(
            lambda: self.Quant._get_reserve_quantity(
                product, self.loc, 5.0, strict=False
            )
        )
        self.assertEqual(
            n, 2, "least_packages must re-gather the full set for availability"
        )

    def _count_strategy_calls(self, fn):
        import odoo.addons.stock.models.stock_quant_reservation as _sq

        orig = _sq.StockQuantReservation._get_removal_strategy
        calls = {"n": 0}

        def spy(records, *args, **kwargs):
            calls["n"] += 1
            return orig(records, *args, **kwargs)

        _sq.StockQuantReservation._get_removal_strategy = spy
        try:
            fn()
        finally:
            _sq.StockQuantReservation._get_removal_strategy = orig
        return calls["n"]

    def test_reserve_resolves_strategy_once_fifo(self):
        product = self.env["product.product"].create(
            {"name": "qimp-strat-fifo", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, 20.0)
        self.env.cr.flush()
        self.env.invalidate_all()
        n = self._count_strategy_calls(
            lambda: self.Quant._get_reserve_quantity(
                product, self.loc, 5.0, strict=False
            )
        )
        self.assertEqual(n, 1, "fifo reservation must resolve the strategy once")

    def test_reserve_resolves_strategy_once_least_packages(self):
        strat = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        categ = self.env["product.category"].create(
            {"name": "qimp-strat-lp", "removal_strategy_id": strat.id}
        )
        product = self.env["product.product"].create(
            {"name": "qimp-strat-lp-prod", "is_storable": True, "categ_id": categ.id}
        )
        pkg1 = self.env["stock.package"].create({"name": "QIMP-SLP1"})
        pkg2 = self.env["stock.package"].create({"name": "QIMP-SLP2"})
        self.Quant._update_available_quantity(product, self.loc, 5.0, package_id=pkg1)
        self.Quant._update_available_quantity(product, self.loc, 5.0, package_id=pkg2)
        self.env.cr.flush()
        self.env.invalidate_all()
        n = self._count_strategy_calls(
            lambda: self.Quant._get_reserve_quantity(
                product, self.loc, 5.0, strict=False
            )
        )
        self.assertEqual(
            n, 1, "least_packages reservation must resolve the strategy once"
        )

    def test_removal_strategy_nearest_ancestor_via_parent_path(self):
        lifo = self.env["product.removal"].search([("method", "=", "lifo")], limit=1)
        closest = self.env["product.removal"].search(
            [("method", "=", "closest")], limit=1
        )
        parent = self.loc
        chain = []
        for i in range(4):
            parent = self.env["stock.location"].create(
                {"name": f"anc-{i}", "location_id": parent.id}
            )
            chain.append(parent)
        self.env.cr.flush()
        deep = chain[-1]
        product = self.env["product.product"].create(
            {"name": "anc-prod", "is_storable": True}
        )
        chain[0].removal_strategy_id = closest
        chain[2].removal_strategy_id = lifo
        self.env.cr.flush()
        self.env.invalidate_all()
        self.assertEqual(self.Quant._get_removal_strategy(product, deep), "lifo")
        deep.removal_strategy_id = closest
        self.env.cr.flush()
        self.env.invalidate_all()
        self.assertEqual(self.Quant._get_removal_strategy(product, deep), "closest")

    def test_action_apply_all_without_active_domain(self):
        product = self.products[0]
        quant = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 1.0}
        )
        action = quant.action_apply_all()
        self.assertEqual(action["res_model"], "stock.inventory.adjustment.name")
        self.assertEqual(action["context"]["default_quant_ids"], quant.ids)

    def test_reservation_key(self):
        product = self.products[4]
        self.Quant._update_available_quantity(product, self.loc, 1.0)
        quant = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(
            quant._get_reservation_key(),
            (quant.location_id, quant.lot_id, quant.package_id, quant.owner_id),
        )

    def test_release_lock_miss_persists_negative_reserved(self):
        product = self.env["product.product"].create(
            {"name": "qimp-release", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, 10.0)
        self.Quant._update_reserved_quantity(product, self.loc, 6.0)
        self.env.cr.flush()
        domain = [
            ("product_id", "=", product.id),
            ("location_id", "=", self.loc.id),
        ]

        def lock_nothing(records, **kwargs):
            return records.browse()

        # the reservation above locked the row for this transaction; the
        # simulated miss only makes sense once that lock is forgotten
        self.env.cr.cache.pop(LOCKED_QUANTS_CACHE_KEY, None)
        with patch.object(type(self.Quant), "_try_lock", lock_nothing):
            self.Quant._update_reserved_quantity(product, self.loc, -6.0)

        quants = self.Quant.search(domain)
        self.assertEqual(
            len(quants),
            2,
            "an un-lockable release must be recorded on a sibling row",
        )
        self.assertEqual(
            sum(quants.mapped("reserved_quantity")),
            0.0,
            "aggregate reserved must net to zero right after the release",
        )
        self.assertEqual(
            self.Quant._get_available_quantity(product, self.loc),
            10.0,
            "availability must reflect the release before any merge/clean runs",
        )
        quants._merge_quants()
        merged = self.Quant.search(domain)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.reserved_quantity, 0.0)
        self.assertEqual(merged.quantity, 10.0)

    def test_merging_duplicates_keeps_the_count_bookkeeping(self):
        product = self.env["product.product"].create(
            {"name": "qimp-merge-count", "is_storable": True}
        )
        older = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 10.0}
        )
        self.env.flush_all()
        newer = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 4.0}
        )
        self.env.flush_all()
        self.assertLess(older.id, newer.id, "the older row is the one that survives")

        counted = newer.with_context(inventory_mode=True)
        counted.action_set_inventory_quantity()
        counted.inventory_quantity = 5.0
        self.env.flush_all()
        self.assertTrue(newer.user_id, "the count is assigned to someone")

        self.Quant._merge_quants()
        self.env.invalidate_all()
        merged = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.quantity, 14.0)
        self.assertEqual(merged.inventory_quantity, 5.0)
        self.assertTrue(
            merged.inventory_quantity_set,
            "a row carrying a counted quantity cannot also say nobody counted it",
        )
        self.assertTrue(merged.user_id, "the count assignment must survive the merge")
        self.assertTrue(
            merged.is_outdated,
            "5 was counted against 4; the merged row holds 14, which is the drift the"
            " conflict wizard exists to show",
        )
        action = merged.with_context(inventory_mode=True).action_apply_inventory()
        self.assertEqual(
            (action or {}).get("res_model"),
            "stock.inventory.conflict",
            "applying must warn, not silently write off nine units",
        )

    def test_quant_tasks_recordset_survives_merge_dupes(self):
        product = self.env["product.product"].create(
            {"name": "qimp-dupes", "is_storable": True}
        )
        dupes = self.Quant.create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "quantity": 5.0,
                },
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "quantity": 7.0,
                },
            ]
        )
        self.env.cr.flush()
        dupes._run_maintenance_tasks()
        remaining = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(len(remaining), 1, "the duplicate rows must be merged")
        self.assertEqual(remaining.quantity, 12.0)

    def test_clean_reservations_scoped_to_recordset(self):
        product = self.env["product.product"].create(
            {"name": "qimp-clean", "is_storable": True}
        )
        loc_b = self.env["stock.location"].create(
            {"name": "qimp-clean-b", "usage": "internal", "location_id": self.loc.id}
        )
        phantom = self.Quant.create(
            {
                "product_id": product.id,
                "location_id": loc_b.id,
                "quantity": 5.0,
                "reserved_quantity": 5.0,
            }
        )
        in_scope = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 3.0}
        )
        self.env.cr.flush()
        in_scope._run_maintenance_tasks()
        self.assertEqual(
            phantom.reserved_quantity,
            5.0,
            "a scoped clean-up must not touch quants outside its locations",
        )
        self.Quant._sync_reserved_quantities()
        self.assertEqual(
            phantom.reserved_quantity,
            0.0,
            "the model-level clean-up must stay global",
        )

    def test_every_removal_strategy_orders_the_same_in_sql_and_in_python(self):
        product = self.env["product.product"].create(
            {"name": "qimp-order-parity", "is_storable": True}
        )
        sublocations = self.env["stock.location"].create(
            [
                {
                    "name": f"qimp-order-{name}",
                    "usage": "internal",
                    "location_id": self.loc.id,
                }
                for name in ("delta", "alpha", "charlie", "bravo", "echo", "foxtrot")
            ]
        )
        base = datetime(2020, 1, 1)
        for index, location in enumerate(sublocations):
            self.Quant._update_available_quantity(product, location, 5.0 + index)
        quants = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "in", sublocations.ids)]
        )
        self.assertEqual(len(quants), 6)
        offsets = (3, 0, 2, 1, 0, 2)
        for offset, quant in zip(offsets, quants, strict=True):
            quant.sudo().write({"in_date": base + timedelta(days=offset)})
        self.assertLess(
            len(set(offsets)), len(offsets), "the fixture must contain in_date ties"
        )
        if "removal_date" in self.Quant._fields:
            lots = self.env["stock.lot"].create(
                [
                    {"name": f"qimp-order-lot-{index}", "product_id": product.id}
                    for index in range(4)
                ]
            )
            for days, lot in zip((5, 1, 5, 3), lots, strict=True):
                lot.removal_date = base + timedelta(days=days)
            for lot, quant in zip(lots, quants, strict=False):
                quant.sudo().write({"lot_id": lot.id})
            self.assertEqual(
                len(quants.filtered(lambda quant: not quant.removal_date)),
                2,
                "two quants must stay unset so the NULL branch is exercised",
            )
        self.env.flush_all()

        methods = set(self.env["product.removal"].search([]).mapped("method"))
        self.assertIn("fifo", methods, "the data strategies must be installed")
        for method in sorted(methods):
            strategy = self.Quant._get_removal_strategy_record(method)
            sort_key = strategy.resolve_sorted_arguments()
            if sort_key is None:
                continue
            with self.subTest(removal_strategy=method):
                key, reverse = sort_key
                order = strategy.order
                from_sql = self.Quant.search(
                    [("id", "in", quants.ids)], order=order or None
                )
                from_python = from_sql.sorted(key, reverse=reverse)
                self.assertEqual(
                    from_sql.ids,
                    from_python.ids,
                    f"the SQL order and the Python sort key for {method!r} must be "
                    f"one ordering, not two",
                )

    def test_gather_cache_bypassed_for_extended_domain(self):
        product = self.env["product.product"].create(
            {"name": "qimp-extdom", "is_storable": True}
        )
        self.Quant.create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "quantity": 2.0,
                },
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "quantity": 9.0,
                },
            ]
        )
        self.env.cr.flush()
        cache = self.Quant._get_quants_by_products_locations(product, self.loc)
        gather = self.Quant.with_context(quants_cache=cache)._gather

        self.assertEqual(len(gather(product, self.loc, strict=True)), 2)

        registry_cls = type(self.Quant)
        orig = registry_cls._get_domain_gather

        def extended(records, *args, **kwargs):
            return orig(records, *args, **kwargs) & Domain("quantity", ">", 6.0)

        with patch.object(registry_cls, "_get_domain_gather", extended):
            res = gather(product, self.loc, strict=True)
        self.assertEqual(
            res.mapped("quantity"),
            [9.0],
            "an override-extended gather domain must fall back to the search "
            "path instead of serving unfiltered quants from the cache",
        )

    def test_gather_cache_bypassed_for_unknown_strategy_order(self):
        product = self.env["product.product"].create(
            {"name": "qimp-custstrat", "is_storable": True}
        )
        self.Quant.create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "quantity": 5.0,
                    "in_date": "2024-01-01 00:00:00",
                },
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "quantity": 5.0,
                    "in_date": "2020-01-01 00:00:00",
                },
            ]
        )
        self.env.cr.flush()

        with self.assertRaises(UserError):
            self.Quant._get_removal_strategy_record("qimp_custom")

        registry_cls = type(self.Quant)
        orig_strategies = registry_cls._get_removal_strategies

        def custom_strategy(records, product_id, location_id):
            return "qimp_custom"

        def custom_strategies(records):
            return {
                **orig_strategies(records),
                "qimp_custom": RemovalStrategy(order="id DESC"),
            }

        with (
            patch.object(registry_cls, "_get_removal_strategy", custom_strategy),
            patch.object(registry_cls, "_get_removal_strategies", custom_strategies),
        ):
            search_ids = self.Quant._gather(product, self.loc, strict=True).ids
            cache = self.Quant._get_quants_by_products_locations(product, self.loc)
            cache_ids = (
                self.Quant.with_context(quants_cache=cache)
                ._gather(product, self.loc, strict=True)
                .ids
            )

        self.assertEqual(
            search_ids,
            sorted(search_ids, reverse=True),
            "control: the custom strategy's SQL order must be id DESC",
        )
        self.assertEqual(
            cache_ids,
            search_ids,
            "a strategy without a Python sort key must bypass the cache and "
            "match the search-path order",
        )

    def test_reserve_full_availability_despite_negative_quant(self):
        product = self.env["product.product"].create(
            {"name": "qimp-negquant", "is_storable": True, "tracking": "lot"}
        )
        lots = {}
        for name, qty in (("A", 4), ("B", 8), ("C", 9)):
            lots[name] = self.env["stock.lot"].create(
                {"name": f"qimp-neg-{name}", "product_id": product.id}
            )
            self.Quant._update_available_quantity(
                product, self.loc, qty, lot_id=lots[name]
            )
        self.Quant._update_reserved_quantity(product, self.loc, 9, lot_id=lots["C"])
        self.Quant.search(
            [("product_id", "=", product.id), ("lot_id", "=", lots["C"].id)]
        ).write({"quantity": 1})
        self.env.flush_all()

        available = self.Quant._get_available_quantity(product, self.loc)
        self.assertEqual(available, 12.0, "lots A and B are wholly free")

        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 12,
                "location_id": self.loc.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move._action_confirm()
        move._action_assign()
        self.env.flush_all()

        self.assertEqual(
            move.quantity, 12.0, "a single reservation pass must take all 12"
        )
        self.assertEqual(move.state, "assigned")
        self.assertEqual(
            sorted(move.move_line_ids.mapped("lot_id.name")),
            ["qimp-neg-A", "qimp-neg-B"],
        )

    def _count_orderpoint_searches_on_assign(self, count, code):
        warehouse = self.env["stock.warehouse"].create(
            {
                "name": f"Assign {code}",
                "reception_steps": "one_step",
                "delivery_steps": "ship_only",
                "code": code,
                "sequence": 5,
            }
        )
        picking_type = warehouse.out_type_id
        picking_type.reservation_method = "manual"
        location = warehouse.lot_stock_id
        products = self.env["product.product"].create(
            [
                {"name": f"qimp-assign-{code}-{i}", "is_storable": True}
                for i in range(count)
            ]
        )
        for product in products:
            self.Quant._update_available_quantity(product, location, 50.0)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["stock.move"].create(
            [
                {
                    "product_id": product.id,
                    "product_uom_qty": 5.0,
                    "picking_id": picking.id,
                    "location_id": location.id,
                    "location_dest_id": self.customer_location.id,
                }
                for product in products
            ]
        )
        picking.action_confirm()
        picking.move_ids._unreserve()
        self.env.flush_all()

        StockMove = type(self.env["stock.move"])
        original = StockMove._get_orderpoints_to_update
        calls = []

        def spy(records):
            calls.append(len(records))
            return original(records)

        with patch.object(StockMove, "_get_orderpoints_to_update", spy):
            picking.move_ids._action_assign()
            self.env.flush_all()
        return len(calls), picking.move_ids.mapped("state")

    def test_action_assign_does_not_reset_orderpoint_values_per_move(self):
        few, few_states = self._count_orderpoint_searches_on_assign(2, "AQA")
        many, many_states = self._count_orderpoint_searches_on_assign(20, "AQB")

        self.assertGreaterEqual(few, 1, "the spy must have seen the refresh at all")
        self.assertEqual(
            many,
            few,
            "orderpoint refresh must not scale with the number of moves "
            f"(2 moves produced {few} searches, 20 produced {many})",
        )
        self.assertEqual(
            few_states,
            ["assigned"] * 2,
            "suppressing the per-move recompute must not change the outcome",
        )
        self.assertEqual(many_states, ["assigned"] * 20)

    def test_quants_cache_is_prefetched(self):
        products = self.env["product.product"].create(
            [{"name": f"qimp-warm-{i}", "is_storable": True} for i in range(5)]
        )
        for product in products:
            self.Quant._update_available_quantity(product, self.loc, 7.0)
        self.env.flush_all()
        self.env.invalidate_all()

        cache = self.Quant._get_quants_by_products_locations(products, self.loc)
        before = self.env.cr.sql_statement_count
        for product in products:
            quants = cache[product.id, self.loc.id, False, False, False]
            self.assertTrue(quants, "the scan covered this product/location")
            self.assertEqual(quants.quantity, 7.0)
            quants.mapped("in_date")
            quants.mapped("reserved_quantity")
        self.assertEqual(
            self.env.cr.sql_statement_count,
            before,
            "cached quants must already carry their values",
        )

    def _least_packages_location(self, name):
        return self.env["stock.location"].create(
            {
                "name": name,
                "usage": "internal",
                "location_id": self.loc.id,
                "removal_strategy_id": self.env["product.removal"]
                .search([("method", "=", "least_packages")], limit=1)
                .id,
            }
        )

    def test_least_packages_skips_loose_quants_with_no_available_unit(self):
        location = self._least_packages_location("lp-available-units")
        product = self.env["product.product"].create(
            {"name": "lp-avail", "is_storable": True, "tracking": "lot"}
        )
        lots = self.env["stock.lot"].create(
            [{"name": f"lp-avail-{i}", "product_id": product.id} for i in range(4)]
        )
        package = self.env["stock.package"].create({"name": "lp-avail-pkg"})
        base = datetime(2020, 1, 1)
        for index, (lot, quantity) in enumerate(
            [(lots[0], 4.0), (lots[1], 4.0), (lots[2], 2.0)]
        ):
            self.Quant.sudo().create(
                {
                    "product_id": product.id,
                    "location_id": location.id,
                    "lot_id": lot.id,
                    "quantity": quantity,
                    "in_date": base + timedelta(days=index),
                }
            )
        self.Quant.sudo().create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "lot_id": lots[3].id,
                "quantity": 5.0,
                "package_id": package.id,
                "in_date": base + timedelta(days=3),
            }
        )
        self.env.flush_all()

        self._deliver(product, 8.0, location)
        self.assertEqual(
            self.Quant._get_available_quantity(product, location, strict=False),
            7.0,
            "2 loose + 5 packed units remain free",
        )

        reserved = self.Quant._get_reserve_quantity(product, location, 2.0)
        self.assertEqual(
            sum(quantity for _quant, quantity in reserved),
            2.0,
            "the request must be served from the loose lot that still holds stock",
        )
        picking = self._deliver(product, 2.0, location)
        self.assertEqual(picking.move_ids.state, "assigned")
        self.assertEqual(picking.move_ids.quantity, 2.0)

    def test_least_packages_still_prefers_a_whole_package(self):
        location = self._least_packages_location("lp-whole-package")
        product = self.env["product.product"].create(
            {"name": "lp-whole", "is_storable": True}
        )
        base = datetime(2020, 1, 1)
        exact = self.env["stock.package"].create({"name": "lp-whole-5"})
        other = self.env["stock.package"].create({"name": "lp-whole-3"})
        self.Quant.sudo().create(
            [
                {
                    "product_id": product.id,
                    "location_id": location.id,
                    "quantity": 5.0,
                    "package_id": exact.id,
                    "in_date": base,
                },
                {
                    "product_id": product.id,
                    "location_id": location.id,
                    "quantity": 3.0,
                    "package_id": other.id,
                    "in_date": base + timedelta(days=1),
                },
                {
                    "product_id": product.id,
                    "location_id": location.id,
                    "quantity": 10.0,
                    "in_date": base + timedelta(days=2),
                },
            ]
        )
        self.env.flush_all()
        gathered = self.Quant._gather(product, location, strict=False, qty=5.0)
        self.assertEqual(gathered.package_id, exact)

    def _deliver(self, product, quantity, location):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env["stock.picking.type"]
                .search([("code", "=", "outgoing")], limit=1)
                .id,
                "location_id": location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": quantity,
                            "product_uom_id": product.uom_id.id,
                            "location_id": location.id,
                            "location_dest_id": self.customer_location.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        return picking

    def test_gs1_barcode_quantity_rounds_instead_of_truncating(self):
        kg = self.env.ref("uom.product_uom_kgm")
        product = self.env["product.product"].create(
            {
                "name": "gs1-round",
                "is_storable": True,
                "tracking": "lot",
                "uom_id": kg.id,
                "barcode": "01234567890128",
            }
        )
        lot = self.env["stock.lot"].create(
            {"name": "GS1ROUND", "product_id": product.id}
        )
        quant = self.Quant.sudo().create(
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "lot_id": lot.id,
                "quantity": 0.0,
            }
        )
        ai = "3102"
        for quantity in (0.29, 0.58, 1.16, 2.32, 4.64):
            quant.sudo().write({"quantity": quantity})
            quant.invalidate_recordset()
            barcode = quant._get_gs1_barcode({kg.id: ai})
            encoded = barcode.split(ai)[1][:6]
            self.assertEqual(
                int(encoded) / 100,
                quantity,
                f"{quantity} must encode exactly, got {encoded}",
            )


@tagged("post_install", "-at_install")
class TestQuantTasksScope(TestStockCommon):
    def test_quant_tasks_propagates_recordset(self):
        from odoo.addons.stock.models import stock_quant_reservation as _sq

        product = self.env["product.product"].create(
            {"name": "QT Scope Product", "is_storable": True},
        )
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        self.env["stock.quant"]._update_available_quantity(
            product,
            warehouse.lot_stock_id,
            quantity=3,
        )
        quant = self.env["stock.quant"].search(
            [("product_id", "=", product.id)],
            limit=1,
        )
        seen_sizes = []
        orig = _sq.StockQuantReservation._merge_quants

        def spy(records, *args, **kwargs):
            seen_sizes.append(len(records))
            return orig(records, *args, **kwargs)

        _sq.StockQuantReservation._merge_quants = spy
        self.addCleanup(setattr, _sq.StockQuantReservation, "_merge_quants", orig)

        quant._run_maintenance_tasks()
        self.assertEqual(
            seen_sizes,
            [1],
            "a recordset call must reach the scoped tasks with its records",
        )
        self.env["stock.quant"]._run_maintenance_tasks()
        self.assertEqual(
            seen_sizes,
            [1, 0],
            "a model-level call must stay global (empty recordset)",
        )


@tagged("post_install", "-at_install")
class TestQuantIncomingDate(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def _tracked_product_with_a_lotless_sibling(self, name, lot_date, loose_date):
        product = self.env["product.product"].create(
            {"name": name, "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": f"{name}-lot", "product_id": product.id}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=lot, in_date=lot_date
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=loose_date
        )
        self.env.flush_all()
        self.env.invalidate_all()
        return product, lot

    def _lot_quant(self, product, lot):
        return self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("lot_id", "=", lot.id),
                ("location_id", "=", self.loc.id),
            ]
        )

    def test_reserving_does_not_backdate_the_incoming_date(self):
        arrived = datetime(2026, 8, 1)
        product, lot = self._tracked_product_with_a_lotless_sibling(
            "qaud-reserve", arrived, datetime(2019, 1, 1)
        )

        self.Quant._update_reserved_quantity(product, self.loc, 1.0, lot_id=lot)
        self.env.flush_all()
        self.env.invalidate_all()

        quant = self._lot_quant(product, lot)
        self.assertEqual(quant.reserved_quantity, 1.0)
        self.assertEqual(
            quant.in_date,
            arrived,
            "reserving moves no goods, so it must not adopt the lotless "
            "sibling's older in_date",
        )

    def test_a_delivery_reservation_does_not_backdate_the_incoming_date(self):
        arrived = datetime(2026, 8, 1)
        product, lot = self._tracked_product_with_a_lotless_sibling(
            "qaud-delivery", arrived, datetime(2019, 1, 1)
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.out_type_id.id,
                "location_id": self.loc.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": 2,
                            "location_id": self.loc.id,
                            "location_dest_id": self.customer_location.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            self._lot_quant(product, lot).in_date,
            arrived,
            "action_assign must not rewrite in_date -- it is the FIFO sort key",
        )

    def test_reserving_does_not_reorder_removal(self):
        product = self.env["product.product"].create(
            {"name": "qaud-order", "is_storable": True, "tracking": "lot"}
        )
        old, new = self.env["stock.lot"].create(
            [
                {"name": "qaud-order-old", "product_id": product.id},
                {"name": "qaud-order-new", "product_id": product.id},
            ]
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=old, in_date=datetime(2021, 1, 1)
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=new, in_date=datetime(2026, 1, 1)
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=1, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.Quant._gather(product, self.loc).mapped("lot_id.name")

        self.Quant._update_reserved_quantity(product, self.loc, 1.0, lot_id=new)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            self.Quant._gather(product, self.loc).mapped("lot_id.name"),
            before,
            "reserving the newest lot must not promote it ahead of the oldest "
            "under FIFO",
        )

    def test_reserving_does_not_age_stock_that_never_moved(self):
        product = self.env["product.product"].create(
            {"name": "qaud-dormant", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-dormant-lot", "product_id": product.id}
        )
        self.Quant._update_available_quantity(product, self.loc, quantity=5, lot_id=lot)
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        quant = self._lot_quant(product, lot)
        self.assertFalse(quant.date_last_movement)
        self.assertEqual(quant.days_since_last_movement, 0)

        self.Quant._update_reserved_quantity(product, self.loc, 1.0, lot_id=lot)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            self._lot_quant(product, lot).days_since_last_movement,
            0,
            "a reservation is not seven years of standing still",
        )

    def test_receiving_still_merges_to_the_oldest_incoming_date(self):
        product = self.env["product.product"].create(
            {"name": "qaud-merge", "is_storable": True}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=datetime(2026, 8, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        self.Quant._update_available_quantity(
            product, self.loc, quantity=3, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        quant = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(quant.quantity, 8)
        self.assertEqual(
            quant.in_date,
            datetime(2019, 1, 1),
            "an incoming quantity still carries the oldest in_date of its group",
        )


@tagged("post_install", "-at_install")
class TestQuantCleanReservations(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def _drift(self, count, tag):
        products = self.env["product.product"].create(
            [
                {"name": f"qaud-{tag}-{index}", "is_storable": True}
                for index in range(count)
            ]
        )
        for product in products:
            self.Quant._update_available_quantity(product, self.loc, quantity=10)
            self.Quant._update_available_quantity(
                product, self.loc, reserved_quantity=3
            )
        self.env.flush_all()
        self.env.invalidate_all()
        return products

    def _clean_cost(self, products):
        before = self.env.cr.sql_statement_count
        self.Quant._sync_reserved_quantities(products=products, locations=self.loc)
        self.env.flush_all()
        return self.env.cr.sql_statement_count - before

    def test_clean_reservations_cost_per_group_is_bounded(self):
        small = self._clean_cost(self._drift(2, "small"))
        large = self._clean_cost(self._drift(20, "large"))
        marginal = (large - small) / 18
        self.assertLessEqual(
            marginal,
            2.5,
            "correcting one drifted group must not re-gather the quants the "
            f"read_group already returned (measured {marginal:.1f} queries/group)",
        )

    def test_clean_reservations_still_corrects_the_drift(self):
        products = self._drift(3, "correct")
        self.Quant._sync_reserved_quantities(products=products, locations=self.loc)
        self.env.flush_all()
        self.env.invalidate_all()
        quants = self.Quant.search(
            [("product_id", "in", products.ids), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(
            sum(quants.mapped("reserved_quantity")),
            0,
            "a reservation with no move line behind it is dropped",
        )

    def test_clean_reservations_leaves_the_incoming_date_alone(self):
        product = self.env["product.product"].create(
            {"name": "qaud-clean-date", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-clean-lot", "product_id": product.id}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=lot, in_date=datetime(2026, 8, 1)
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        self.Quant.search(
            [("product_id", "=", product.id), ("lot_id", "=", lot.id)]
        ).sudo().write({"reserved_quantity": 2})
        self.env.flush_all()
        self.env.invalidate_all()

        self.Quant._sync_reserved_quantities(products=product, locations=self.loc)
        self.env.flush_all()
        self.env.invalidate_all()

        quant = self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("lot_id", "=", lot.id),
                ("location_id", "=", self.loc.id),
            ]
        )
        self.assertEqual(quant.in_date, datetime(2026, 8, 1))


@tagged("post_install", "-at_install")
class TestQuantRemovalStrategySeam(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]

    def test_every_selectable_strategy_resolves_to_one_object(self):
        methods = self.env["product.removal"].search([]).mapped("method")
        self.assertIn("fifo", methods, "the data strategies must be installed")
        for method in sorted(set(methods)):
            with self.subTest(removal_strategy=method):
                strategy = self.Quant._get_removal_strategy_record(method)
                self.assertIsInstance(
                    strategy,
                    RemovalStrategy,
                    "a strategy an addon added resolved to None, so _gather read"
                    " both of its behaviour flags as False without saying so",
                )
                self.assertIs(strategy, self.Quant._get_removal_strategies()[method])

    def test_the_table_is_the_seam_and_carries_the_behaviour_flags(self):
        registry_cls = type(self.Quant)
        base = registry_cls._get_removal_strategies

        def patched(records):
            strategies = base(records)
            strategies["qsh_byloc"] = RemovalStrategy(
                order=False, sort_key=lambda quant: quant.id, sorts_by_location=True
            )
            return strategies

        registry_cls._get_removal_strategies = patched
        try:
            strategy = self.Quant._get_removal_strategy_record("qsh_byloc")
            self.assertTrue(
                strategy.sorts_by_location,
                "extending the table must be enough to reach the flags",
            )
            self.assertIs(strategy.order, False)
            self.assertIsNotNone(strategy.resolve_sorted_arguments())
        finally:
            registry_cls._get_removal_strategies = base

    def test_an_unknown_strategy_still_names_itself(self):
        with self.assertRaises(UserError):
            self.Quant._get_removal_strategy_record("qsh_nonexistent")

    def test_the_table_is_a_copy_not_the_shared_constant(self):
        first = self.Quant._get_removal_strategies()
        first["qsh_scribble"] = None
        self.assertNotIn(
            "qsh_scribble",
            self.Quant._get_removal_strategies(),
            "an override that adds an entry must not mutate the module constant",
        )


@tagged("post_install", "-at_install")
class TestQuantsCacheScope(TransactionCase):
    def _cache(self, roots, products=(7,)):
        return QuantsCache(self.env["stock.quant"], products, roots)

    def test_a_descendant_is_covered_and_the_location_itself_is(self):
        cache = self._cache(["1/2/"])
        self.assertTrue(cache.is_covering(_Stub(7), _Stub(2, "1/2/")))
        self.assertTrue(cache.is_covering(_Stub(7), _Stub(99, "1/2/99/")))

    def test_a_sibling_whose_id_is_a_decimal_prefix_is_not_covered(self):
        cache = self._cache(["1/2/"])
        self.assertFalse(
            cache.is_covering(_Stub(7), _Stub(20, "1/20/")),
            "a sibling location must never be served from another's cache",
        )
        stripped = self._cache(["1/2"])
        self.assertTrue(
            stripped.is_covering(_Stub(7), _Stub(20, "1/20/")),
            "this asserts the FAILURE mode on purpose: without the trailing"
            " slash the sibling is covered, which is why the roots must always"
            " come from parent_path verbatim",
        )

    def test_the_roots_come_from_parent_path_verbatim(self):
        location = (
            self.env["stock.warehouse"]
            .search([("company_id", "=", self.env.company.id)], limit=1)
            .lot_stock_id
        )
        self.assertTrue(
            location.parent_path.endswith("/"),
            "parent_path is what QuantsCache scopes on; without the trailing"
            " slash its prefix test admits siblings",
        )
        cache = self.env["stock.quant"]._get_quants_by_products_locations(
            self.env["product.product"].browse(), location
        )
        self.assertEqual(cache._location_paths, (location.parent_path,))

    def test_an_unsaved_location_is_never_covered(self):
        cache = self._cache(["1/2/"])
        self.assertFalse(cache.is_covering(_Stub(7), _Stub(0, False)))

    def test_a_cache_with_no_usable_root_covers_nothing(self):
        cache = self._cache([False, "", None])
        self.assertEqual(cache._location_paths, ())
        self.assertFalse(cache.is_covering(_Stub(7), _Stub(2, "1/2/")))


class _Stub:
    __slots__ = ("id", "parent_path")

    def __init__(self, id_, parent_path=None):
        self.id = id_
        self.parent_path = parent_path
