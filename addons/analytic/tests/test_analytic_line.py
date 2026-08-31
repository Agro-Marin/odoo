from unittest import SkipTest

from freezegun import freeze_time

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAnalyticLine(TransactionCase):
    def setUp(self):
        super().setUp()
        # `_search_from_last_fiscal_year` reaches `compute_fiscalyear_dates`, which
        # `account` adds to `res.company` (`account/models/res_company.py:1450`). This
        # module does not depend on `account`, so the hook is only exercisable when it
        # happens to be installed. `account.tests.common.ensure_installed` says exactly
        # this, but importing it from here would be the dependency we do not have.
        if self.env["ir.module.module"]._get("account").state != "installed":
            raise SkipTest("Module required for the test is not installed (account)")

    @freeze_time("2026-01-01 02:00:00")
    def test_from_last_fiscal_year_uses_the_user_local_date(self):
        """The window must open on the user's date, not the server's UTC date.

        At the frozen instant the server is already on 2026-01-01 while a user in
        `America/Mexico_City` (UTC-6) is still on 2025-12-31. The two dates sit in
        different fiscal years, so the window they select differs by a whole year --
        which is the entire six-hour-a-year window in which this can be observed.
        """
        lines = self.env["account.analytic.line"].with_context(tz="America/Mexico_City")

        (domain_leaf,) = lines._search_from_last_fiscal_year("=", True)
        field, operator, bound = domain_leaf

        self.assertEqual((field, operator), ("date", ">="))
        # The user's 2025-12-31 sits in the fiscal year opening 2025-01-01; one year
        # back is 2024-01-01. Reading the server's clock would say 2025-01-01.
        self.assertEqual(str(bound), "2024-01-01")
