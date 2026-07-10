from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.stock.models.stock_quant import (
    _distribute_reservation,
    _least_packages_search,
    _LeastPackagesPriorityQueue,
    _ReservationCandidate,
)
from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestLeastPackagesSearch(TransactionCase):
    """Pure, DB-free unit tests for the extracted least_packages A* solver.

    `_least_packages_search(qty_by_package, qty)` returns the winning node's
    `taken_packages` tuple. `qty_by_package` is a list of `(key, available_qty)`
    where `key` is a package id or None for a virtual single unit; singles are
    kept last, exactly as `_run_least_packages_removal_strategy_astar` builds it.
    """

    def _num_packages(self, taken):
        return len(taken)

    def test_exact_single_package(self):
        taken = _least_packages_search([(10, 5), (11, 3)], 5)
        self.assertEqual(taken, ((10, 5),))

    def test_prefers_fewer_packages_over_exactness(self):
        # 8 is reachable by one package (10) or two (11+12); the solver minimises count.
        taken = _least_packages_search([(10, 8), (11, 5), (12, 3)], 8)
        self.assertEqual(taken, ((10, 8),))

    def test_multi_single_exact_cover(self):
        # A too-big package forces the exact cover to be two singles.
        taken = _least_packages_search([(10, 9), (None, 1), (None, 1)], 2)
        self.assertEqual(taken, ((None, 1), (None, 1)))

    def test_overselect_fallback_when_no_exact(self):
        # qty 4 cannot be matched exactly by a single package of 5; best leaf overselects.
        taken = _least_packages_search([(10, 5)], 4)
        self.assertEqual(taken, ((10, 5),))
        self.assertEqual(self._num_packages(taken), 1)

    def test_insufficient_stock_returns_closest_leaf(self):
        # Not enough available: returns the closest partial cover rather than raising.
        taken = _least_packages_search([(10, 2)], 5)
        self.assertEqual(taken, ((10, 2),))

    def test_priority_queue_never_compares_items_on_tie(self):
        """Equal-priority frontier entries must be ordered by their insertion index,
        never by comparing the item nodes themselves. A node's `taken_packages`
        mixes `None` (single) and `int` (package) keys, and `None < int` raises
        TypeError on Python 3. Previously this was avoided only as an emergent
        consequence of the amount-dedup; the insertion-index tie-breaker makes it a
        structural guarantee. Push items that explode if ever compared to prove the
        heap never touches them on a tie.
        """

        class Explodes:
            def __lt__(self, other):
                raise AssertionError("frontier items must never be compared")

            __gt__ = __lt__
            __le__ = __lt__
            __ge__ = __lt__

        pq = _LeastPackagesPriorityQueue()
        first, second, third = Explodes(), Explodes(), Explodes()
        pq.put(first, 1.0)
        pq.put(second, 1.0)  # identical priority -> must fall back to insertion order
        pq.put(third, 1.0)
        # FIFO among equal priorities, and crucially: no TypeError/AssertionError.
        self.assertIs(pq.get(), first)
        self.assertIs(pq.get(), second)
        self.assertIs(pq.get(), third)
        self.assertTrue(pq.empty())


@tagged("post_install", "-at_install")
class TestDistributeReservation(TransactionCase):
    """Pure, DB-free unit tests for the extracted reservation allocator.

    `_distribute_reservation(candidates, quantity, available_quantity, digits)`
    returns a list of `(handle, amount)` pairs. Candidates are
    `_ReservationCandidate(handle, on_hand, reserved, key)` in removal-strategy
    order; `handle`/`key` are opaque, so plain strings stand in for quants here.
    """

    DIGITS = 2

    def _cand(self, handle, on_hand, reserved, key=None):
        # Default each candidate to its own key (no interchangeable grouping).
        return _ReservationCandidate(handle, on_hand, reserved, key or handle)

    def test_zero_quantity_is_noop(self):
        cands = [self._cand("a", 10, 0)]
        self.assertEqual(_distribute_reservation(cands, 0, 10, self.DIGITS), [])

    def test_reserve_stops_at_quantity(self):
        # Two quants of 10 available; reserve 8 -> all from the first.
        cands = [self._cand("a", 10, 0), self._cand("b", 10, 0)]
        res = _distribute_reservation(cands, 8, 20, self.DIGITS)
        self.assertEqual(res, [("a", 8)])

    def test_reserve_spans_multiple_candidates(self):
        cands = [self._cand("a", 5, 0), self._cand("b", 5, 0)]
        res = _distribute_reservation(cands, 8, 10, self.DIGITS)
        self.assertEqual(res, [("a", 5), ("b", 3)])

    def test_reserve_skips_fully_reserved(self):
        # First quant has no slack; allocation moves to the second.
        cands = [self._cand("a", 5, 5), self._cand("b", 5, 0)]
        res = _distribute_reservation(cands, 3, 5, self.DIGITS)
        self.assertEqual(res, [("b", 3)])

    def test_reserve_entire_available_budget(self):
        # Reserving exactly the whole available budget drains both quants and stops
        # cleanly (the caller pre-caps quantity to available, so they hit zero together).
        cands = [self._cand("a", 4, 1), self._cand("b", 5, 0)]  # slack 3 + 5 = 8
        res = _distribute_reservation(cands, 8, 8, self.DIGITS)
        self.assertEqual(res, [("a", 3), ("b", 5)])

    def test_negative_available_absorbed_within_group(self):
        """A quant over-reserved into negative available must be absorbed by the
        positive slack of another quant sharing its key, before that slack is used
        to reserve fresh quantity."""
        # a: -3 available (over-reserved), b: +10 available, same key "g".
        cands = [self._cand("a", 2, 5, key="g"), self._cand("b", 10, 0, key="g")]
        # Reserve 4. b's 10 slack first absorbs a's 3 negative, leaving 7 to reserve.
        res = _distribute_reservation(cands, 4, 7, self.DIGITS)
        self.assertEqual(res, [("b", 4)])

    def test_negative_available_not_absorbed_across_groups(self):
        # a's negative belongs to key "g1"; b is "g2" and must not absorb it.
        cands = [self._cand("a", 2, 5, key="g1"), self._cand("b", 10, 0, key="g2")]
        res = _distribute_reservation(cands, 4, 7, self.DIGITS)
        self.assertEqual(res, [("b", 4)])

    def test_unreserve_releases_up_to_reserved(self):
        # Negative quantity releases reservations, capped per candidate at `reserved`.
        cands = [self._cand("a", 10, 4), self._cand("b", 10, 4)]
        res = _distribute_reservation(cands, -6, 8, self.DIGITS)
        self.assertEqual(res, [("a", -4), ("b", -2)])


@tagged("post_install", "-at_install")
class TestStockQuantImprovements(TestStockCommon):
    """Regression tests for the stock.quant refactors (batched create, inventory-key
    coalescing, sn_duplicated scoping, _unlink_zero_quants scoping, is_outdated helper,
    and the _gather cache path None-safety)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location
        cls.products = cls.env["product.product"].create(
            [{"name": f"qimp-{i}", "is_storable": True} for i in range(5)]
        )

    # ---- #A: non-inventory create() must batch into a single INSERT ---------
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
        # order + content preserved
        self.assertEqual(quants.product_id, self.products)
        self.assertEqual(set(quants.mapped("quantity")), {3.0})

    def test_create_preserves_order_mixed(self):
        """A batch mixing plain rows keeps the returned recordset in vals order."""
        vals_list = [
            {"product_id": p.id, "location_id": self.loc.id, "quantity": float(i + 1)}
            for i, p in enumerate(self.products)
        ]
        quants = self.Quant.create(vals_list)
        self.assertEqual(quants.product_id.ids, self.products.ids)
        self.assertEqual(quants.mapped("quantity"), [1.0, 2.0, 3.0, 4.0, 5.0])

    # ---- #5: the two inventory keys must not cross-contaminate --------------
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
        # auto_apply key present -> value 0 is authoritative; the other key is ignored.
        self.assertEqual(quant.quantity, 0.0)

    # ---- #2: _compute_sn_duplicated must not write outside self -------------
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
        # Compute only qa; qb must NOT be pulled into cache by the compute.
        _ = qa.sn_duplicated
        self.assertFalse(
            self.env.cache.contains(qb, type(qb).sn_duplicated),
            "computing sn_duplicated on qa must not write it onto qb (outside self)",
        )
        # Both are genuinely duplicated, detection stays global.
        self.assertTrue(qa.sn_duplicated)
        self.env.invalidate_all()
        self.assertTrue(qb.sn_duplicated)

    # ---- #11: _unlink_zero_quants scope (recordset vs model level) ----------
    def test_unlink_zero_quants_scoping(self):
        px, py = self.products[0], self.products[1]
        qx = self.Quant.create(
            {"product_id": px.id, "location_id": self.loc.id, "quantity": 0.0}
        )
        qy = self.Quant.create(
            {"product_id": py.id, "location_id": self.loc.id, "quantity": 0.0}
        )
        self.env.cr.flush()
        # Scoped call: only qx's product/location is in scope -> qy survives.
        qx._unlink_zero_quants()
        self.assertFalse(
            qx.exists(), "scoped call should remove the in-scope zero quant"
        )
        self.assertTrue(
            qy.exists(), "scoped call must not touch out-of-scope zero quants"
        )
        # Model-level (empty self) call: global sweep removes qy too.
        self.env["stock.quant"]._unlink_zero_quants()
        self.assertFalse(qy.exists(), "model-level call should sweep all zero quants")

    # ---- #8: compute and search agree on is_outdated -----------------------
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
        # Persist the count so inventory_diff_quantity is frozen at count time
        # (it depends on inventory_quantity, not on the live on-hand quantity).
        self.env.flush_all()
        # Now the on-hand quantity drifts, as it would when stock moves after a count.
        quant.sudo().write({"quantity": 9.0})
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertTrue(quant.is_outdated)
        found = self.env["stock.quant"].search([("is_outdated", "in", [True])])
        self.assertIn(quant, found, "search(is_outdated) must agree with the compute")

        # Negation path: `_search_is_outdated` only implements the positive `in`
        # operator and returns NotImplemented otherwise, delegating to the ORM which
        # inverts `not in` -> `in` and negates. So `= False` must be the *exact*
        # complement of `= True`, never a copy of it. (Guards the search method from
        # ever growing an implementation that ignores the operator.)
        all_quants = self.env["stock.quant"].search([])
        outdated = self.env["stock.quant"].search([("is_outdated", "=", True)])
        not_outdated = self.env["stock.quant"].search([("is_outdated", "=", False)])
        self.assertIn(quant, outdated)
        self.assertNotIn(quant, not_outdated)
        self.assertFalse(outdated & not_outdated, "True/False sets must be disjoint")
        self.assertEqual(
            outdated | not_outdated, all_quants, "False must be the complement of True"
        )

    # ---- last_count_date: previously-uncovered compute ----------------------
    def test_last_count_date_tracks_inventory_move(self):
        """`_compute_last_count_date` surfaces the newest *done inventory* move-line
        date onto the matching quant. This compute had no coverage; the test also
        pins the 2x2 (location, package) cross product that builds the lookup keys —
        an applied count's move-line reaches the quant via its destination location.
        """
        product = self.env["product.product"].create(
            {"name": "qimp-lastcount", "is_storable": True}
        )
        # Creating with `inventory_quantity_auto_apply` applies the count immediately,
        # leaving a done inventory stock.move.line from the loss location into self.loc.
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

    # ---- #B: _gather cache path tolerates None package/owner ----------------
    def test_gather_cache_path_none_package_owner(self):
        product = self.products[3]
        self.Quant._update_available_quantity(product, self.loc, 2.0)
        self.env.cr.flush()
        cache = self.Quant._get_quants_by_products_locations(product, self.loc)
        # package_id / owner_id default to None; the cache path must not raise.
        res = self.Quant.with_context(quants_cache=cache)._gather(
            product, self.loc, strict=True
        )
        self.assertEqual(res.product_id, product)

    # ---- #C: least_packages domain resolves multi-single from one record -----
    def test_least_packages_multi_single_single_query(self):
        """A least_packages gather whose exact cover needs several singles from a
        single unpackaged quant must not crash and must resolve the singles with
        one query (the old code re-ran the search once per single)."""
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
        # One package of 9 (too big for an exact 3) + one unpackaged record of 6.
        self.Quant._update_available_quantity(product, self.loc, 9.0, package_id=pkg)
        self.Quant._update_available_quantity(product, self.loc, 6.0)
        self.env.invalidate_all()

        # Count searches issued *while resolving singles* (inside _least_packages_domain).
        # The exact cover of 3 is three (None, 1) singles from one unpackaged record, so
        # the pre-fix pop()+re-search-on-empty code ran this search 3 times; now once.
        cls = type(self.Quant)
        orig_search, orig_domain = cls.search, cls._least_packages_domain
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
        cls._least_packages_domain = counting_domain
        try:
            res = self.Quant._gather(product, self.loc, qty=3)
        finally:
            cls.search = orig_search
            cls._least_packages_domain = orig_domain

        # Exact cover of 3 must come from the unpackaged record (package is 9).
        self.assertTrue(res, "gather must return the unpackaged quant")
        self.assertEqual(res.package_id.ids, [], "should pick the unpackaged quant")
        self.assertEqual(
            state["singles_searches"],
            1,
            "singles must be resolved with a single query, not one per unit",
        )

    # ---- #A1: least_packages must not expand singles when there are no packages --
    def test_least_packages_no_packages_is_noop(self):
        """With only unpackaged stock (no real packages) the strategy is a guaranteed
        no-op: it must return the domain *without* running the A* solver — i.e. without
        first expanding every unpackaged unit into an individual (None, 1) entry. This
        locks the early-return placement; regressing it reintroduces O(units) work (and
        an unguarded allocation) for a call that changes nothing.
        """
        from odoo.addons.stock.models import stock_quant as _sq

        strat = self.env["product.removal"].search(
            [("method", "=", "least_packages")], limit=1
        )
        categ = self.env["product.category"].create(
            {"name": "qimp-lp-noop", "removal_strategy_id": strat.id}
        )
        product = self.env["product.product"].create(
            {"name": "qimp-lp-noop-prod", "is_storable": True, "categ_id": categ.id}
        )
        # Unpackaged stock only — no stock.package anywhere for this product.
        self.Quant._update_available_quantity(product, self.loc, 5.0)
        self.env.invalidate_all()

        base_domain = [
            ("product_id", "=", product.id),
            ("location_id", "=", self.loc.id),
        ]
        calls = {"n": 0}
        original = _sq._least_packages_search

        def spy(qty_by_package, qty):
            calls["n"] += 1
            return original(qty_by_package, qty)

        _sq._least_packages_search = spy
        try:
            res = self.Quant._run_least_packages_removal_strategy_astar(base_domain, 3)
        finally:
            _sq._least_packages_search = original

        self.assertEqual(
            calls["n"], 0, "no real packages -> the A* solver must never run"
        )
        # The no-op returns the (optimized) input domain unchanged.
        from odoo.fields import Domain

        self.assertEqual(res, Domain(base_domain).optimize(self.Quant))

    # ---- #A2: cache-path and search-path _gather agree on fifo/lifo order --------
    def test_gather_cache_path_matches_search_order(self):
        """A strict _gather must return quants in the same order whether or not a
        quants_cache is in context; otherwise the first quant locked/consumed downstream
        depends on the presence of a cache. The cache is keyed but unordered, so the
        fifo/lifo in_date ordering has to be replicated on the cache branch.
        """
        product = self.env["product.product"].create(
            {"name": "qimp-order", "is_storable": True}
        )
        # Two un-merged rows, identical characteristics, with the *earlier* in_date on
        # the *higher* id so id-order and in_date-order genuinely diverge.
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

    # ---- C1: write() must not silently drop a mixed-recordset forbidden write ----
    def test_write_mixed_recordset_does_not_silently_drop(self):
        """A forbidden-field write in inventory mode is a silent no-op only when *every*
        quant sits in an inventory-adjustment location. If a real (internal) quant shares
        the recordset, the operation is restricted and must be reported, not swallowed —
        the old `any(... == "inventory")` gate silently dropped the change for everyone.
        """
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
        # Mixed set + forbidden field (owner_id) -> must raise, not no-op.
        with self.assertRaises(UserError):
            (q_internal | q_inv).with_context(inventory_mode=True).write(
                {"owner_id": owner.id}
            )
        self.env.invalidate_all()
        self.assertFalse(
            q_internal.owner_id, "the raise must have rolled back the whole write"
        )
        # All-inventory-location set stays a silent no-op returning True.
        self.assertTrue(
            q_inv.with_context(inventory_mode=True).write({"owner_id": owner.id})
        )
        self.env.invalidate_all()
        self.assertFalse(
            q_inv.owner_id, "inventory-location forbidden write is a no-op"
        )

    # ---- P1: reservation reuses its gather except for least_packages -------------
    def _count_gather_calls(self, fn):
        import odoo.addons.stock.models.stock_quant as _sq

        orig = _sq.StockQuant._gather
        calls = {"n": 0}

        def spy(records, *args, **kwargs):
            calls["n"] += 1
            return orig(records, *args, **kwargs)

        _sq.StockQuant._gather = spy
        try:
            fn()
        finally:
            _sq.StockQuant._gather = orig
        return calls["n"]

    def test_reserve_reuses_gather_for_fifo(self):
        """fifo reservation must gather once: the availability computation reuses the
        already-gathered recordset instead of issuing a second identical search."""
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
        """least_packages narrows the gather by qty, so availability must be measured
        over a fresh full gather — locking in that the reuse stays conditional."""
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
        import odoo.addons.stock.models.stock_quant as _sq

        orig = _sq.StockQuant._get_removal_strategy
        calls = {"n": 0}

        def spy(records, *args, **kwargs):
            calls["n"] += 1
            return orig(records, *args, **kwargs)

        _sq.StockQuant._get_removal_strategy = spy
        try:
            fn()
        finally:
            _sq.StockQuant._get_removal_strategy = orig
        return calls["n"]

    def test_reserve_resolves_strategy_once_fifo(self):
        """The removal strategy must be resolved exactly once per reservation: the
        gather and the availability computation both receive the pre-resolved value
        instead of each re-walking the category + location parent chain."""
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
        """least_packages re-gathers for availability, but that re-gather must still
        reuse the already-resolved strategy — one resolution total, not three."""
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
        """_get_removal_strategy resolves the location chain through parent_path: the
        nearest ancestor carrying a strategy wins over a farther one, and the
        location's own strategy wins over every ancestor."""
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
        # Farther ancestor closest, nearer ancestor lifo -> nearer (lifo) wins.
        chain[0].removal_strategy_id = closest
        chain[2].removal_strategy_id = lifo
        self.env.cr.flush()
        self.env.invalidate_all()
        self.assertEqual(self.Quant._get_removal_strategy(product, deep), "lifo")
        # The location's own strategy beats every ancestor.
        deep.removal_strategy_id = closest
        self.env.cr.flush()
        self.env.invalidate_all()
        self.assertEqual(self.Quant._get_removal_strategy(product, deep), "closest")

    # ---- C3: action_apply_all degrades gracefully without active_domain ----------
    def test_action_apply_all_without_active_domain(self):
        """No active_domain in context must fall back to self, not KeyError (and not a
        catch-all empty-domain search that would sweep every quant)."""
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
            quant._reservation_key(),
            (quant.location_id, quant.lot_id, quant.package_id, quant.owner_id),
        )
