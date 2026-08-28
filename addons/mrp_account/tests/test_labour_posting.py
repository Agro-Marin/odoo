from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.mrp_account.tests.common import TestBomPriceCommon


@tagged("post_install", "-at_install")
class TestLabourPosting(TestBomPriceCommon):
    """`_post_labour` charges each MO against its own company and location."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("mrp.group_mrp_routings")
        cls.component = cls._create_product(
            "Labour component", 50.0, category=cls.category_avco_auto
        )
        cls.expense_a, cls.expense_b, cls.expense_c = cls.env["account.account"].create(
            [
                {"code": "LAB100", "name": "Labour A", "account_type": "expense"},
                {"code": "LAB101", "name": "Labour B", "account_type": "expense"},
                {"code": "LAB102", "name": "Labour C", "account_type": "expense"},
            ]
        )

    @classmethod
    def _create_workcenter(cls, name, expense_account, costs_hour=60.0):
        return cls.env["mrp.workcenter"].create(
            {
                "name": name,
                "costs_hour": costs_hour,
                "expense_account_id": expense_account.id,
            }
        )

    @classmethod
    def _create_manufactured_product(cls, name, workcenters):
        product = cls._create_product(
            name, 0.0, quantity=0, category=cls.category_avco_auto
        )
        bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": f"op{index}",
                            "workcenter_id": workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 60,
                        }
                    )
                    for index, workcenter in enumerate(workcenters)
                ],
            }
        )
        return product, bom

    def _create_labour_mo(self, product, bom, duration=60):
        mo = self.env["mrp.production"].create(
            {"product_id": product.id, "bom_id": bom.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        mo.qty_producing = 1
        mo.workorder_ids.duration = duration
        mo.move_raw_ids.picked = True
        return mo

    def test_batch_spanning_two_production_locations(self):
        """One `_post_inventory` over MOs with different production locations.

        `_post_labour` read `self.product_id` and `self.company_id` inside its
        own `for mo in self` loop, so a batch of two products resolved to two
        production locations and the entry died on `Expected singleton`.
        """
        other_account = self.env["account.account"].create(
            {"code": "LAB200", "name": "Production 2", "account_type": "asset_current"}
        )
        other_location = self.env["stock.location"].create(
            {
                "name": "Production 2",
                "usage": "production",
                "location_id": self.warehouse.view_location_id.id,
                "valuation_account_id": other_account.id,
            }
        )
        first, first_bom = self._create_manufactured_product(
            "Batched A", self._create_workcenter("WC-A", self.expense_a)
        )
        second, second_bom = self._create_manufactured_product(
            "Batched B", self._create_workcenter("WC-B", self.expense_b)
        )
        second.product_tmpl_id.property_stock_production = other_location

        mo_first = self._create_labour_mo(first, first_bom)
        mo_second = self._create_labour_mo(second, second_bom)
        (mo_first | mo_second)._post_inventory()

        for mo, expense, production_account in (
            (mo_first, self.expense_a, self.account_production),
            (mo_second, self.expense_b, other_account),
        ):
            lines = mo.workorder_ids.time_ids.account_move_line_id.move_id.line_ids
            self.assertRecordValues(
                lines.sorted("id"),
                [
                    {"account_id": expense.id, "debit": 0.0, "credit": 60.0},
                    {"account_id": production_account.id, "debit": 60.0, "credit": 0.0},
                ],
            )

    def test_workcenter_charged_to_the_production_account(self):
        """A work centre may expense straight to the production account.

        Both sides were accumulated in one dict keyed by account, so the two
        amounts netted: the work centre's labour vanished from the entry and
        its time records were left with no `account_move_line_id`.
        """
        shared = self._create_workcenter("WC-shared", self.account_production)
        distinct = self._create_workcenter("WC-distinct", self.expense_a)
        product, bom = self._create_manufactured_product(
            "Shared account", distinct | shared
        )

        mo = self._create_labour_mo(product, bom)
        mo._post_inventory()

        self.assertFalse(
            mo.workorder_ids.filtered(lambda wo: not wo.time_ids.account_move_line_id),
            "every work order must be linked to the line carrying its labour",
        )
        lines = mo.workorder_ids.time_ids.account_move_line_id.move_id.line_ids
        self.assertRecordValues(
            lines.sorted("id"),
            [
                {"account_id": self.expense_a.id, "debit": 0.0, "credit": 60.0},
                {
                    "account_id": self.account_production.id,
                    "debit": 0.0,
                    "credit": 60.0,
                },
                {
                    "account_id": self.account_production.id,
                    "debit": 120.0,
                    "credit": 0.0,
                },
            ],
        )

    def test_labour_posted_equals_labour_capitalised(self):
        """Labour that does not divide into cents is rounded once, not per account.

        `_cal_price` capitalises the unrounded total while `_post_labour` posted
        the sum of the per-account roundings; the difference stayed in the
        production account for good. The order here has no byproduct on purpose:
        `_cal_price` rounds the finished and byproduct unit prices independently,
        so a cost share leaves a residual of its own that this method does not
        address.
        """
        workcenters = self.env["mrp.workcenter"].browse()
        for index, expense in enumerate(
            (self.expense_a, self.expense_b, self.expense_c)
        ):
            workcenters |= self._create_workcenter(f"WC-{index}", expense, 100.0)
        product, bom = self._create_manufactured_product("Unroundable", workcenters)

        mo = self._create_labour_mo(product, bom, duration=0.03)
        mo.workorder_ids.time_ids.write({"duration": 0.03})

        currency = self.company.currency_id
        per_account = sum(
            currency.round(workorder._get_cost()) for workorder in mo.workorder_ids
        )
        self.assertNotEqual(
            per_account,
            currency.round(mo.workorder_ids._get_cost()),
            "the scenario only bites while rounding each account on its own differs "
            "from rounding the order's labour once",
        )

        mo._post_inventory()

        movements = self.env["account.move.line"].search(
            [("account_id", "=", self.account_production.id)]
        )
        self.assertEqual(
            currency.round(
                sum(movements.mapped("debit")) - sum(movements.mapped("credit"))
            ),
            0.0,
            "labour posted must equal the labour capitalised into the finished move",
        )

    def test_byproduct_cost_share_still_clears(self):
        """The byproduct split must add back up to the order's total, too.

        `_cal_price` derived the finished and byproduct unit prices from the same
        total and rounded each on its own, so their values did not add back to
        `round(total_cost)` -- a cent per order on top of the labour one.
        """
        workcenters = self.env["mrp.workcenter"].browse()
        for index, expense in enumerate(
            (self.expense_a, self.expense_b, self.expense_c)
        ):
            workcenters |= self._create_workcenter(f"BP-{index}", expense, 100.0)
        product, bom = self._create_manufactured_product(
            "Byproduct residual", workcenters
        )
        self.component.standard_price = 100.03
        byproduct = self._create_product(
            "Residual byproduct", 0.0, quantity=0, category=self.category_avco_auto
        )
        self._add_byproduct(bom, byproduct, cost_share=33, quantity=3)

        mo = self._create_labour_mo(product, bom, duration=0.03)
        mo.workorder_ids.time_ids.write({"duration": 0.03})
        mo.move_byproduct_ids.quantity = 3
        mo.move_byproduct_ids.picked = True
        mo._post_inventory()

        self.assertEqual(
            self._production_account_balance(),
            0.0,
            "finished value + byproduct values must equal the order's total cost",
        )

    def _add_byproduct(self, bom, product, cost_share, quantity=1):
        bom.write(
            {
                "byproduct_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_qty": quantity,
                            "cost_share": cost_share,
                        }
                    )
                ]
            }
        )

    def _production_account_balance(self):
        movements = self.env["account.move.line"].search(
            [("account_id", "=", self.account_production.id)]
        )
        return self.company.currency_id.round(
            sum(movements.mapped("debit")) - sum(movements.mapped("credit"))
        )

    def test_byproduct_valued_at_standard_enters_at_its_own_price(self):
        """A standard-cost byproduct is a variance, not a value of zero.

        `_get_value_from_production` values a production move at
        ``quantity * price_unit``, so the byproduct `_cal_price` never priced
        entered stock at 0.00 while the finished move had already given up its
        share -- the whole share vanished into the production account.
        """
        workcenter = self._create_workcenter("BPStd", self.expense_a, 60.0)
        product, bom = self._create_manufactured_product("Std byproduct", workcenter)
        byproduct = self._create_product(
            "Standard byproduct", 7.0, quantity=0, category=self.category_standard_auto
        )
        self._add_byproduct(bom, byproduct, cost_share=20)

        mo = self._create_labour_mo(product, bom)
        mo.move_byproduct_ids.quantity = 1
        mo.move_byproduct_ids.picked = True
        mo._post_inventory()

        finished = mo.move_finished_ids.filtered(lambda m: m.product_id == product)
        # components 50 + labour 60 = 110; the byproduct's 20% (22.00) comes off
        # the finished move, and it enters stock at its standard 7.00.
        self.assertEqual(finished.value, 88.0)
        self.assertEqual(mo.move_byproduct_ids.value, 7.0)
        self.assertEqual(
            self._production_account_balance(),
            15.0,
            "22.00 of share against a 7.00 standard leaves a 15.00 variance",
        )

    def test_standard_finished_product_still_prices_its_byproducts(self):
        """The standard-cost branch returned before pricing anything else.

        The finished move took its standard price and every byproduct was left
        at 0.00, however much cost share it carried.
        """
        workcenter = self._create_workcenter("BPFin", self.expense_a, 60.0)
        product, bom = self._create_manufactured_product("Std finished", workcenter)
        product.categ_id = self.category_standard_auto
        product.standard_price = 90.0
        byproduct = self._create_product(
            "Shared byproduct", 0.0, quantity=0, category=self.category_avco_auto
        )
        self._add_byproduct(bom, byproduct, cost_share=20)

        mo = self._create_labour_mo(product, bom)
        mo.move_byproduct_ids.quantity = 1
        mo.move_byproduct_ids.picked = True
        mo._post_inventory()

        finished = mo.move_finished_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(finished.value, 90.0, "standard means standard")
        self.assertEqual(
            mo.move_byproduct_ids.value,
            22.0,
            "the byproduct takes its 20% of the 110.00 actually spent",
        )
        self.assertEqual(
            self._production_account_balance(),
            -2.0,
            "88.00 actually earned against a 90.00 standard is a 2.00 variance",
        )

    def test_byproduct_without_a_cost_share_stays_free(self):
        """A zero share means the byproduct costs nothing; it must not pick up a price."""
        workcenter = self._create_workcenter("BPFree", self.expense_a, 60.0)
        product, bom = self._create_manufactured_product("Free byproduct", workcenter)
        byproduct = self._create_product(
            "Free scrap", 7.0, quantity=0, category=self.category_standard_auto
        )
        self._add_byproduct(bom, byproduct, cost_share=0)

        mo = self._create_labour_mo(product, bom)
        mo.move_byproduct_ids.quantity = 1
        mo.move_byproduct_ids.picked = True
        mo._post_inventory()

        self.assertEqual(mo.move_byproduct_ids.value, 0.0)
        self.assertEqual(self._production_account_balance(), 0.0)


@tagged("post_install", "-at_install")
class TestKitPriceUnit(TestBomPriceCommon):
    """`_get_kit_price_unit` values a kit in the kit product's own UoM."""

    def _make_kit(self, name, bom_uom, component_qty):
        component = self._create_product(f"{name} component", 10.0)
        kit = self._create_product(name, 0.0, quantity=0)
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "type": "phantom",
                "product_qty": 1.0,
                "product_uom_id": bom_uom.id,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": component.id, "product_qty": component_qty}
                    )
                ],
            }
        )
        return kit, bom, component

    def _deliver(self, product, quantity):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": quantity,
                "product_uom_id": self.uom.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move._action_confirm()
        move.quantity = quantity
        move.picked = True
        move._action_done()
        return move

    def test_price_is_per_product_uom_whatever_the_bom_uom(self):
        """A BoM stated per dozen used to value the kit twelve times over."""
        for label, bom_uom, component_qty in (
            ("per unit", self.uom, 2),
            ("per dozen", self.dozen, 24),
        ):
            with self.subTest(bom=label):
                kit, bom, component = self._make_kit(
                    f"Kit {label}", bom_uom, component_qty
                )
                self.env["stock.quant"]._update_available_quantity(
                    component, self.stock_location, 100
                )
                moves = self._deliver(component, 6)
                self.assertEqual(moves._get_kit_price_unit(kit, bom, 3), 20.0)

    def test_price_does_not_depend_on_the_quantity_asked_for(self):
        """A unit price must be the same whatever quantity it is asked about.

        `_explode` rounds every component line UP, so exploding a fraction of a
        BoM batch inflated each component by a varying amount: a kit whose BoM
        is stated per dozen swung between 1.666667 and 1.7 across quantities of
        1 to 12.
        """
        kit, bom, component = self._make_kit("Kit per dozen", self.dozen, 24)
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 100
        )
        moves = self._deliver(component, 6)

        prices = {moves._get_kit_price_unit(kit, bom, qty) for qty in (1, 2, 3, 5, 12)}

        self.assertEqual(prices, {20.0})


@tagged("post_install", "-at_install")
class TestWipWizardDates(TestBomPriceCommon):
    """The WIP wizard reads the user's day, not UTC's."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("mrp.group_mrp_routings")
        cls.env.user.tz = "America/Mexico_City"
        cls.component = cls._create_product("WIP component", 50.0)
        cls.finished = cls._create_product("WIP finished", 0.0, quantity=0)
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
            }
        )

    def test_wizard_can_be_created_without_a_form(self):
        """`reversal_date` is required and stored, so it has to be precomputed."""
        wizard = self.env["mrp.account.wip.accounting"].create({})
        self.assertEqual(wizard.reversal_date, wizard.date + timedelta(days=1))

    def test_default_date_is_the_users_day(self):
        wizard = self.env["mrp.account.wip.accounting"].create({})
        self.assertEqual(wizard.date, fields.Date.context_today(self.env.user))

    def test_orders_from_two_companies_are_refused(self):
        """One entry means one journal and one set of company-dependent accounts."""
        other = self.env["res.company"].create({"name": "Other WIP company"})
        self.env.user.company_ids += other
        first = self.env["mrp.production"].create(
            {"product_id": self.finished.id, "bom_id": self.bom.id, "product_qty": 1.0}
        )
        second = first.copy()
        second.company_id = other

        wizard = self.env["mrp.account.wip.accounting"].create(
            {"mo_ids": [Command.set((first | second).ids)]}
        )

        with self.assertRaisesRegex(UserError, "one WIP entry per company"):
            wizard.confirm()

    def test_components_consumed_late_in_the_local_day_are_included(self):
        """The cut-off was a naive local date compared against UTC timestamps."""
        mo = self.env["mrp.production"].create(
            {"product_id": self.finished.id, "bom_id": self.bom.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        mo.qty_producing = 1
        mo.move_raw_ids.picked = True

        today = fields.Date.context_today(self.env.user)
        local_evening = datetime.combine(
            today, time(20, 0), tzinfo=ZoneInfo(self.env.user.tz)
        )
        mo.move_raw_ids.move_line_ids.date = local_evening.astimezone(UTC).replace(
            tzinfo=None
        )

        wizard = self.env["mrp.account.wip.accounting"].create(
            {"date": today, "mo_ids": [Command.set(mo.ids)]}
        )
        components = wizard.line_ids.filtered(
            lambda line: line.label == "WIP - Component Value"
        )
        self.assertEqual(components.credit, 50.0)


@tagged("post_install", "-at_install")
class TestAnalyticLineRename(TestBomPriceCommon):
    """Renaming an order carries its analytic lines with it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("mrp.group_mrp_routings") + cls.env.ref(
            "analytic.group_analytic_accounting"
        )
        plan = cls.env["account.analytic.plan"].create({"name": "Rename plan"})
        cls.analytic_account = cls.env["account.analytic.account"].create(
            {"name": "Rename account", "plan_id": plan.id}
        )
        cls.component = cls._create_product("Rename component", 50.0)
        cls.workcenter = cls.env["mrp.workcenter"].create(
            {
                "name": "Rename workcenter",
                "costs_hour": 60.0,
                "analytic_distribution": {str(cls.analytic_account.id): 100.0},
            }
        )
        cls.finished = cls._create_product("Rename finished", 0.0, quantity=0)
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
                "operation_ids": [
                    Command.create(
                        {
                            "name": "op",
                            "workcenter_id": cls.workcenter.id,
                            "time_mode": "manual",
                            "time_cycle_manual": 60,
                        }
                    )
                ],
            }
        )

    def test_rename_reaches_the_workcentre_analytic_lines(self):
        """`wc_analytic_account_line_ids` kept the old name; only the `mo_` half moved."""
        mo = self.env["mrp.production"].create(
            {"product_id": self.finished.id, "bom_id": self.bom.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        mo.workorder_ids.duration = 60
        lines = mo.workorder_ids.wc_analytic_account_line_ids
        self.assertTrue(
            lines, "the work centre distribution must produce analytic lines"
        )

        mo.write({"name": "RENAMED/MO/0001"})

        self.assertEqual(lines.mapped("ref"), ["RENAMED/MO/0001"] * len(lines))
        self.assertEqual(
            lines.mapped("name"),
            [f"[WC] {mo.workorder_ids.display_name}"] * len(lines),
        )

    def test_analytic_line_is_billed_at_the_rate_the_order_ran_at(self):
        """The analytic line and the journal entry must agree on the hourly rate.

        `button_finish` stamps the rate a work order actually ran at, and
        `_get_cost` bills that. The analytic entry read
        `workcenter_id.costs_hour` instead, so re-rating the work centre after
        the fact restated the analytic side and left the accounting side alone.
        """
        mo = self.env["mrp.production"].create(
            {"product_id": self.finished.id, "bom_id": self.bom.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        workorder = mo.workorder_ids
        workorder.duration = 60
        workorder.button_finish()
        self.assertEqual(workorder.costs_hour, 60.0, "the rate is stamped at finish")

        self.workcenter.costs_hour = 500.0
        workorder.time_ids.write({"duration": 60.0})
        workorder.invalidate_recordset()

        self.assertEqual(
            sum(workorder.wc_analytic_account_line_ids.mapped("amount")),
            -workorder._get_cost(),
        )

    def test_analytic_line_follows_the_estimated_cost_mode(self):
        """An order costed as estimated is billed its expected duration."""
        self.bom.operation_ids.cost_mode = "estimated"
        mo = self.env["mrp.production"].create(
            {"product_id": self.finished.id, "bom_id": self.bom.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        workorder = mo.workorder_ids
        workorder.duration = 123  # actual, deliberately unlike the expected
        workorder.button_finish()
        workorder.invalidate_recordset()

        self.assertTrue(workorder._should_estimate_cost())
        self.assertEqual(
            sum(workorder.wc_analytic_account_line_ids.mapped("amount")),
            -workorder._get_cost(),
        )
        self.assertEqual(
            workorder.wc_analytic_account_line_ids.unit_amount,
            workorder.duration_expected / 60.0,
        )

    def test_unrelated_write_leaves_analytic_lines_alone(self):
        mo = self.env["mrp.production"].create(
            {"product_id": self.finished.id, "bom_id": self.bom.id, "product_qty": 1.0}
        )
        mo.action_confirm()
        mo.workorder_ids.duration = 60
        lines = mo.workorder_ids.wc_analytic_account_line_ids
        before = (lines.mapped("ref"), lines.mapped("name"))

        mo.write({"priority": "1"})

        self.assertEqual((lines.mapped("ref"), lines.mapped("name")), before)
