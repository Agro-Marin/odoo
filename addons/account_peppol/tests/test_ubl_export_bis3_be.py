from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account_edi_ubl_cii.tests.test_ubl_export_bis3_be import (
    TestUblExportBis3BE,
)


@tagged(
    "post_install_l10n", "post_install", "-at_install", *TestUblExportBis3BE.extra_tags
)
class TestUblExportBis3BEPeppol(TestUblExportBis3BE):
    def test_invoice_PEPPOL_EN16931_R010_R020_ensure_customer_supplier_endpoint_id(
        self,
    ):
        partner = self.env["res.partner"].create(
            {
                **self._create_partner_default_values(),
                "name": "partner",
                "country_id": self.env.ref("base.be").id,
            }
        )
        tax_21 = self.percent_tax(21.0)
        product = self._create_product(lst_price=10.0, taxes_id=tax_21)

        invoice = self._create_invoice_one_line(
            product_id=product, partner_id=partner, post=True
        )
        with self.assertRaisesRegex(UserError, r".*\[PEPPOL\-EN16931\-R010\].*"):
            self._generate_invoice_ubl_file(invoice, sending_methods=["peppol"])
        self._generate_invoice_ubl_file(invoice)
        self.assertTrue(invoice.ubl_cii_xml_id)

        invoice = self._create_invoice_one_line(
            product_id=product, partner_id=partner, post=True
        )
        partner.peppol_eas = "0208"
        partner.peppol_endpoint = "0477472701"
        company_partner = self.env.company.partner_id
        company_partner.vat = None
        company_partner.company_registry = None
        company_partner.peppol_eas = None
        company_partner.peppol_endpoint = None
        with self.assertRaisesRegex(UserError, r".*\[PEPPOL\-EN16931\-R020\].*"):
            self._generate_invoice_ubl_file(invoice, sending_methods=["peppol"])
        self._generate_invoice_ubl_file(invoice)
        self.assertTrue(invoice.ubl_cii_xml_id)
