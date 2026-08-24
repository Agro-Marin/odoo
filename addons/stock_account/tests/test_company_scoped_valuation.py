"""Valuation must depend on the data, not on the session.

Every test here pins a defect where a figure was drawn from `env.companies` (the
set of companies the user happens to have enabled in the switcher) instead of
`env.company` (the company that owns the stock), or where a per-company write was
fed from a deliberately cross-company aggregate.
"""

from datetime import timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestCompanyScopedValuation(TestStockValuationCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.other_company
        cls.env.user.company_ids = [Command.link(cls.company_b.id)]
        cls.wh_b = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company_b.id)], limit=1
        )
        cls.stock_b = cls.wh_b.lot_stock_id
        cls.picking_type_in_b = cls.wh_b.in_type_id
        cls.both_companies = [cls.company.id, cls.company_b.id]

    def _shared_categ(self, name, cost_method):
        """A category configured identically in both companies, as a product
        shared across companies requires."""
        categ = self.env["product.category"].create({"name": name})
        for company in (self.company, self.company_b):
            categ.with_company(company).property_cost_method = cost_method
            categ.with_company(company).property_valuation = "periodic"
        return categ

    def _shared_product(self, name, categ):
        return self.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "categ_id": categ.id,
                "uom_id": self.uom.id,
            }
        )

    def _prepare_receipt(
        self, product, company, location, picking_type, qty, unit_cost
    ):
        """A confirmed, picked receipt that has NOT been done yet, so callers can
        validate several of them in one batch."""
        move = (
            self.env["stock.move"]
            .with_company(company)
            .create(
                {
                    "product_id": product.id,
                    "location_id": self.supplier_location.id,
                    "location_dest_id": location.id,
                    "product_uom_id": self.uom.id,
                    "product_uom_qty": qty,
                    "picking_type_id": picking_type.id,
                    "company_id": company.id,
                    "price_unit": unit_cost,
                    "value_manual": unit_cost * qty,
                }
            )
        )
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        return move

    def _receive(self, product, company, location, picking_type, qty, unit_cost):
        move = self._prepare_receipt(
            product, company, location, picking_type, qty, unit_cost
        )
        move._action_done()
        return move

    def _receive_a(self, product, qty, unit_cost):
        return self._receive(
            product,
            self.company,
            self.stock_location,
            self.picking_type_in,
            qty,
            unit_cost,
        )

    def _receive_b(self, product, qty, unit_cost):
        return self._receive(
            product,
            self.company_b,
            self.stock_b,
            self.picking_type_in_b,
            qty,
            unit_cost,
        )

    # ------------------------------------------------------------------
    # `product.value` is per company
    # ------------------------------------------------------------------
    def test_manual_revaluation_does_not_cross_companies(self):
        """`_get_last_product_value` runs sudo, so it must filter on the company
        itself: the record rule cannot do it."""
        product = self._shared_product("Shared", self._shared_categ("avco", "average"))
        product.with_company(self.company_b).standard_price = 100
        product.with_company(self.company).standard_price = 10

        found = product.with_company(self.company_b)._get_last_product_value()
        self.assertEqual(
            found[product].company_id,
            self.company_b,
            "company B picked up company A's manual revaluation",
        )

    def test_other_company_revaluation_does_not_move_our_inventory_value(self):
        """Reading the valuation report in B must not see A's revaluation."""
        product = self._shared_product("Shared", self._shared_categ("avco", "average"))
        product.with_company(self.company_b).standard_price = 100
        self._receive_b(product, 10, 100)
        value_before = product.with_company(self.company_b).sudo().total_value
        self.assertEqual(value_before, 1000)

        product.with_company(self.company).standard_price = 1
        product.invalidate_recordset()

        self.assertEqual(
            product.with_company(self.company_b).sudo().total_value,
            1000,
            "company A's revaluation wrote down company B's inventory",
        )

    # ------------------------------------------------------------------
    # FIFO stack is per company
    # ------------------------------------------------------------------
    def test_fifo_stack_ignores_other_companies_receipts(self):
        product = self._shared_product("Fifo", self._shared_categ("fifo", "fifo"))
        self._receive_b(product, 10, 999)
        self._receive_a(product, 10, 10)

        for label, allowed in (
            ("single company session", [self.company.id]),
            ("multi company session", self.both_companies),
        ):
            scoped = product.with_context(allowed_company_ids=allowed).with_company(
                self.company
            )
            scoped.invalidate_recordset()
            stack, _first = scoped._run_fifo_get_stack()
            self.assertEqual(
                self.env["stock.move"].concat(*stack).company_id,
                self.company,
                f"{label}: FIFO stack reached into another company",
            )
            self.assertEqual(
                scoped._run_fifo(10),
                100,
                f"{label}: COGS valued against another company's receipt",
            )

    def test_fifo_cogs_is_independent_of_enabled_companies(self):
        """A delivery must be valued the same however many companies the user
        has ticked in the session switcher."""
        product = self._shared_product("Fifo", self._shared_categ("fifo", "fifo"))
        self._receive_b(product, 10, 999)
        self._receive_a(product, 10, 10)

        env_multi = self.env(
            context=dict(self.env.context, allowed_company_ids=self.both_companies)
        )
        out = (
            env_multi["stock.move"]
            .with_company(self.company)
            .create(
                {
                    "product_id": product.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "product_uom_id": self.uom.id,
                    "product_uom_qty": 10,
                    "picking_type_id": self.picking_type_out.id,
                    "company_id": self.company.id,
                }
            )
        )
        out._action_confirm()
        out._action_assign()
        out.quantity = 10
        out.picked = True
        out._action_done()
        self.assertEqual(out.value, 100, "COGS drawn from company B's receipt")

    # ------------------------------------------------------------------
    # `standard_price` is per company
    # ------------------------------------------------------------------
    def test_standard_price_is_not_blended_across_companies(self):
        """`total_value` is deliberately a cross-company aggregate; it must not
        reach the company-dependent `standard_price`."""
        product = self._shared_product("Fifo", self._shared_categ("fifo", "fifo"))
        self._receive_b(product, 10, 999)
        self._receive_a(product, 10, 10)
        product.invalidate_recordset()

        env_multi = self.env(
            context=dict(self.env.context, allowed_company_ids=self.both_companies)
        )
        product.with_env(env_multi).with_company(
            self.company
        ).sudo()._update_standard_price()
        product.invalidate_recordset()

        self.assertEqual(
            product.with_company(self.company).standard_price,
            10,
            "company A's cost was blended with company B's (would be 504.5)",
        )
        self.assertEqual(
            product.with_company(self.company_b).standard_price,
            999,
            "company B's cost was blended with company A's",
        )

    def test_set_value_does_not_recompute_another_companys_products(self):
        """`_set_value` groups by company; the per-company accumulators must not
        carry over between iterations."""
        categ = self._shared_categ("avco", "average")
        product_a = self._shared_product("Only in A", categ)
        product_b = self._shared_product("Only in B", categ)

        product_a.with_company(self.company_b).standard_price = 100
        self._receive_b(product_a, 10, 100)
        product_a.with_company(self.company).standard_price = 1
        self._receive_a(product_a, 10, 1)
        product_a.invalidate_recordset()
        cost_in_b_before = product_a.with_company(self.company_b).standard_price
        self.assertEqual(cost_in_b_before, 100)

        move_a = self._prepare_receipt(
            product_a, self.company, self.stock_location, self.picking_type_in, 1, 1
        )
        move_b = self._prepare_receipt(
            product_b, self.company_b, self.stock_b, self.picking_type_in_b, 1, 7
        )
        (move_a | move_b)._action_done()

        product_a.invalidate_recordset()
        self.assertEqual(
            product_a.with_company(self.company_b).standard_price,
            cost_in_b_before,
            "a batch that only moved product_a in company A changed its cost in B",
        )


@tagged("post_install", "-at_install")
class TestValuationAccountMoveBatching(TestStockValuationCommon):
    def test_one_entry_per_partner(self):
        """A batch validation spanning several customers must produce one
        valuation entry per accounting partner, not crash on a multi-record
        `partner_id`."""
        account = self._use_inventory_location_accounting()
        self.customer_location.valuation_account_id = account.id
        product = self.env["product.product"].create(
            {
                "name": "Perpetual",
                "is_storable": True,
                "categ_id": self.category_avco_auto.id,
                "uom_id": self.uom.id,
                "standard_price": 10,
            }
        )
        self._make_in_move(product, 100, unit_cost=10)

        pickings = self.env["stock.picking"]
        for name in ("Customer A", "Customer B"):
            partner = self.env["res.partner"].create({"name": name})
            pickings |= self.env["stock.picking"].create(
                {
                    "picking_type_id": self.picking_type_out.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "partner_id": partner.id,
                    "move_ids": [
                        Command.create(
                            {
                                "product_id": product.id,
                                "location_id": self.stock_location.id,
                                "location_dest_id": self.customer_location.id,
                                "product_uom_id": self.uom.id,
                                "product_uom_qty": 5,
                            }
                        )
                    ],
                }
            )
        pickings.action_confirm()
        pickings.action_assign()
        for picking in pickings:
            picking.move_ids.quantity = 5
            picking.move_ids.picked = True

        pickings.button_validate()

        account_moves = pickings.move_ids.account_move_id
        self.assertEqual(len(account_moves), 2, "expected one entry per partner")
        self.assertEqual(
            set(account_moves.mapped("partner_id.name")),
            {"Customer A", "Customer B"},
        )
        for picking in pickings:
            self.assertEqual(
                picking.move_ids.account_move_id.partner_id,
                picking.partner_id,
                "valuation entry attached to the wrong partner",
            )


@tagged("post_install", "-at_install")
class TestAvcoAuditReportOrdering(TestStockValuationCommon):
    def _avco_product(self, name):
        categ = self.env["product.category"].create({"name": f"avco {name}"})
        categ.property_cost_method = "average"
        categ.property_valuation = "periodic"
        return self.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "categ_id": categ.id,
                "uom_id": self.uom.id,
            }
        )

    def _replayed(self, product):
        rows = self.env["stock.avco.report"].search(
            [("product_id", "=", product.id), ("company_id", "=", self.company.id)]
        )
        return rows.sorted(self.env["stock.avco.report"]._REPLAY_ORDER)

    def test_adjustments_replay_in_chronological_order(self):
        """`product.value` rows carry a negated id so they stay unique across the
        UNION; that id must never act as the chronological tiebreak."""
        product = self._avco_product("Audited")
        day1 = fields.Datetime.now() - timedelta(days=3)
        day2 = fields.Datetime.now() - timedelta(days=2)
        day3 = fields.Datetime.now() - timedelta(days=1)
        with freeze_time(day1):
            product.with_company(self.company).standard_price = 10
        with freeze_time(day2):
            self._make_in_move(product, 10, unit_cost=10)
        with freeze_time(day3):
            product.with_company(self.company).standard_price = 50

        replayed = self._replayed(product)
        self.assertEqual(
            [r.res_model_name for r in replayed],
            ["product.value", "stock.move", "product.value"],
            "the receipt must replay between the two revaluations",
        )
        self.assertEqual([r.value for r in replayed], [10, 100, 50])
        self.assertEqual(
            replayed[-1].avco_value,
            50,
            "the audit must end on the cost the product actually carries",
        )

    def test_same_instant_revaluation_replays_after_the_move(self):
        """When a revaluation and a move share a timestamp the engine treats the
        revaluation as the later event (`_run_average_batch` skips moves whose
        `date <= product.value.date`); the audit must agree or it justifies a
        different figure than the one stored."""
        product = self._avco_product("Same instant")
        instant = fields.Datetime.now() - timedelta(days=1)
        with freeze_time(instant):
            self._make_in_move(product, 10, unit_cost=10)
            product.with_company(self.company).standard_price = 50

        replayed = self._replayed(product)
        self.assertEqual(
            [r.res_model_name for r in replayed],
            ["stock.move", "product.value"],
            "a same-instant revaluation must replay after the move",
        )
        self.assertEqual(replayed[-1].avco_value, 50)
        self.assertEqual(
            replayed[-1].avco_value,
            product.with_company(self.company).standard_price,
            "the audit disagrees with the stored cost it is meant to justify",
        )

    def test_pending_records_are_visible_to_the_replay(self):
        """The view is `_auto = False`, so `search()` flushes a model with no
        table; the replay has to flush the source tables itself."""
        categ = self.env["product.category"].create({"name": "avco"})
        categ.property_cost_method = "average"
        categ.property_valuation = "periodic"
        product = self.env["product.product"].create(
            {
                "name": "Pending",
                "is_storable": True,
                "categ_id": categ.id,
                "uom_id": self.uom.id,
            }
        )
        product.with_company(self.company).standard_price = 10
        move = self._make_in_move(product, 10, unit_cost=10)

        rows = self.env["stock.avco.report"].search(
            [("product_id", "=", product.id), ("company_id", "=", self.company.id)]
        )
        move_rows = rows.filtered(lambda r: r.res_model_name == "stock.move")
        self.assertTrue(move_rows, "the pending receipt is missing from the report")
        self.assertEqual(move_rows.quantity, move._get_valued_qty())


@tagged("post_install", "-at_install")
class TestValuationBatching(TestStockValuationCommon):
    """Valuing a catalogue must not cost a fixed number of queries per product.

    `_run_average_batch` walks every product's moves in one ordered pass; if it
    ever reverts to a pass per product, each product costs its own round of
    move/move-line fetches and closing a real catalogue becomes tens of
    thousands of queries.
    """

    def _seed(self, categ, count, offset):
        products = self.env["product.product"].create(
            [
                {
                    "name": f"Batch {offset}_{i}",
                    "is_storable": True,
                    "categ_id": categ.id,
                    "uom_id": self.uom.id,
                    "standard_price": 10,
                }
                for i in range(count)
            ]
        )
        for product in products:
            self._make_in_move(product, 10, unit_cost=10)
        self.env.flush_all()
        return products

    def _stock_value_query_count(self):
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        self.company.stock_value()
        return self.env.cr.sql_log_count - before

    def test_stock_value_does_not_scale_with_the_catalogue(self):
        categ = self.env["product.category"].create({"name": "batched"})
        categ.property_cost_method = "average"
        categ.property_valuation = "periodic"

        self._seed(categ, 10, 0)
        small = self._stock_value_query_count()
        self._seed(categ, 40, 1)
        large = self._stock_value_query_count()

        # Five times the catalogue must not cost anything like five times the
        # queries. The bound is deliberately loose -- it is here to catch a
        # return to per-product batching, not to pin an exact number.
        self.assertLess(
            large,
            small * 2,
            f"valuing the catalogue scales with its size ({small} -> {large} "
            f"queries for 5x the products)",
        )


@tagged("post_install", "-at_install")
class TestLotValuationBatching(TestStockValuationCommon):
    """Valuing many lots must give the same answer as valuing them one by one.

    `_run_average_batch` replays all of a product's lots in a single pass over its
    moves; this pins that result against the one-lot-at-a-time path it replaced.
    """

    def setUp(self):
        super().setUp()
        self.categ = self.env["product.category"].create({"name": "avco lots"})
        self.categ.property_cost_method = "average"
        self.categ.property_valuation = "periodic"
        self.product = self.env["product.product"].create(
            {
                "name": "Lot valuated",
                "is_storable": True,
                "categ_id": self.categ.id,
                "uom_id": self.uom.id,
                "tracking": "lot",
                "lot_valuated": True,
                "standard_price": 10,
            }
        )
        self.lots = self.env["stock.lot"].create(
            [
                {
                    "name": f"LOT{i}",
                    "product_id": self.product.id,
                    "company_id": self.company.id,
                }
                for i in range(6)
            ]
        )

    def _batched(self):
        self.lots.invalidate_recordset()
        return {lot.id: (lot.avg_cost, lot.total_value) for lot in self.lots}

    def _one_by_one(self):
        """Value each lot in isolation. Re-browsing is what makes this different
        from `_batched`: iterating a recordset keeps the prefetch set, so the
        compute would still receive -- and batch -- all six lots."""
        result = {}
        for lot_id in self.lots.ids:
            self.lots.invalidate_recordset()
            lot = (
                self.env["stock.lot"]
                .browse(lot_id)
                .with_context(
                    **{
                        key: value
                        for key, value in self.lots.env.context.items()
                        if key == "to_date"
                    }
                )
            )
            result[lot_id] = (lot.avg_cost, lot.total_value)
        return result

    def _assert_batched_matches_single(self):
        one_by_one = self._one_by_one()
        batched = self._batched()
        for lot in self.lots:
            single_cost, single_value = one_by_one[lot.id]
            batch_cost, batch_value = batched[lot.id]
            self.assertAlmostEqual(
                batch_cost, single_cost, places=6, msg=f"{lot.name} avg_cost"
            )
            self.assertAlmostEqual(
                batch_value, single_value, places=6, msg=f"{lot.name} total_value"
            )
        # The comparison is only meaningful if the lots do not all carry the same
        # cost: identical values would match under any amount of cross-lot bleed.
        self.assertGreater(
            len({round(cost, 6) for cost, _value in batched.values()}),
            1,
            "the scenario produced one cost for every lot, so it cannot detect "
            "cross-lot contamination",
        )
        return batched

    def test_batched_matches_one_by_one_on_receipts(self):
        self._make_in_move(self.product, 12, unit_cost=10, lot_ids=self.lots)
        self._make_in_move(self.product, 6, unit_cost=40, lot_ids=self.lots[:3])
        batched = self._assert_batched_matches_single()
        # Lots that only received at 10 must stay at 10; the ones that also
        # received at 40 must sit strictly above it.
        self.assertAlmostEqual(batched[self.lots[5].id][0], 10, places=6)
        self.assertGreater(batched[self.lots[0].id][0], 10)

    def test_batched_matches_one_by_one_with_outs_and_revaluation(self):
        self._make_in_move(self.product, 12, unit_cost=10, lot_ids=self.lots)
        self._make_in_move(self.product, 12, unit_cost=25, lot_ids=self.lots[:4])
        self._make_out_move(self.product, 4, lot_ids=self.lots[:2])
        # A manual revaluation on one lot only: the batched pass must seed that
        # lot from it and leave the others on their own history.
        self.lots[0].standard_price = 99
        self._assert_batched_matches_single()

    def test_batched_matches_one_by_one_at_a_past_date(self):
        self._make_in_move(self.product, 12, unit_cost=10, lot_ids=self.lots)
        self._make_in_move(self.product, 6, unit_cost=40, lot_ids=self.lots[:3])
        at_date = fields.Datetime.now()
        self.lots = self.lots.with_context(to_date=at_date)
        self._assert_batched_matches_single()

    def test_lot_valuation_does_not_scale_with_the_lot_count(self):
        self._make_in_move(self.product, 12, unit_cost=10, lot_ids=self.lots)
        self.env.flush_all()

        self.lots.invalidate_recordset()
        before = self.env.cr.sql_log_count
        self.lots[:2].mapped("total_value")
        two_lots = self.env.cr.sql_log_count - before

        self.lots.invalidate_recordset()
        before = self.env.cr.sql_log_count
        self.lots.mapped("total_value")
        six_lots = self.env.cr.sql_log_count - before

        self.assertLess(
            six_lots,
            two_lots * 2,
            f"valuing lots scales with their number ({two_lots} -> {six_lots} "
            f"queries for 3x the lots)",
        )


@tagged("post_install", "-at_install")
class TestQuantValuationBatching(TestStockValuationCommon):
    """`stock.quant.value` is a Python aggregate (the field is not stored), so the
    grouped Inventory Valuation list resolves it for every quant in the group.
    It must resolve a whole company at a time, not a quant -- or a product -- at
    a time."""

    def _avco_categ(self):
        categ = self.env["product.category"].create({"name": "avco quants"})
        categ.property_cost_method = "average"
        categ.property_valuation = "periodic"
        return categ

    def _seed(self, categ, count, offset):
        products = self.env["product.product"].create(
            [
                {
                    "name": f"Quant {offset}_{i}",
                    "is_storable": True,
                    "categ_id": categ.id,
                    "uom_id": self.uom.id,
                    "standard_price": 10,
                }
                for i in range(count)
            ]
        )
        for product in products:
            self._make_in_move(product, 10, unit_cost=10)
        self.env.flush_all()
        return products

    def _read_group_query_count(self, products):
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        self.env["stock.quant"]._read_group(
            [("product_id", "in", products.ids)], ["location_id"], ["value:sum"]
        )
        return self.env.cr.sql_log_count - before

    def test_value_sum_does_not_scale_with_the_product_count(self):
        categ = self._avco_categ()
        small = self._read_group_query_count(self._seed(categ, 10, 0))
        large = self._read_group_query_count(self._seed(categ, 40, 1))
        # Resolving per company costs the same for 10 or 40 products, so the bound
        # is tight enough to also catch a regression to per-product resolution
        # (which measured 39 -> 70 for these two sizes).
        self.assertLess(
            large,
            small * 1.5,
            f"aggregating quant value scales with the product count "
            f"({small} -> {large} queries for 4x the products)",
        )

    def test_lot_valuated_product_with_an_unlotted_quant(self):
        """A lot-valuated product can still carry a quant with no lot: the guard on
        enabling the flag only inspects the stock present at that moment. Such a
        quant is valued against the product, so it must not be looked up as a lot."""
        categ = self._avco_categ()
        product = self.env["product.product"].create(
            {
                "name": "Partly lotted",
                "is_storable": True,
                "categ_id": categ.id,
                "uom_id": self.uom.id,
                "tracking": "lot",
                "lot_valuated": True,
                "standard_price": 10,
            }
        )
        lot = self.env["stock.lot"].create(
            {"name": "L1", "product_id": product.id, "company_id": self.company.id}
        )
        self._make_in_move(product, 10, unit_cost=10, lot_ids=lot)
        # A quant that carries no lot, alongside the lotted stock.
        unlotted = self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": self.stock_location.id,
                "quantity": 5,
                "company_id": self.company.id,
            }
        )
        self.env.flush_all()
        self.env.invalidate_all()

        # Must resolve through the product path without a KeyError. The unlotted
        # quant takes its share of the product's value spread over all on-hand
        # quantity -- the lot holds 10 units worth 100 and the quant adds 5 unvalued
        # units, so 5 * 100 / 15. This is the pre-batching result, pinned here
        # because the quant is easy to route down the lot path by mistake.
        quants = self.env["stock.quant"].search([("product_id", "=", product.id)])
        self.assertIn(unlotted, quants)
        values = {quant.id: quant.value for quant in quants}
        self.assertAlmostEqual(
            values[unlotted.id],
            5 * 100 / 15,
            places=2,
            msg="the unlotted quant was not valued against its product",
        )


@tagged("post_install", "-at_install")
class TestValuationScopeReuse(TestStockValuationCommon):
    """`_with_valuation_context()` resolves the company's valued locations with a
    search. Loops that value product after product re-enter it constantly, so it
    has to be free once the recordset already carries the scope -- and it must
    still re-derive when the company changes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.company_ids = [Command.link(cls.other_company.id)]

    def test_rescoping_the_same_company_is_free(self):
        product = self.env["product.product"].search(
            [("is_storable", "=", True)], limit=1
        )
        scoped = product._with_valuation_context()
        self.env.flush_all()

        before = self.env.cr.sql_log_count
        rescoped = scoped._with_valuation_context()
        self.assertEqual(
            self.env.cr.sql_log_count,
            before,
            "re-scoping an already-scoped recordset searched the locations again",
        )
        for key in ("location", "owners", "strict"):
            self.assertEqual(
                rescoped.env.context[key],
                scoped.env.context[key],
                f"re-scoping changed {key}",
            )

    def test_rescoping_another_company_re_derives(self):
        product = self.env["product.product"].search(
            [("is_storable", "=", True)], limit=1
        )
        scoped_a = product.with_company(self.company)._with_valuation_context()
        scoped_b = scoped_a.with_company(self.other_company)._with_valuation_context()

        self.assertNotEqual(
            scoped_b.env.context["location"],
            scoped_a.env.context["location"],
            "the scope was carried over to a different company",
        )
        self.assertEqual(
            scoped_b.env.context["owners"],
            [False, self.other_company.partner_id.id],
            "the owner scope was carried over to a different company",
        )


@tagged("post_install", "-at_install")
class TestDoneMoveLineRevaluation(TestStockValuationCommon):
    """`is_in` / `is_out` / `is_dropship` are stored as of completion and their
    `depends` deliberately ignore the move line fields `_is_in()` / `_is_out()`
    read -- otherwise any write to a line would re-classify historical moves and
    restate past valuations. The places that knowingly change such a field on a
    done move must re-derive them, or they decide whether to revalue from a stale
    classification."""

    def _avco_product(self, name):
        categ = self.env["product.category"].create({"name": f"reval {name}"})
        categ.property_cost_method = "average"
        categ.property_valuation = "periodic"
        return self.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "categ_id": categ.id,
                "uom_id": self.uom.id,
                "standard_price": 10,
            }
        )

    def _total_value(self, product):
        product.invalidate_recordset()
        return product.with_company(self.company).sudo().total_value

    def test_marking_a_done_receipt_as_consigned_removes_its_value(self):
        """Consignment stock is not owned, so a receipt corrected to name a
        third-party owner must stop contributing to the valuation."""
        product = self._avco_product("Consigned later")
        self._make_in_move(product, 10, unit_cost=10)
        consigned = self._make_in_move(product, 10, unit_cost=50)
        self.assertEqual(self._total_value(product), 600)
        self.assertTrue(consigned.is_in)

        consigned.move_line_ids.write({"owner_id": self.owner.id})

        consigned.invalidate_recordset()
        self.assertFalse(
            consigned.is_in,
            "the move stayed classified as incoming after being consigned",
        )
        self.assertEqual(
            self._total_value(product),
            100,
            "consigned goods are still counted in the company's stock value",
        )

    def test_clearing_the_owner_brings_a_receipt_back_into_the_valuation(self):
        """The reverse correction: goods first booked as consignment turn out to
        be owned."""
        product = self._avco_product("Owned later")
        self._make_in_move(product, 10, unit_cost=10)
        consigned = self._make_in_move(
            product, 10, unit_cost=50, owner_id=self.owner.id
        )
        self.assertFalse(consigned.is_in)
        self.assertEqual(self._total_value(product), 100)

        consigned.move_line_ids.write({"owner_id": False})

        consigned.invalidate_recordset()
        self.assertTrue(
            consigned.is_in,
            "the move stayed excluded after the consignment was cleared",
        )
        self.assertEqual(
            self._total_value(product),
            600,
            "the now-owned goods were not brought back into the stock value",
        )
