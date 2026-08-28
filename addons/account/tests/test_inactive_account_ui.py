from lxml import etree

from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

# Every account field a user can still see configured after the account was
# archived, with the boolean that mirrors `active` so the view can mute it.
ACTIVE_MIRRORS = {
    "account.journal": [
        ("default_account_id", "default_account_active"),
        ("suspense_account_id", "suspense_account_active"),
        ("non_deductible_account_id", "non_deductible_account_active"),
        ("profit_account_id", "profit_account_active"),
        ("loss_account_id", "loss_account_active"),
    ],
    "account.tax.repartition.line": [
        ("account_id", "account_active"),
    ],
    "res.partner": [
        ("property_account_receivable_id", "property_account_receivable_active"),
        ("property_account_payable_id", "property_account_payable_active"),
    ],
    "product.template": [
        ("property_account_income_id", "property_account_income_active"),
        ("property_account_expense_id", "property_account_expense_active"),
    ],
    "res.config.settings": [
        (
            "income_currency_exchange_account_id",
            "income_currency_exchange_account_active",
        ),
        (
            "expense_currency_exchange_account_id",
            "expense_currency_exchange_account_active",
        ),
        (
            "account_journal_suspense_account_id",
            "account_journal_suspense_account_active",
        ),
        ("transfer_account_id", "transfer_account_active"),
        (
            "account_cash_basis_base_account_id",
            "account_cash_basis_base_account_active",
        ),
        (
            "account_journal_early_pay_discount_loss_account_id",
            "account_journal_early_pay_discount_loss_account_active",
        ),
        (
            "account_journal_early_pay_discount_gain_account_id",
            "account_journal_early_pay_discount_gain_account_active",
        ),
        (
            "account_discount_income_allocation_id",
            "account_discount_income_allocation_active",
        ),
        (
            "account_discount_expense_allocation_id",
            "account_discount_expense_allocation_active",
        ),
        ("income_account_id", "income_account_active"),
        ("expense_account_id", "expense_account_active"),
    ],
}

# The view sites that must mute an archived account, per view xml_id.
MUTED_IN_VIEW = {
    "account.view_account_journal_tree": [
        ("default_account_id", "default_account_active"),
    ],
    "account.view_account_journal_form": [
        ("default_account_id", "default_account_active"),
        ("suspense_account_id", "suspense_account_active"),
        ("non_deductible_account_id", "non_deductible_account_active"),
        ("profit_account_id", "profit_account_active"),
        ("loss_account_id", "loss_account_active"),
    ],
    "account.view_tax_form": [
        ("account_id", "account_active"),
    ],
    "account.view_partner_property_form": [
        ("property_account_receivable_id", "property_account_receivable_active"),
        ("property_account_payable_id", "property_account_payable_active"),
    ],
    "account.product_template_form_view": [
        ("property_account_income_id", "property_account_income_active"),
        ("property_account_expense_id", "property_account_expense_active"),
    ],
}


@tagged("post_install", "-at_install")
class TestInactiveAccountUi(AccountTestInvoicingCommon):
    def test_every_account_field_mirrors_the_active_flag_of_its_account(self):
        for model_name, pairs in ACTIVE_MIRRORS.items():
            model = self.env[model_name]
            for account_fname, active_fname in pairs:
                with self.subTest(model=model_name, field=account_fname):
                    self.assertIn(active_fname, model._fields)
                    field = model._fields[active_fname]
                    self.assertEqual(field.type, "boolean")
                    self.assertEqual(
                        field.related,
                        f"{account_fname}.active",
                    )

    def test_a_journal_shows_its_default_account_as_archived(self):
        journal = self.company_data["default_journal_bank"]
        self.assertTrue(journal.default_account_id)
        self.assertTrue(journal.default_account_active)

        journal.default_account_id.action_archive()
        self.assertFalse(journal.default_account_active)

    def test_an_archived_account_is_muted_where_it_stays_configured(self):
        # Most of these fields sit behind a group; without it they never reach
        # the arch and the assertions below would pass on an empty view.
        self.env.user.group_ids = [
            Command.link(self.env.ref("account.group_account_readonly").id),
            Command.link(self.env.ref("account.group_account_user").id),
        ]
        for xml_id, pairs in MUTED_IN_VIEW.items():
            view = self.env.ref(xml_id)
            arch = etree.fromstring(
                self.env[view.model].get_view(view_id=view.id, view_type=view.type)[
                    "arch"
                ]
            )
            for account_fname, active_fname in pairs:
                with self.subTest(view=xml_id, field=account_fname):
                    nodes = [
                        node
                        for node in arch.findall(f".//field[@name='{account_fname}']")
                        # Odoo injects invisible copies of any field a domain
                        # mentions; those are technical and carry no decoration.
                        if node.get("data-used-by") is None
                    ]
                    self.assertTrue(nodes, "the field left the view")
                    for node in nodes:
                        self.assertEqual(
                            node.get("decoration-muted"),
                            f"not {active_fname}",
                        )
