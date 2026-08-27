from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.account_payment.tests.common import AccountPaymentCommon


@tagged("-at_install", "post_install")
class TestPaymentRefundWizard(AccountPaymentCommon):
    def _create_wizard(self, payment):
        return (
            self.env["payment.refund.wizard"]
            .with_context(active_id=payment.id)
            .create({})
        )

    def test_amount_to_refund_defaults_to_amount_available_for_refund(self):
        self.provider.support_refund = "full_only"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment

        wizard = self._create_wizard(tx.payment_id)

        self.assertAlmostEqual(
            wizard.amount_to_refund,
            tx.payment_id.amount_available_for_refund,
            places=2,
            msg="amount_to_refund should default to amount_available_for_refund.",
        )

    def test_refunded_amount_reflects_already_refunded_transactions(self):
        self.provider.support_refund = "partial"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment
        self._create_transaction(
            "redirect",
            reference=f"{tx.reference}-refund",
            amount=-1,
            operation="refund",
            source_transaction_id=tx.id,
            state="done",
        )._post_process()

        wizard = self._create_wizard(tx.payment_id)

        self.assertAlmostEqual(
            wizard.refunded_amount,
            1,
            places=2,
            msg="refunded_amount should be payment_amount minus amount_available_for_refund.",
        )

    def test_support_refund_none_when_provider_does_not_support_it(self):
        self.provider.support_refund = "none"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment

        wizard = self._create_wizard(tx.payment_id)

        self.assertEqual(wizard.support_refund, "none")

    def test_support_refund_full_only_when_provider_only_supports_that(self):
        self.provider.support_refund = "full_only"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment

        wizard = self._create_wizard(tx.payment_id)

        self.assertEqual(wizard.support_refund, "full_only")

    def test_has_pending_refund_true_when_a_refund_is_in_progress(self):
        self.provider.support_refund = "partial"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment
        self._create_transaction(
            "redirect",
            reference=f"{tx.reference}-refund",
            amount=-1,
            operation="refund",
            source_transaction_id=tx.id,
            state="pending",
        )

        wizard = self._create_wizard(tx.payment_id)

        self.assertTrue(wizard.has_pending_refund)

    def test_amount_to_refund_rejects_zero(self):
        self.provider.support_refund = "full_only"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment
        wizard = self._create_wizard(tx.payment_id)

        with self.assertRaises(ValidationError):
            wizard.amount_to_refund = 0

    def test_amount_to_refund_rejects_amount_above_available(self):
        self.provider.support_refund = "full_only"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment
        wizard = self._create_wizard(tx.payment_id)

        with self.assertRaises(ValidationError):
            wizard.amount_to_refund = tx.payment_id.amount_available_for_refund + 1

    def test_action_refund_delegates_to_transaction(self):
        self.provider.support_refund = "full_only"
        tx = self._create_transaction("redirect", state="done")
        tx._post_process()  # Create the payment
        wizard = self._create_wizard(tx.payment_id)

        wizard.action_refund()

        refund_tx = self.env["payment.transaction"].search(
            [("source_transaction_id", "=", tx.id), ("operation", "=", "refund")]
        )
        self.assertEqual(len(refund_tx), 1)
        self.assertAlmostEqual(-refund_tx.amount, wizard.amount_to_refund, places=2)
