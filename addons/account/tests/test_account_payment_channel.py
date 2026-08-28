from odoo.tests import Form, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountPaymentChannel(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.bank_journal_1 = cls.company_data["default_journal_bank"]
        cls.bank_journal_2 = cls.company_data["default_journal_bank"].copy()

        cls.inbound_payment_channel_1 = cls.env[
            "account.payment.channel"
        ].create(
            {
                "name": "new inbound payment method line 1",
                "payment_method_id": cls.bank_journal_1.available_payment_method_ids[
                    0
                ].id,
                "payment_type": "inbound",
                "journal_id": cls.bank_journal_1.id,
            }
        )
        cls.inbound_payment_channel_2 = cls.env[
            "account.payment.channel"
        ].create(
            {
                "name": "new inbound payment method line 2",
                "payment_method_id": cls.bank_journal_1.available_payment_method_ids[
                    0
                ].id,
                "payment_type": "inbound",
                "journal_id": cls.bank_journal_1.id,
            }
        )
        cls.inbound_payment_channel_other_journal = cls.env[
            "account.payment.channel"
        ].create(
            {
                "name": "new inbound payment method line other journal",
                "payment_method_id": cls.bank_journal_2.available_payment_method_ids[
                    0
                ].id,
                "payment_type": "inbound",
                "journal_id": cls.bank_journal_2.id,
            }
        )
        cls.partner_c = cls.partner_a.copy()
        cls.partner_a.property_inbound_payment_channel_id = (
            cls.inbound_payment_channel_1
        )
        cls.partner_b.property_inbound_payment_channel_id = (
            cls.inbound_payment_channel_2
        )
        cls.partner_c.property_inbound_payment_channel_id = (
            cls.inbound_payment_channel_other_journal
        )

        cls.move_partner_a = cls.init_invoice(
            move_type="out_invoice",
            partner=cls.partner_a,
            products=cls.product_a,
            post=True,
        )
        cls.move_partner_b = cls.init_invoice(
            move_type="out_invoice",
            partner=cls.partner_b,
            products=cls.product_a,
            post=True,
        )
        cls.move_partner_c = cls.init_invoice(
            move_type="out_invoice",
            partner=cls.partner_c,
            products=cls.product_a,
            post=True,
        )

    def assertRegisterPayment(
        self,
        expected_journal,
        expected_payment_method,
        move_partner,
        payment_channel=False,
    ):
        if payment_channel and expected_payment_method:
            move_partner.preferred_payment_channel_id = expected_payment_method

        payment = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move",
                active_ids=move_partner.ids,
            )
            .create({})
        )

        if not expected_payment_method:
            expected_payment_method = (
                payment.journal_id._get_available_payment_channels(
                    payment.payment_type
                )[0]._origin
            )

        self.assertRecordValues(
            payment,
            [
                {
                    "journal_id": expected_journal.id,
                    "payment_channel_id": expected_payment_method.id,
                }
            ],
        )

    def test_move_register_payment_wizard(self):
        self.assertRegisterPayment(
            self.bank_journal_1,
            self.inbound_payment_channel_1,
            self.move_partner_a,
        )
        self.assertRegisterPayment(
            self.bank_journal_1,
            self.inbound_payment_channel_2,
            self.move_partner_a,
            True,
        )
        self.assertRegisterPayment(
            self.bank_journal_2,
            self.inbound_payment_channel_other_journal,
            self.move_partner_a,
            True,
        )

    def test_multiple_moves_register_payment(self):
        move_partner_a_copy = self.move_partner_a.copy()
        move_partner_a_copy.action_post()
        self.assertRegisterPayment(
            self.bank_journal_1,
            self.inbound_payment_channel_1,
            self.move_partner_a + move_partner_a_copy,
        )

        self.partner_d = self.partner_a.copy()
        move_partner_d = self.init_invoice(
            move_type="out_invoice",
            partner=self.partner_d,
            products=self.product_a,
            post=True,
        )
        self.assertRegisterPayment(
            self.bank_journal_1,
            self.inbound_payment_channel_1,
            self.move_partner_a + move_partner_d,
        )

        self.assertRegisterPayment(
            self.bank_journal_1,
            None,
            self.move_partner_a + self.move_partner_b,
        )

    def test_move_register_payment_view(self):
        with Form(
            self.env["account.payment"].with_context(default_partner_id=self.partner_a)
        ) as pay_form:
            self.assertEqual(pay_form.journal_id.id, self.bank_journal_1.id)
            self.assertEqual(
                pay_form.payment_channel_id.id,
                self.inbound_payment_channel_1.id,
            )

            pay_form.partner_id = self.partner_b
            self.assertEqual(
                pay_form.payment_channel_id.id,
                self.inbound_payment_channel_2.id,
            )

            pay_form.partner_id = self.partner_c
            self.assertEqual(pay_form.journal_id.id, self.bank_journal_2.id)
            self.assertEqual(
                pay_form.payment_channel_id.id,
                self.inbound_payment_channel_other_journal.id,
            )
