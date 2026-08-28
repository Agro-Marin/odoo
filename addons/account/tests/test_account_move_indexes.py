import re

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountMoveIndexes(AccountTestInvoicingCommon):
    def _leading_index_columns(self, table):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", (table,)
        )
        leading = set()
        for (indexdef,) in self.env.cr.fetchall():
            match = re.search(r"USING \w+ \(\"?(\w+)", indexdef)
            if match:
                leading.add(match.group(1))
        return leading

    def test_commercial_partner_id_is_indexed(self):
        self.assertIn(
            "commercial_partner_id",
            self._leading_index_columns("account_move"),
            "res.partner.days_sales_outstanding groups account.move by"
            " commercial_partner_id and filters on it; without an index that"
            " read_group is a sequential scan of the whole table",
        )
