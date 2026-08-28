from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.mail.tests.common import MailCase


@tagged("post_install", "-at_install")
class TestResPartnerBankTracking(AccountTestInvoicingCommon, MailCase):
    """`ResPartnerBank.write` logs the tracked change on the partner that owns
    the account, and -- when the account moved -- on the partner that lost it.
    Nothing else asserts that second log, so a change to the tracking API would
    remove it silently.
    """

    @classmethod
    def default_env_context(cls):
        # OVERRIDE: the common context disables tracking, which is the whole
        # subject of this test.
        return {}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.old_owner = cls.env["res.partner"].create({"name": "Old Owner"})
        cls.new_owner = cls.env["res.partner"].create({"name": "New Owner"})

    def test_moving_a_bank_account_logs_on_both_partners(self):
        bank = self.env["res.partner.bank"].create(
            {
                "acc_number": "12345",
                "acc_holder_name": "Old Owner",
                "partner_id": self.old_owner.id,
            }
        )
        self.flush_tracking()

        with self.mock_mail_gateway(), self.mock_mail_app():
            bank.write(
                {
                    "active": False,
                    "allow_out_payment": True,
                    "acc_number": "99999",
                    "clearing_number": "123456789",
                    "acc_holder_name": "Marcel Offane",
                    "partner_id": self.new_owner.id,
                }
            )
            self.flush_tracking()

        partner_msgs = self._new_msgs.filtered(lambda m: m.model == "res.partner")
        self.assertEqual(
            sorted(partner_msgs.mapped("res_id")),
            sorted((self.old_owner + self.new_owner).ids),
            "the partner that lost the account is logged too",
        )
        for msg in partner_msgs:
            self.assertMessageFields(
                msg,
                {
                    "body": (
                        "<p>Bank Account "
                        f'<a href="#" data-oe-model="{bank._name}" '
                        f'data-oe-id="{bank.id}">#{bank.id}</a> updated</p>'
                    ),
                    "model": "res.partner",
                    "subtype_id": self.env.ref("mail.mt_note"),
                    "tracking_values": [
                        ("active", "boolean", True, False),
                        ("allow_out_payment", "boolean", False, True),
                        ("acc_number", "char", "12345", "99999"),
                        ("clearing_number", "char", False, "123456789"),
                        ("acc_holder_name", "char", "Old Owner", "Marcel Offane"),
                        ("partner_id", "many2one", self.old_owner, self.new_owner),
                    ],
                },
            )
