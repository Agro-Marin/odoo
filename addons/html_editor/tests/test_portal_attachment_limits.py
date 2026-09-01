import json
from base64 import b64encode
from unittest.mock import patch

import odoo.tests
from odoo.tests.common import HttpCase, new_test_user


@odoo.tests.tagged("-at_install", "post_install")
class TestPortalAttachmentLimits(HttpCase):
    """`_attachment_create` creates with sudo whenever a module allows the media
    dialog to bypass the caller's rights -- `website_forum` does, for any portal
    user whose karma reaches `karma_editor`. The bypass must not hand that user
    an unrestricted `ir.attachment.create`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = new_test_user(
            cls.env, login="portal_limits", groups="base.group_portal"
        )
        cls.internal_user = new_test_user(
            cls.env, login="internal_limits", groups="base.group_user"
        )
        cls.headers = {"Content-Type": "application/json"}
        cls.pixel = "R0lGODlhAQABAIAAAP///wAAACwAAAAAAQABAAACAkQBADs="

    def _add_data(self, **params):
        # The bypass itself lives in the modules that grant it (website_forum,
        # web_unsplash); html_editor's own hook returns False, so the branch
        # under test is unreachable here without standing in for one of them.
        with patch.object(
            type(self.env["ir.attachment"]),
            "_can_bypass_rights_on_media_dialog",
            return_value=True,
        ):
            return self.url_open(
                "/html_editor/attachment/add_data",
                data=json.dumps(self.prepare_rpc_payload(params)),
                headers=self.headers,
            ).json()

    def test_portal_cannot_upload_a_non_image_through_the_bypass(self):
        self.authenticate("portal_limits", "portal_limits")
        response = self._add_data(
            name="payload.txt",
            data=b64encode(b"not an image at all").decode(),
            is_image=False,
        )
        self.assertIn("error", response, "a portal user uploaded a text file")
        self.assertFalse(
            self.env["ir.attachment"].search([("name", "=", "payload.txt")]),
            "the attachment was created before the check refused it",
        )

    def test_portal_cannot_upload_a_file_over_the_size_limit(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "html_editor.max_portal_file_size", "16"
        )
        self.authenticate("portal_limits", "portal_limits")
        response = self._add_data(name="big.gif", data=self.pixel, is_image=False)
        self.assertIn("error", response, "a portal user uploaded an oversized file")

    def test_portal_can_still_upload_a_small_image(self):
        self.authenticate("portal_limits", "portal_limits")
        response = self._add_data(name="tiny.gif", data=self.pixel, is_image=False)
        self.assertNotIn("error", response, response.get("error"))
        self.assertTrue(self.env["ir.attachment"].search([("name", "=", "tiny.gif")]))

    def test_internal_user_is_not_subject_to_the_portal_limits(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "html_editor.max_portal_file_size", "16"
        )
        self.authenticate("internal_limits", "internal_limits")
        response = self._add_data(
            name="internal.txt",
            data=b64encode(b"not an image at all").decode(),
            is_image=False,
        )
        self.assertNotIn("error", response, response.get("error"))
        self.assertTrue(
            self.env["ir.attachment"].search([("name", "=", "internal.txt")])
        )
