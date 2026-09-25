from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinUnmergeBranches(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.company_data["company"]
        cls.company_data_b = cls.setup_other_company(name="unmerge_company_b")
        cls.company_b = cls.company_data_b["company"]
        cls.country = cls.company_a.tax_config_id.account_fiscal_country_id
        cls.company_b.tax_config_id.account_fiscal_country_id = cls.country
        cls.company_a.write(
            {"child_ids": [Command.create({"name": "unmerge_branch_a1"})]}
        )
        cls.company_b.write(
            {"child_ids": [Command.create({"name": "unmerge_branch_b1"})]}
        )
        cls.cr.precommit.run()
        cls.branch_a1 = cls.company_a.child_ids.filtered(
            lambda company: company.name == "unmerge_branch_a1"
        )
        cls.branch_b1 = cls.company_b.child_ids
        cls.env.user.company_ids |= cls.branch_a1 | cls.branch_b1
        cls.all_companies = (
            cls.company_a + cls.branch_a1 + cls.company_b + cls.branch_b1
        )
        cls.env = cls.env(
            context=dict(cls.env.context, allowed_company_ids=cls.all_companies.ids)
        )

    def _shared_account(self):
        account = self.env["account.account"].create(
            {
                "code": "121990",
                "name": "Unmerge shared receivable",
                "account_type": "asset_receivable",
                "reconcile": True,
                "company_ids": [Command.set(self.company_a.ids)],
            }
        )
        account.write(
            {
                "company_ids": [Command.link(self.company_b.id)],
                "code_mapping_ids": [
                    Command.create({"company_id": self.company_b.id, "code": "121991"})
                ],
            }
        )
        return account

    def _shared_tax(self):
        return self.env["account.tax"].create(
            {
                "name": "Unmerge VAT 16%",
                "type_tax_use": "sale",
                "amount_type": "percent",
                "amount": 16.0,
                "country_id": self.country.id,
                "company_ids": [Command.set((self.company_a + self.company_b).ids)],
            }
        )

    def _root_data(self, company):
        return (
            self.company_data
            if company.root_id == self.company_a
            else self.company_data_b
        )

    def _entry_line(self, company, account):
        data = self._root_data(company)
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "company_id": company.id,
                "journal_id": data["default_journal_misc"].id,
                "date": "2026-01-15",
                "line_ids": [
                    Command.create({"account_id": account.id, "balance": 10.0}),
                    Command.create(
                        {
                            "account_id": data["default_account_expense"].id,
                            "balance": -10.0,
                        }
                    ),
                ],
            }
        )
        move.action_post()
        self.assertEqual(move.company_id, company)
        return move.line_ids.filtered(lambda line: line.account_id == account)

    def _invoice(self, company, tax):
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": company.id,
                "journal_id": self._root_data(company)["default_journal_sale"].id,
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-15",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "price_unit": 100.0,
                            "tax_ids": [Command.set(tax.ids)],
                        }
                    )
                ],
            }
        )
        move.action_post()
        self.assertEqual(move.company_id, company)
        return move

    def _add_xmlids(self, record, suffix):
        self.env["ir.model.data"].create(
            [
                {
                    "module": "account",
                    "name": f"{company.id}_{suffix}",
                    "model": record._name,
                    "res_id": record.id,
                }
                for company in self.all_companies
            ]
            + [
                {
                    "module": "account",
                    "name": f"shared_{self.company_b.id}_{suffix}",
                    "model": record._name,
                    "res_id": record.id,
                }
            ]
        )

    def _assert_xmlids(self, suffix, expected_by_company, original):
        for company, expected in expected_by_company.items():
            self.assertEqual(
                self.env.ref(f"account.{company.id}_{suffix}"),
                expected,
                f"the xmlid of {company.name} follows its company's record",
            )
        self.assertEqual(
            self.env.ref(f"account.shared_{self.company_b.id}_{suffix}"),
            original,
            "an xmlid without a leading company id is not a company xmlid",
        )

    def _code_store(self, account):
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT code_store FROM account_account WHERE id = %s", [account.id]
        )
        return self.env.cr.fetchone()[0] or {}

    def _unmerge(self, record, base_company):
        record.with_company(base_company).with_context(
            account_unmerge_confirm=True
        ).action_unmerge()
        self.env.invalidate_all()
        split = (
            self.env[record._name]
            .with_context(active_test=False)
            .search(
                [
                    ("name", "=", record.name),
                    ("id", "!=", record.id),
                ]
            )
        )
        self.assertEqual(len(split), 1)
        return split

    def _assert_account_split(self, base_company):
        account = self._shared_account()
        lines = {
            company: self._entry_line(company, account)
            for company in self.all_companies
        }
        for company in (self.branch_a1, self.branch_b1):
            self.partner_a.with_company(
                company
            ).property_account_receivable_id = account
        account.with_company(self.branch_a1).sudo().code_store = "121993"
        account.with_company(self.branch_b1).sudo().code_store = "121992"
        self._add_xmlids(account, "unmerge_branch_account")

        split = self._unmerge(account, base_company)

        other_root = self.company_a + self.company_b - base_company
        expected_by_company = {
            company: split if company.root_id == other_root else account
            for company in self.all_companies
        }
        for company, line in lines.items():
            self.assertEqual(
                line.account_id,
                expected_by_company[company],
                f"the journal item of {company.name} follows its company's account",
            )
        for company in (self.branch_a1, self.branch_b1):
            self.assertEqual(
                self.partner_a.with_company(company).property_account_receivable_id,
                expected_by_company[company],
                f"the receivable property of {company.name} follows the split",
            )
        codes_by_root = {
            self.company_a: {self.company_a: "121990", self.branch_a1: "121993"},
            self.company_b: {self.company_b: "121991", self.branch_b1: "121992"},
        }
        for record, root in ((account, base_company), (split, other_root)):
            self.assertEqual(
                self._code_store(record),
                {
                    str(company.id): code
                    for company, code in codes_by_root[root].items()
                },
                "every company-dependent value keyed by a company of the subtree "
                "moves together, branches included",
            )
        self.assertEqual(account.company_ids, base_company)
        self.assertEqual(split.company_ids, other_root)
        self._assert_xmlids("unmerge_branch_account", expected_by_company, account)

    def test_account_unmerge_follows_branches(self):
        self._assert_account_split(self.company_a)

    def test_account_unmerge_from_the_other_root_keeps_its_subtree(self):
        self._assert_account_split(self.company_b)

    def test_tax_unmerge_follows_branches(self):
        tax = self._shared_tax()
        moves = {company: self._invoice(company, tax) for company in self.all_companies}
        self._add_xmlids(tax, "unmerge_branch_tax")

        split = self._unmerge(tax, self.company_a)

        expected_by_company = {
            company: split if company.root_id == self.company_b else tax
            for company in self.all_companies
        }
        for company, move in moves.items():
            expected = expected_by_company[company]
            base_line = move.invoice_line_ids
            tax_line = move.line_ids.filtered("tax_repartition_line_id")
            self.assertEqual(
                base_line.tax_ids,
                expected,
                f"the base line of {company.name} follows its company's tax",
            )
            self.assertEqual(tax_line.tax_line_id, expected)
            self.assertIn(
                tax_line.tax_repartition_line_id,
                expected.repartition_line_ids,
                f"the tax line of {company.name} keeps a repartition line of "
                "the tax it carries",
            )
        self.assertEqual(tax.company_ids, self.company_a)
        self.assertEqual(split.company_ids, self.company_b)
        self._assert_xmlids("unmerge_branch_tax", expected_by_company, tax)
