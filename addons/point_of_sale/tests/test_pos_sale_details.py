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
        session1.post_closing_cash_details(200)
        session1.close_session_from_ui()

        self.config.open_ui()
        session2 = self.config.current_session_id
        session2.set_opening_control(200, None)
        order = self._create_order(session2, product, 100)
        self.make_payment(order, self.bank_pm1, 100)
        session2.try_cash_in_out(
            "out", 50, "Cash out", False, {"translatedType": "out"}
        )
        session2.post_closing_cash_details(142)
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
