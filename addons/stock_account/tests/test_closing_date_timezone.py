from datetime import date

from freezegun import freeze_time

from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestClosingDateTimezone(TestStockValuationCommon):
    """The valuation report's "Generate Entry" button sends no date when the
    user is closing *today* -- `controller.js` compares against the browser's
    own `DateTime.now()` and omits the argument -- so the server picks the day
    itself. Every user here is at UTC-6, where the last six hours of the
    working day already fall on the next UTC day.
    """

    # 01:00 UTC on the 1st is still 19:00 on the 30th in America/Mexico_City,
    # i.e. the evening a monthly closing is most likely to be generated.
    UTC_INSTANT = "2026-10-01 01:00:00"
    LOCAL_DAY = date(2026, 9, 30)

    def _company_in_local_tz(self):
        return self.company.with_context(tz="America/Mexico_City")

    def test_closing_entry_is_dated_on_the_user_day(self):
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)

        with freeze_time(self.UTC_INSTANT):
            closing = self._company_in_local_tz()._close_stock_valuation(auto_post=True)

        self.assertTrue(closing, "the fixture must produce a closing entry")
        self.assertEqual(
            closing.date,
            self.LOCAL_DAY,
            "the closing must land on the day the user is living, not the UTC day",
        )

    def test_explicit_date_still_wins(self):
        product = self.product_avco.with_company(self.company)
        self._make_in_move(product, 10, unit_cost=10)

        with freeze_time(self.UTC_INSTANT):
            closing = self._company_in_local_tz()._close_stock_valuation(
                at_date=date(2026, 9, 15), auto_post=True
            )

        self.assertEqual(
            closing.date,
            date(2026, 9, 15),
            "an explicit date is the user's own choice and must be untouched",
        )
