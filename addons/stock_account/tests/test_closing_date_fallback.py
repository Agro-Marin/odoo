from odoo import fields
from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestClosingDateLegacyFallback(TestStockValuationCommon):
    def _state_tracking(self, closing):
        am_state_field = (
            self.env["ir.model.fields"]
            .sudo()
            .search([("model", "=", "account.move"), ("name", "=", "state")], limit=1)
        )
        return closing.message_ids.tracking_value_ids.filtered(
            lambda t: t.field_id == am_state_field
        ).sorted("id")

    def _simulate_state_change_tracking(self, closing):
        am_state_field = (
            self.env["ir.model.fields"]
            .sudo()
            .search([("model", "=", "account.move"), ("name", "=", "state")], limit=1)
        )
        message = closing.sudo().message_post(
            body="Status changed", subtype_xmlid="mail.mt_note"
        )
        self.env["mail.tracking.value"].sudo().create(
            {
                "mail_message_id": message.id,
                "field_id": am_state_field.id,
                "old_value_char": "draft",
                "new_value_char": "posted",
            }
        )

    def test_null_cutoff_falls_back_to_tracked_state_change_date(self):
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)
        closing = self.company._close_stock_valuation(auto_post=True)
        closing.stock_valuation_closing_cutoff = False
        self._simulate_state_change_tracking(closing)
        tracking = self._state_tracking(closing)
        self.assertTrue(tracking, "posting a move should record a state change")
        expected = tracking[-1].create_date
        self.assertEqual(
            expected.date(),
            closing.date,
            "the state-change tracking must land the same day as the closing "
            "for this test to actually exercise the tracked-date branch",
        )
        self.assertEqual(self.company._get_last_closing_date(), expected)

    def test_null_cutoff_without_tracking_falls_back_to_closing_date(self):
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)
        closing = self.company._close_stock_valuation(auto_post=True)
        closing.stock_valuation_closing_cutoff = False
        self._simulate_state_change_tracking(closing)
        self._state_tracking(closing).unlink()
        self.assertEqual(
            self.company._get_last_closing_date(),
            fields.Datetime.to_datetime(closing.date),
        )
