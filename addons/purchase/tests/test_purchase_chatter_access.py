from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseChatterReadAccess(AccountTestInvoicingCommon):
    """A read-only reader of a purchase order must be able to answer in its chatter.

    `purchase/security/ir.model.access.csv` grants `account.group_account_readonly`
    read without write, so without `_mail_post_access = "read"` such a user sees the
    conversation and cannot reply to it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Read-only accountant",
                    "login": "po_reader",
                    "email": "po_reader@example.com",
                    "company_id": cls.env.company.id,
                    "company_ids": [Command.set(cls.env.company.ids)],
                    "group_ids": [
                        Command.set(
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref("account.group_account_readonly").id,
                            ]
                        )
                    ],
                }
            )
        )
        cls.order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create({"product_id": cls.product_a.id, "product_qty": 3.0})
                ],
            }
        )

    def test_reader_has_read_but_not_write(self):
        order = self.order.with_user(self.reader)
        self.assertTrue(order.name, "the read-only group must still be able to read")
        with self.assertRaises(AccessError):
            order.notes = "nope"

    def test_reader_can_post_on_chatter(self):
        order = self.order.with_user(self.reader)
        before = len(self.order.message_ids)
        order.message_post(body="Received today, invoice to follow.")
        self.assertEqual(
            len(self.order.message_ids),
            before + 1,
            "a read-only reader must be able to answer in the chatter",
        )

    def test_purchase_order_opts_into_read_post_access(self):
        self.assertEqual(self.env["purchase.order"]._mail_post_access, "read")
