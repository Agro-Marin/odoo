from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosLockDates(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.session = self._start_pos_session(self.cash_pm1, 0)
        self.session.start_at = fields.Datetime.now() - timedelta(days=5)
        self.lock_date = fields.Date.today() - timedelta(days=2)

    def test_fiscal_lock_over_open_session_raises(self):
        with self.assertRaisesRegex(ValidationError, self.session.name):
            self.company.account_config_id.fiscalyear_lock_date = self.lock_date

    def test_tax_lock_through_company_write_raises(self):
        with self.assertRaisesRegex(ValidationError, self.session.name):
            self.company.write({"tax_lock_date": self.lock_date})

    def test_sale_lock_ignores_session_on_general_journal(self):
        self.assertEqual(self.config.journal_id.type, "general")
        self.company.account_config_id.sale_lock_date = self.lock_date
        self.assertEqual(self.company.account_config_id.sale_lock_date, self.lock_date)

    def test_sale_lock_over_open_sale_journal_session_raises(self):
        self.config.journal_id.type = "sale"
        with self.assertRaisesRegex(ValidationError, self.session.name):
            self.company.account_config_id.sale_lock_date = self.lock_date

    def test_lock_before_session_start_is_allowed(self):
        earlier = self.session.start_at.date() - timedelta(days=1)
        self.company.account_config_id.fiscalyear_lock_date = earlier
        self.assertEqual(self.company.account_config_id.fiscalyear_lock_date, earlier)

    def test_lock_over_closed_session_is_allowed(self):
        self.session.action_pos_session_close()
        self.assertEqual(self.session.state, "closed")
        self.company.account_config_id.fiscalyear_lock_date = self.lock_date
        self.assertEqual(
            self.company.account_config_id.fiscalyear_lock_date, self.lock_date
        )
