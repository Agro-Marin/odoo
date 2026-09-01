import json
from unittest.mock import patch

import odoo.tests
from odoo.tests.common import HttpCase, new_test_user

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'


class _Response:
    """The two shapes `save_library_media` reads off `requests`."""

    def __init__(self, payload=None, content=b"", headers=None):
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.status_code = 200

    def json(self):
        return self._payload


@odoo.tests.tagged("-at_install", "post_install")
class TestLibraryMediaPortal(HttpCase):
    """The Illustrations tab of the media dialog is reachable by a portal user
    -- the route is `auth="user"` -- but every attachment it deals with belongs
    to `ir.ui.view`, and portal has no read on `ir.attachment`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = new_test_user(
            cls.env, login="portal_library", groups="base.group_portal"
        )
        cls.internal_user = new_test_user(
            cls.env, login="internal_library", groups="base.group_user"
        )
        cls.headers = {"Content-Type": "application/json"}

    def _save_library_media(self):
        media = {"42": {"query": "tree", "is_dynamic_svg": False}}
        with (
            patch(
                "odoo.addons.html_editor.controllers.main.requests.post",
                return_value=_Response(payload={"42": "https://example.com/tree.svg"}),
            ),
            patch(
                "odoo.addons.html_editor.controllers.main.requests.get",
                return_value=_Response(
                    content=SVG, headers={"content-type": "image/svg+xml"}
                ),
            ),
            patch(
                "odoo.addons.mail.tools.link_preview._url_is_safe",
                return_value=True,
            ),
        ):
            return self.url_open(
                "/html_editor/save_library_media",
                data=json.dumps(self.prepare_rpc_payload({"media": media})),
                headers=self.headers,
            ).json()

    def test_portal_user_can_save_a_library_illustration(self):
        self.authenticate("portal_library", "portal_library")
        response = self._save_library_media()
        self.assertNotIn("error", response, response.get("error"))
        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["mimetype"], "image/svg+xml")

    def test_a_second_save_reuses_the_attachment_it_already_created(self):
        self.authenticate("portal_library", "portal_library")
        first = self._save_library_media()
        second = self._save_library_media()
        self.assertNotIn("error", second, second.get("error"))
        self.assertEqual(
            first["result"][0]["id"],
            second["result"][0]["id"],
            "the same illustration was stored twice",
        )

    def test_internal_user_is_unaffected(self):
        self.authenticate("internal_library", "internal_library")
        response = self._save_library_media()
        self.assertNotIn("error", response, response.get("error"))
        self.assertEqual(len(response["result"]), 1)
