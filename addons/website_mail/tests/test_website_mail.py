# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWebsiteMail(TransactionCase):
    def test_warranty_message_flags_website(self):
        """The publisher warranty message advertises the website presence."""
        base_message = self.env["publisher_warranty.contract"]._get_message()
        self.assertTrue(base_message["website"])
        # the flag is added on top of the inherited payload, not replacing it
        self.assertGreater(len(base_message), 1)
