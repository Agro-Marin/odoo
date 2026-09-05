import base64

from odoo.tests.common import HttpCase, JsonRpcException, tagged

from odoo.addons.mail.tests.common import mail_new_test_user

ONE_PIXEL_PNG = (
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2"
    b"FzhVAAAAAElFTkSuQmCC"
)


@tagged("-at_install", "post_install")
class TestPortalProfilePicture(HttpCase):
    """A portal user owns their own avatar; nobody else's."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = mail_new_test_user(
            cls.env,
            "portal_profile",
            groups="base.group_portal",
            name="Portal Profile",
        )
        cls.other_user = mail_new_test_user(
            cls.env,
            "portal_profile_other",
            groups="base.group_portal",
            name="Portal Profile Other",
        )

    def _login(self):
        self.authenticate("portal_profile", "portal_profile")

    def test_portal_user_sets_own_picture(self):
        self._login()
        self.assertFalse(self.portal_user.image_1920)

        self.call_jsonrpc(
            "/my/profile/save",
            params={"image_1920": ONE_PIXEL_PNG.decode()},
        )

        self.assertTrue(self.portal_user.image_1920)
        self.assertTrue(base64.b64decode(self.portal_user.image_1920))
        self.assertTrue(self.portal_user.avatar_512)

    def test_portal_user_clears_own_picture(self):
        self.portal_user.sudo().image_1920 = ONE_PIXEL_PNG
        self._login()

        self.call_jsonrpc("/my/profile/save", params={"image_1920": False})

        self.assertFalse(self.portal_user.image_1920)

    def test_route_never_touches_another_user(self):
        """The route takes no user: it writes the session's own record, always."""
        self._login()

        self.call_jsonrpc(
            "/my/profile/save",
            params={"image_1920": ONE_PIXEL_PNG.decode()},
        )

        self.assertTrue(self.portal_user.image_1920)
        self.assertFalse(self.other_user.image_1920)

    def test_non_string_payload_is_refused_cleanly(self):
        """A bad payload must come back as an error, not as an ORM traceback."""
        self._login()

        for payload in ({"nope": 1}, 42, ["a"]):
            with self.subTest(payload=payload):
                with self.assertRaises(JsonRpcException) as capture:
                    self.call_jsonrpc(
                        "/my/profile/save", params={"image_1920": payload}
                    )
                self.assertNotIn("TypeError", str(capture.exception))
                self.assertNotIn("ValueError", str(capture.exception))
                self.assertFalse(self.portal_user.image_1920)

    def test_my_account_renders_the_picture_card(self):
        self._login()

        response = self.url_open("/my/account")

        self.assertEqual(response.status_code, 200)
        self.assertIn("o_portal_profile_card", response.text)
