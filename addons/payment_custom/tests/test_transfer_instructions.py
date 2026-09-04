"""The wire-transfer instructions and their QR code read one bank account."""

from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.payment_custom.tests.common import PaymentCustomCommon


@tagged("-at_install", "post_install")
class TestTransferInstructions(PaymentCustomCommon):
    """Every company gets instructions, and they name the account the QR charges."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls._prepare_provider(code="custom", custom_mode="wire_transfer")
        cls.company_partner = cls.provider.company_id.partner_id
        # Two accounts on the company, so "the first one" and "the chosen one" are
        # not the same record: `bank_ids[:1]` orders by `sequence, id`.
        cls.first_account, cls.chosen_account = cls.env["res.partner.bank"].create(
            [
                {
                    "acc_number": "BE15001559627230",
                    "partner_id": cls.company_partner.id,
                    "sequence": 1,
                },
                {
                    "acc_number": "BE49001559627231",
                    "partner_id": cls.company_partner.id,
                    "sequence": 2,
                },
            ]
        )

    def _render_pending_page(self, tx):
        """Return the portal payment status page for a pending transaction."""
        return str(
            self.env["ir.qweb"]._render(
                "payment.state_header", {"tx": tx, "is_processing": False}
            )
        )

    def test_a_company_created_after_install_gets_transfer_instructions(self):
        """The provider copied to a new company still tells the customer where to pay."""
        company = self.env["res.company"].create({"name": "Wire Transfer Co"})

        provider = (
            self.env["payment.provider"]
            .sudo()
            .search(
                [
                    ("company_id", "=", company.id),
                    ("code", "=", "custom"),
                    ("custom_mode", "=", "wire_transfer"),
                ]
            )
        )

        self.assertTrue(provider, "no wire transfer provider was copied to the company")
        self.assertTrue(
            provider._get_status_message("pending"),
            "the new company's wire transfer provider offers no payment instructions",
        )

    def test_the_instructions_name_the_bank_account_chosen_on_the_provider(self):
        """The rendered instructions name the provider's account, not another one."""
        self.provider.partner_bank_id = self.chosen_account
        tx = self._create_transaction(flow="direct")
        tx._set_pending()

        rendered = self._render_pending_page(tx)

        self.assertIn(self.chosen_account.acc_number, rendered)
        self.assertNotIn(self.first_account.acc_number, rendered)

    def test_the_qr_charges_the_bank_account_chosen_on_the_provider(self):
        """The QR is built from the provider's account, whatever the company's first is."""
        self.provider.write(
            {"qr_code": True, "partner_bank_id": self.chosen_account.id}
        )
        tx = self._create_transaction(flow="direct")
        ResPartnerBank = type(self.env["res.partner.bank"])

        with patch.object(
            ResPartnerBank,
            "build_qr_code_base64",
            autospec=True,
            return_value="data:image/png;base64,QR",
        ) as build_qr:
            qr_code = tx._get_custom_qr_code()

        self.assertEqual(qr_code, "data:image/png;base64,QR")
        self.assertEqual(
            build_qr.call_args.args[0],
            self.chosen_account,
            "the QR was built from another account than the provider's",
        )

    def test_no_qr_code_when_the_provider_does_not_offer_one(self):
        """A provider with QR codes off returns nothing to render."""
        self.provider.write(
            {"qr_code": False, "partner_bank_id": self.chosen_account.id}
        )
        tx = self._create_transaction(flow="direct")

        self.assertFalse(tx._get_custom_qr_code())

    def test_the_bank_account_defaults_to_the_company_first_one(self):
        """A new provider gets an account without anyone having to pick one."""
        provider = self.env["payment.provider"].create(
            {
                "name": "Another wire transfer",
                "code": "custom",
                "custom_mode": "wire_transfer",
                "company_id": self.provider.company_id.id,
            }
        )

        self.assertEqual(
            provider._get_custom_bank_account(), self.company_partner.bank_ids[:1]
        )
