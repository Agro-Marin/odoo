from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestTaxesCountryConstraint(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.foreign_country = cls.env.ref("base.de")
        foreign_tax_group = cls.env["account.tax.group"].create(
            {
                "name": "Foreign tax group",
                "country_id": cls.foreign_country.id,
                "company_id": cls.company_data["company"].id,
            }
        )
        cls.foreign_tax = cls.company_data["default_tax_sale"].copy(
            {
                "name": "Foreign 19%",
                "country_id": cls.foreign_country.id,
                "tax_group_id": foreign_tax_group.id,
            }
        )

    def _invoice_vals(self, tax):
        return {
            "move_type": "out_invoice",
            "partner_id": self.partner_a.id,
            "invoice_date": "2026-06-01",
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

    def test_domestic_tax_is_accepted(self):
        domestic_tax = self.company_data["default_tax_sale"]
        self.assertEqual(
            domestic_tax.country_id,
            self.company_data["company"].account_fiscal_country_id,
            "fixture assumption: the default sale tax is domestic",
        )
        move = self.env["account.move"].create(self._invoice_vals(domestic_tax))
        self.assertTrue(move.id)

    def test_foreign_tax_without_a_fiscal_position_is_refused(self):
        self.assertNotEqual(
            self.foreign_country,
            self.company_data["company"].account_fiscal_country_id,
            "fixture assumption: the tax's country is not the fiscal country",
        )
        with self.assertRaisesRegex(
            ValidationError, "incompatible with your fiscal country"
        ):
            self.env["account.move"].create(self._invoice_vals(self.foreign_tax))

    def test_foreign_tax_under_a_matching_foreign_vat_position_is_accepted(self):
        fiscal_position = self.env["account.fiscal.position"].create(
            {
                "name": "Foreign VAT registration",
                "country_id": self.foreign_country.id,
                # `base_vat` validates a fiscal position's foreign_vat through the
                # same checksum as a partner's, so this has to be a real German
                # number -- it is the one base_vat's own error message offers.
                "foreign_vat": "DE123456788",
                "company_id": self.company_data["company"].id,
            }
        )
        move = self.env["account.move"].create(
            {
                **self._invoice_vals(self.foreign_tax),
                "fiscal_position_id": fiscal_position.id,
            }
        )
        self.assertEqual(
            move.tax_country_id,
            self.foreign_country,
            "a foreign-VAT position moves the move's tax country with it",
        )

    def test_foreign_tax_under_a_position_for_another_country_is_refused(self):
        other_country = self.env.ref("base.es")
        fiscal_position = self.env["account.fiscal.position"].create(
            {
                "name": "Other foreign VAT registration",
                "country_id": other_country.id,
                "foreign_vat": "ESA12345674",
                "company_id": self.company_data["company"].id,
            }
        )
        with self.assertRaisesRegex(
            ValidationError, "not compatible with your fiscal position"
        ):
            self.env["account.move"].create(
                {
                    **self._invoice_vals(self.foreign_tax),
                    "fiscal_position_id": fiscal_position.id,
                }
            )
