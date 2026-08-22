from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountPaymentDuplicateMoves(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.company_data["company"]
        cls.receivable = cls.company_data["default_account_receivable"]
        cls.payable = cls.company_data["default_account_payable"]
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.comp_curr = cls.company_data["currency"]

        cls.payment_in = cls.env["account.payment"].create(
            {
                "amount": 50.0,
                "payment_type": "inbound",
                "partner_id": cls.partner_a.id,
                "destination_account_id": cls.receivable.id,
            }
        )
        cls.payment_out = cls.env["account.payment"].create(
            {
                "amount": 50.0,
                "payment_type": "outbound",
                "partner_id": cls.partner_a.id,
                "destination_account_id": cls.payable.id,
            }
        )

        cls.out_invoice_1 = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": cls.partner_a.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product_a.id,
                            "price_unit": 50.0,
                            "tax_ids": [],
                        },
                    )
                ],
            }
        )
        cls.in_invoice_1 = cls.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": cls.partner_a.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product_a.id,
                            "price_unit": 50.0,
                            "tax_ids": [],
                        },
                    )
                ],
            }
        )
        cls.out_invoice_2 = cls.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2017-01-01",
                "invoice_date": "2017-01-01",
                "partner_id": cls.partner_a.id,
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": cls.product_a.id,
                            "price_unit": 20.0,
                            "tax_ids": [],
                        },
                    )
                ],
            }
        )
        (cls.out_invoice_1 + cls.out_invoice_2 + cls.in_invoice_1).action_post()

    def test_duplicate_payments(self):
        payment_in_1 = self.payment_in
        payment_out_1 = self.payment_out

        self.assertRecordValues(payment_in_1, [{"duplicate_payment_ids": []}])

        payment_in_2 = payment_in_1.copy(default={"date": payment_in_1.date})
        payment_out_2 = payment_out_1.copy(default={"date": payment_out_1.date})
        self.assertRecordValues(
            payment_in_2,
            [
                {
                    "duplicate_payment_ids": [payment_in_1.id],
                }
            ],
        )
        self.assertRecordValues(
            payment_out_2,
            [
                {
                    "duplicate_payment_ids": [payment_out_1.id],
                }
            ],
        )
        payment_out_3 = payment_out_1.copy(default={"date": "2023-12-31"})
        self.assertRecordValues(payment_out_3, [{"duplicate_payment_ids": []}])

        payment_out_4 = self.env["account.payment"].create(
            {
                "amount": 60.0,
                "payment_type": "outbound",
                "partner_id": self.partner_a.id,
                "destination_account_id": self.payable.id,
            }
        )
        self.assertRecordValues(payment_out_4, [{"duplicate_payment_ids": []}])

        payment_out_5 = self.env["account.payment"].create(
            {
                "amount": 50.0,
                "payment_type": "outbound",
                "partner_id": self.partner_b.id,
                "destination_account_id": self.payable.id,
            }
        )
        self.assertRecordValues(payment_out_5, [{"duplicate_payment_ids": []}])

    def test_in_payment_multiple_duplicate_inbound_batch(self):
        payment_1 = self.payment_in
        payment_2 = payment_1.copy(default={"date": payment_1.date})
        payment_3 = payment_1.copy(default={"date": payment_1.date})

        payments = payment_1 + payment_2 + payment_3

        self.assertRecordValues(
            payments,
            [
                {"duplicate_payment_ids": (payment_2 + payment_3).ids},
                {"duplicate_payment_ids": (payment_1 + payment_3).ids},
                {"duplicate_payment_ids": (payment_1 + payment_2).ids},
            ],
        )

    def test_in_payment_multiple_duplicate_multiple_journals(self):
        payment_in_1 = self.payment_in
        payment_out_1 = self.payment_out
        bank_journal_B = self.bank_journal.copy()
        bank_journal_B.inbound_payment_method_line_ids.payment_account_id = self.env[
            "account.account"
        ].create(
            {
                "name": "Outstanding Payment Account B",
                "code": "OPAB",
                "account_type": "asset_current",
                "reconcile": True,
            }
        )
        payment_in_2 = payment_in_1.copy(default={"date": payment_in_1.date})
        payment_in_2.journal_id = bank_journal_B
        payment_out_2 = payment_out_1.copy(default={"date": payment_out_1.date})
        payment_out_2.journal_id = bank_journal_B

        payments = payment_in_1 + payment_out_1 + payment_in_2 + payment_out_2

        self.assertRecordValues(
            payments,
            [
                {"duplicate_payment_ids": [payment_in_2.id]},
                {"duplicate_payment_ids": [payment_out_2.id]},
                {"duplicate_payment_ids": [payment_in_1.id]},
                {"duplicate_payment_ids": [payment_out_1.id]},
            ],
        )

    def test_register_payment_different_payment_types(self):
        payment_1 = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move", active_ids=self.out_invoice_1.ids
            )
            .create({"payment_date": self.payment_in.date})
        )
        payment_2 = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=self.in_invoice_1.ids)
            .create({"payment_date": self.payment_out.date})
        )
        existing_payment_in = self.payment_in
        existing_payment_out = self.payment_out

        self.assertRecordValues(
            payment_1, [{"duplicate_payment_ids": [existing_payment_in.id]}]
        )
        self.assertRecordValues(
            payment_2, [{"duplicate_payment_ids": [existing_payment_out.id]}]
        )

    def test_register_payment_single_batch_duplicate_payments(self):
        payment_1 = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move", active_ids=self.out_invoice_1.ids
            )
            .create({"payment_date": self.payment_in.date})
        )
        payment_2 = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move", active_ids=self.out_invoice_2.ids
            )
            .create({"payment_date": self.out_invoice_2.date})
        )
        active_ids = (self.out_invoice_1 + self.out_invoice_2).ids
        combined_payments = (
            self.env["account.payment.register"]
            .with_context(active_model="account.move", active_ids=active_ids)
            .create(
                {
                    "amount": 50.0,
                    "group_payment": True,
                    "payment_difference_handling": "open",
                    "payment_method_line_id": self.inbound_payment_method_line.id,
                }
            )
        )
        existing_payment = self.payment_in

        self.assertRecordValues(
            payment_1, [{"duplicate_payment_ids": [existing_payment.id]}]
        )
        self.assertRecordValues(
            payment_2, [{"duplicate_payment_ids": []}]
        )
        self.assertRecordValues(
            combined_payments, [{"duplicate_payment_ids": [existing_payment.id]}]
        )
