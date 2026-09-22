from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestHorizontalGroupLedger(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ledger_group = cls.env.ref(
            "account.horizontal_group_ledger", raise_if_not_found=False
        )
        cls.balance_sheet = cls.env.ref("account.balance_sheet")

    def _available_ids(self, report):
        options = report.get_options({})
        return [group["id"] for group in options["available_horizontal_groups"]]

    def test_a_ledger_horizontal_group_is_shipped(self):
        """The engine ships complete but empty.

        The only thing that ever creates a horizontal group here is a tax unit,
        an EU construct we have none of, so the filter never renders. This
        record is what makes the feature reachable at all.
        """
        self.assertTrue(self.ledger_group, "account.horizontal_group_ledger must exist")
        self.assertEqual(
            self.ledger_group.rule_ids.mapped("field_name"),
            ["journal_group_id"],
            "it splits the columns by ledger",
        )

    def test_it_is_attached_to_the_three_financial_statements(self):
        for xmlid in (
            "account.balance_sheet",
            "account.profit_and_loss",
            "account.cash_flow_report",
        ):
            with self.subTest(report=xmlid):
                self.assertIn(
                    self.ledger_group,
                    self.env.ref(xmlid).horizontal_group_ids,
                )

    def test_it_is_not_offered_when_no_ledger_exists(self):
        """Offered with nothing to split by, it promises a breakdown that
        renders as a single column."""
        self.env["account.journal.group"].search([]).unlink()

        self.assertNotIn(
            self.ledger_group.id,
            self._available_ids(self.balance_sheet),
            "one company and no journal group: the filter says nothing",
        )

    def test_it_is_offered_once_a_ledger_exists(self):
        self.env["account.journal.group"].search([]).unlink()
        self.env["account.journal.group"].create(
            {
                "name": "Operations ledger",
                "company_id": self.env.company.id,
            }
        )

        self.assertIn(
            self.ledger_group.id,
            self._available_ids(self.balance_sheet),
            "with journals grouped into a ledger the split is meaningful",
        )
