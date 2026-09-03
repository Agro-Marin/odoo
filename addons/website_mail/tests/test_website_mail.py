from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.website_mail.controllers.main import WebsiteMail


@tagged("post_install", "-at_install")
class TestWebsiteMail(TransactionCase):
    def test_warranty_message_flags_website(self):
        """The publisher warranty message advertises the website presence."""
        base_message = self.env["publisher_warranty.contract"]._get_message()
        self.assertTrue(base_message["website"])
        # the flag is added on top of the inherited payload, not replacing it
        self.assertGreater(len(base_message), 1)

    def test_follow_with_no_matching_partner_does_not_crash(self):
        """A public visitor whose recaptcha check fails and whose email
        matches no existing partner must get a graceful `False`, not an
        unhandled IndexError on the empty partner list."""
        website = self.env["website"].search([], limit=1)
        partner = self.env["res.partner"].create(
            {"name": "Follow Target", "email": "follow-target@example.com"}
        )
        controller = WebsiteMail()
        with MockRequest(self.env, website=website) as request:
            request.env.user = self.env.ref("base.public_user")
            request.website = website
            request.session = {}
            with patch.object(
                type(self.env["ir.http"]),
                "_check_request_recaptcha_token",
                side_effect=ValidationError("The reCaptcha token is invalid."),
            ):
                result = controller.website_message_subscribe(
                    id=partner.id,
                    object="res.partner",
                    message_is_follower="off",
                    email="brand-new-follower@example.com",
                )
        self.assertFalse(result)
