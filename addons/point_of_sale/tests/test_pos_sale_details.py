from datetime import timedelta

import odoo
from odoo import fields
from odoo.exceptions import UserError, ValidationError

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPosSaleDetails(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.report = self.env["report.point_of_sale.report_saledetails"]

    def _create_order(self, session, product, amount):
        return self.env["pos.order"].create(
            {
                "company_id": self.env.company.id,
                "session_id": session.id,
                "partner_id": self.partner_a.id,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "name": "OL/0001",
                            "product_id": product.id,
                            "price_unit": amount,
                            "discount": 0,
                            "qty": 1,
                            "tax_ids": [],
                            "price_subtotal": amount,
                            "price_subtotal_incl": amount,
                        },
                    )
                ],
                "pricelist_id": self.config.pricelist_id.id,
                "amount_paid": amount,
                "amount_total": amount,
                "amount_tax": 0.0,
                "amount_return": 0.0,
                "last_order_preparation_change": "{}",
                "to_invoice": False,
            }
        )

    def test_closing_difference_found_in_translated_database(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        product = self.create_product("Product A", self.categ_basic, 100)

        self.config.open_ui()
        session = self.config.current_session_id
        order = self._create_order(session, product, 100)
        self.make_payment(order, self.bank_split_pm1, 100)

        session.with_context(lang="fr_FR").action_pos_session_closing_control(
            bank_payment_method_diffs={self.bank_split_pm1.id: -20}
        )

        diff_move = self.env["account.move"].search(
            [("ref", "=like", "Différence de clôture%")]
        )
        self.assertTrue(
            diff_move,
            "the closing difference move should be referenced in French",
        )

        report = self.report.with_context(lang="fr_FR").get_sale_details(
            session_ids=[session.id]
        )
        row = next(
            p for p in report["payments"] if p.get("id") == self.bank_split_pm1.id
        )
        self.assertTrue(
            row["count"],
            "the report must locate the difference move in a French database",
        )
        self.assertEqual(row["money_difference"], -20)

    def test_cash_difference_line_excluded_not_oldest_move(self):
        cash_journal = self.cash_pm1.journal_id
        cash_journal.loss_account_id = self.company_data["default_account_expense"]
        cash_journal.profit_account_id = self.company_data["default_account_revenue"]
        self.config.cash_control = True
        product = self.create_product("Product A", self.categ_basic, 100)

        self.config.open_ui()
        session1 = self.config.current_session_id
        session1.set_opening_control(0, None)
        session1.try_cash_in_out("in", 200, "Float", False, {"translatedType": "in"})
        session1.update_closing_cash_details(200)
        session1.close_session_from_ui()

        self.config.open_ui()
        session2 = self.config.current_session_id
        session2.set_opening_control(200, None)
        order = self._create_order(session2, product, 100)
        self.make_payment(order, self.bank_pm1, 100)
        session2.try_cash_in_out(
            "out", 50, "Cash out", False, {"translatedType": "out"}
        )
        session2.update_closing_cash_details(142)
        session2.close_session_from_ui()

        report = self.report.get_sale_details(session_ids=[session2.id])
        cash_row = next(p for p in report["payments"] if not p.get("id"))
        amounts = [move["amount"] for move in cash_row["cash_moves"]]

        self.assertIn(-50, amounts, "the genuine cash out must be reported")
        self.assertNotIn(
            -8,
            amounts,
            "the counting difference must not be listed as a cash movement",
        )

    def test_open_session_included_in_date_window(self):
        product = self.create_product("Product A", self.categ_basic, 100)
        self.config.open_ui()
        session = self.config.current_session_id
        session.set_opening_control(0, None)
        order = self._create_order(session, product, 100)
        self.make_payment(order, self.bank_pm1, 100)

        now = fields.Datetime.now()
        report = self.report.get_sale_details(
            date_start=fields.Datetime.to_string(now - timedelta(hours=1)),
            date_stop=fields.Datetime.to_string(now + timedelta(hours=1)),
            config_ids=self.config.ids,
        )
        self.assertEqual(
            report["session_name"],
            session.name,
            "an open session (stop_at NULL) must not be filtered out",
        )

    def test_straddling_session_included_in_date_window(self):
        product = self.create_product("Product A", self.categ_basic, 100)
        self.config.open_ui()
        session = self.config.current_session_id
        session.set_opening_control(0, None)
        order = self._create_order(session, product, 100)
        self.make_payment(order, self.bank_pm1, 100)
        session.action_pos_session_closing_control()

        now = fields.Datetime.now()
        window_start = now - timedelta(hours=1)
        session.sudo().start_at = window_start - timedelta(hours=10)

        report = self.report.get_sale_details(
            date_start=fields.Datetime.to_string(window_start),
            date_stop=fields.Datetime.to_string(now + timedelta(hours=1)),
            config_ids=self.config.ids,
        )
        self.assertEqual(
            report["session_name"],
            session.name,
            "a session straddling the window start must not be filtered out",
        )


@odoo.tests.tagged("post_install", "-at_install")
class TestPosCategoryGuards(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def test_check_hour_rejects_window_that_never_opens(self):
        category = self.env["pos.category"].create({"name": "Snacks"})

        with self.assertRaises(ValidationError):
            category.write({"hour_after": 10.0, "hour_until": 0.0})

        with self.assertRaises(ValidationError):
            self.env["pos.category"].create(
                {"name": "Drinks", "hour_after": 10.0, "hour_until": 0.0}
            )

        with self.assertRaises(ValidationError):
            category.write({"hour_until": 25.0})

        category.write({"hour_after": 0.0, "hour_until": 24.0})
        self.assertEqual(category.hour_until, 24.0)

    def test_unlink_ignores_session_that_cannot_show_the_category(self):
        category = self.env["pos.category"].create({"name": "Snacks"})
        other_category = self.env["pos.category"].create({"name": "Drinks"})
        self.config.write(
            {
                "limit_categories": True,
                "iface_available_categ_ids": [(6, 0, other_category.ids)],
            }
        )
        self.config.open_ui()

        category.unlink()
        self.assertFalse(category.exists())

    def test_unlink_blocked_by_session_that_shows_the_category(self):
        category = self.env["pos.category"].create({"name": "Snacks"})
        self.config.write(
            {
                "limit_categories": True,
                "iface_available_categ_ids": [(6, 0, category.ids)],
            }
        )
        self.config.open_ui()
        session = self.config.current_session_id

        with self.assertRaisesRegex(UserError, session.name):
            category.unlink()

    def test_unlink_ignores_session_of_another_company(self):
        category = self.env["pos.category"].create({"name": "Snacks"})
        self.config.open_ui()
        other_company = self.setup_other_company()["company"]

        category.with_context(allowed_company_ids=other_company.ids).unlink()
        self.assertFalse(category.exists())


@odoo.tests.tagged("post_install", "-at_install")
class TestPosSaleDetailsCoherence(TestPoSCommon):
    """One report, one set of numbers.

    Every figure the report prints for a block must be derivable from the other
    figures in that block: a tax total is the total of the tax rows above it, a
    refund block reads in one direction, and a scope either covers a session or
    says it does not.
    """

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.report = self.env["report.point_of_sale.report_saledetails"]

    def _order(self, session, product, price, qty=1, taxes=None):
        return self.env["pos.order"].create(
            {
                "company_id": self.env.company.id,
                "session_id": session.id,
                "partner_id": self.partner_a.id,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "name": "OL/0001",
                            "product_id": product.id,
                            "price_unit": price,
                            "discount": 0,
                            "qty": qty,
                            "tax_ids": [(6, 0, taxes or [])],
                            "price_subtotal": price * qty,
                            "price_subtotal_incl": price * qty,
                        },
                    )
                ],
                "pricelist_id": self.config.pricelist_id.id,
                "amount_paid": price * qty,
                "amount_total": price * qty,
                "amount_tax": 0.0,
                "amount_return": 0.0,
                "last_order_preparation_change": "{}",
                "to_invoice": False,
            }
        )

    def _open_session(self):
        self.config.open_ui()
        session = self.config.current_session_id
        session.set_opening_control(0, None)
        return session

    def test_every_base_in_the_report_is_computed_from_the_line(self):
        """A base the report reads off ``price_subtotal`` while computing the
        base beside it from ``compute_all`` can disagree with itself, and the
        page gives the reader no way to tell which half is right."""
        tax = self.env["account.tax"].create({"name": "Coherence 10%", "amount": 10})
        product = self.create_product("Taxed", self.categ_basic, 100, tax_ids=tax.ids)
        session = self._open_session()
        order = self._order(session, product, 100, taxes=tax.ids)
        self.make_payment(order, self.bank_pm1, order.amount_total)
        order.lines.sudo().price_subtotal = 1.0

        report = self.report.get_sale_details(session_ids=[session.id])
        self.assertEqual(
            report["taxes"],
            [{"name": tax.name, "tax_amount": 10.0, "base_amount": 100.0}],
        )
        self.assertEqual(
            report["taxes_info"],
            {"tax_amount": 10.0, "base_amount": 100.0},
            "the tax total must be computed the way the tax rows above it are",
        )
        self.assertEqual(
            report["products_info"]["total"],
            report["taxes_info"]["base_amount"],
            "the products block and the tax block report one untaxed total",
        )

    def test_refund_block_reads_in_one_direction(self):
        tax = self.env["account.tax"].create({"name": "Refund 10%", "amount": 10})
        product = self.create_product(
            "Returned", self.categ_basic, 100, tax_ids=tax.ids
        )
        session = self._open_session()
        order = self._order(session, product, 100, taxes=tax.ids)
        self.make_payment(order, self.bank_pm1, 110)
        refund = order._refund()
        self.make_payment(refund, self.bank_pm1, -110)

        report = self.report.get_sale_details(session_ids=[session.id])
        rows = [
            row
            for category in report["refund_products"]
            for row in category["products"]
        ]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["quantity"], 1.0)
        self.assertEqual(row["total_paid"], 100.0)
        self.assertEqual(row["base_amount"], 100.0)
        self.assertEqual(report["refund_info"]["total"], 100.0)
        self.assertEqual(report["refund_taxes_info"]["base_amount"], 100.0)
        self.assertEqual(report["refund_taxes_info"]["tax_amount"], 10.0)
        self.assertEqual(
            report["refund_taxes_info"]["base_amount"],
            sum(r["base_amount"] for r in report["refund_taxes"]),
        )

    def test_scope_without_config_or_session_covers_the_window(self):
        product = self.create_product("Scoped", self.categ_basic, 100)
        session = self._open_session()
        order = self._order(session, product, 100)
        self.make_payment(order, self.cash_pm1, 100)

        report = self.report.get_sale_details()
        self.assertEqual(report["nbr_orders"], 1)
        self.assertIn(
            self.config.name,
            report["config_names"],
            "a report that found the order must name the config that took it",
        )
        self.assertTrue(
            all(payment["count"] for payment in report["payments"]),
            "an in-scope session's payments must be counted, not left unclosed",
        )
        self.assertEqual(report["total_paid"], 100.0)

    def test_config_is_named_once_per_config_not_once_per_session(self):
        product = self.create_product("Repeated", self.categ_basic, 100)
        session_ids = []
        for _index in range(3):
            session = self._open_session()
            order = self._order(session, product, 100)
            self.make_payment(order, self.cash_pm1, 100)
            session.update_closing_cash_details(100)
            session.close_session_from_ui()
            session_ids.append(session.id)

        report = self.report.get_sale_details(session_ids=session_ids)
        self.assertEqual(report["config_names"], [self.config.name])

    def test_total_paid_covers_the_same_window_as_the_orders(self):
        product = self.create_product("Windowed", self.categ_basic, 100)
        session = self._open_session()
        inside = self._order(session, product, 100)
        self.make_payment(inside, self.cash_pm1, 100)
        outside = self._order(session, product, 250)
        self.make_payment(outside, self.bank_pm1, 250)
        outside.sudo().date_order = fields.Datetime.now() - timedelta(days=5)

        now = fields.Datetime.now()
        report = self.report.get_sale_details(
            fields.Datetime.to_string(now - timedelta(hours=1)),
            fields.Datetime.to_string(now + timedelta(hours=1)),
            self.config.ids,
        )
        self.assertEqual(report["nbr_orders"], 1)
        self.assertEqual(
            report["total_paid"],
            report["currency"]["total_paid"],
            "payments and order totals must be read over the same window",
        )

    def test_combo_label_does_not_travel_to_a_plain_line(self):
        combo_part = self.create_product("Side", self.categ_basic, 0)
        product = self.create_product("Meal", self.categ_basic, 100)
        session = self._open_session()
        plain = self._order(session, product, 100)
        self.make_payment(plain, self.cash_pm1, 100)
        with_combo = self._order(session, product, 100)
        self.env["pos.order.line"].create(
            {
                "order_id": with_combo.id,
                "product_id": combo_part.id,
                "qty": 1,
                "price_unit": 0,
                "price_subtotal": 0,
                "price_subtotal_incl": 0,
                "name": "combo child",
                "combo_parent_id": with_combo.lines[0].id,
            }
        )
        self.make_payment(with_combo, self.cash_pm1, 100)

        report = self.report.get_sale_details(session_ids=[session.id])
        rows = [
            row
            for category in report["products"]
            for row in category["products"]
            if row["product_name"] == "Meal"
        ]
        labelled = [row for row in rows if row["combo_products_label"]]
        self.assertEqual(
            [row["quantity"] for row in labelled],
            [1.0],
            "only the unit actually sold as a combo may carry the combo label",
        )
        self.assertEqual(sum(row["quantity"] for row in rows), 2.0)

    def test_extra_arguments_do_not_break_the_advertised_signature(self):
        """``get_sale_details`` declares ``**kwargs``; a caller that supplies one
        must not hit ``_get_domain() got an unexpected keyword argument``."""
        product = self.create_product("Extra", self.categ_basic, 100)
        session = self._open_session()
        order = self._order(session, product, 100)
        self.make_payment(order, self.cash_pm1, 100)

        report = self.report.get_sale_details(
            session_ids=[session.id], employee_id=False
        )
        self.assertEqual(report["nbr_orders"], 1)

    def test_window_covers_the_last_second_of_the_day(self):
        date_start, date_stop = self.report._get_date_start_and_date_stop(False, False)
        self.assertEqual(
            date_stop - date_start,
            timedelta(days=1, microseconds=-1),
            "an order timed at 23:59:59.5 belongs to the day it was taken",
        )

    def test_unrelated_move_with_a_matching_ref_is_not_a_difference(self):
        product = self.create_product("Unrelated", self.categ_basic, 100)
        session = self._open_session()
        order = self._order(session, product, 100)
        self.make_payment(order, self.bank_pm1, 100)
        session.action_pos_session_closing_control()

        ref = session._get_diff_account_move_ref(self.bank_pm1)
        self.env["account.move"].search([("ref", "=", ref)]).unlink()
        self.env["account.move"].create(
            {
                "move_type": "entry",
                "ref": ref,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "account_id": self.company_data[
                                "default_account_receivable"
                            ].id,
                            "debit": 40.0,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "account_id": self.company_data[
                                "default_account_payable"
                            ].id,
                            "credit": 40.0,
                        },
                    ),
                ],
            }
        )

        report = self.report.get_sale_details(session_ids=[session.id])
        row = next(p for p in report["payments"] if p.get("id") == self.bank_pm1.id)
        self.assertEqual(row["final_count"], 100.0)
        self.assertEqual(
            row["money_counted"],
            100.0,
            "what was counted is what settled the payments, not the total of a "
            "journal entry that merely shares the closing-difference reference",
        )
        self.assertEqual(row["money_difference"], 0.0)

    def test_a_deduction_line_is_subtracted_not_added(self):
        """A negative line on an ordinary order is a deduction, not a refund. Its
        sign comes from ``order.is_refund`` — the convention
        ``_compute_amount_line_all`` uses — never from the line's own qty, or two
        units sold and one deducted read as three units and three units' money."""
        tax = self.env["account.tax"].create({"name": "Deduction 10%", "amount": 10})
        product = self.create_product(
            "Deducted", self.categ_basic, 100, tax_ids=tax.ids
        )
        session = self._open_session()
        sold = self._order(session, product, 100, qty=2, taxes=tax.ids)
        self.make_payment(sold, self.cash_pm1, sold.amount_total)
        deduction = self._order(session, product, 100, qty=-1, taxes=tax.ids)
        self.assertFalse(deduction.is_refund)
        self.make_payment(deduction, self.cash_pm1, deduction.amount_total)

        report = self.report.get_sale_details(session_ids=[session.id])
        self.assertFalse(report["refund_products"], "a deduction is not a refund")
        rows = [row for c in report["products"] for row in c["products"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantity"], 1.0)
        self.assertEqual(rows[0]["total_paid"], 100.0)
        self.assertEqual(rows[0]["base_amount"], 100.0)
        self.assertEqual(report["products_info"], {"total": 100.0, "qty": 1.0})
        self.assertEqual(
            report["taxes_info"], {"tax_amount": 10.0, "base_amount": 100.0}
        )

    def test_a_started_session_without_sales_is_still_in_scope(self):
        """The window scope is every session that was open in it, not only the
        ones that took an order: a session with no sales still has a drawer."""
        product = self.create_product("Elsewhere", self.categ_basic, 100)
        quiet_config = self.env["pos.config"].create({"name": "Quiet Shop"})
        quiet_config.open_ui()
        quiet_config.current_session_id.set_opening_control(0, None)
        session = self._open_session()
        order = self._order(session, product, 100)
        self.make_payment(order, self.cash_pm1, 100)

        report = self.report.get_sale_details()
        self.assertEqual(report["nbr_orders"], 1)
        self.assertIn("Quiet Shop", report["config_names"])
        self.assertIn(
            quiet_config.current_session_id.id,
            [payment["session"] for payment in report["payments"]],
            "the quiet session must get its uncounted cash row",
        )
