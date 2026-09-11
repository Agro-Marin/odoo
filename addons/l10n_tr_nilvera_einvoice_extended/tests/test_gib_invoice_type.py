from odoo.tests import tagged

from odoo.addons.l10n_tr_nilvera_einvoice.tests.test_xml_ubl_tr_common import (
    TestUBLTRCommon,
)


@tagged("post_install_l10n", "post_install", "-at_install")
class TestGibInvoiceType(TestUBLTRCommon):
    def _invoice(self, **vals):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": self.company_data["company"].id,
                "partner_id": self.einvoice_partner.id,
                **vals,
            }
        )

    def test_a_new_invoice_is_a_sales_invoice(self):
        self.assertEqual(self._invoice().l10n_tr_gib_invoice_type, "SATIS")

    def test_an_explicit_invoice_type_is_kept(self):
        invoice = self._invoice(l10n_tr_gib_invoice_type="ISTISNA")

        self.assertEqual(invoice.l10n_tr_gib_invoice_type, "ISTISNA")

    def test_changing_the_scenario_resets_the_type_to_sales_not_to_nothing(self):
        invoice = self._invoice(l10n_tr_gib_invoice_type="TEVKIFAT")

        invoice.l10n_tr_gib_invoice_scenario = "KAMU"

        self.assertEqual(invoice.l10n_tr_gib_invoice_type, "SATIS")
