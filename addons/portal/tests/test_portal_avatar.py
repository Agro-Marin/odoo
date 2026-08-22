from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPortalAvatarFallback(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env["res.partner"].create({"name": "Avatar Audit Partner"})
        cls.existing_message = cls.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": partner.id,
                "body": "test",
                "message_type": "comment",
            }
        )

    def test_no_credentials_serves_image(self):
        response = self.url_open("/mail/avatar/mail.message/1/author_avatar/50x50")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_invalid_token_with_missing_message_does_not_500(self):
        response = self.url_open(
            "/mail/avatar/mail.message/99999999/author_avatar/50x50?access_token=bogus"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_invalid_hash_pid_with_missing_message_does_not_500(self):
        response = self.url_open(
            "/mail/avatar/mail.message/99999999/author_avatar/50x50?_hash=bogus&pid=1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_non_numeric_pid_on_existing_message_does_not_500(self):
        response = self.url_open(
            f"/mail/avatar/mail.message/{self.existing_message.id}"
            "/author_avatar/50x50?_hash=bogus&pid=abc"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_non_numeric_pid_on_missing_message_does_not_500(self):
        response = self.url_open(
            "/mail/avatar/mail.message/99999999/author_avatar/50x50?_hash=bogus&pid=abc"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_non_numeric_pid_with_access_token_does_not_500(self):
        response = self.url_open(
            f"/mail/avatar/mail.message/{self.existing_message.id}"
            "/author_avatar/50x50?access_token=bogus&pid=abc"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_access_token_on_thread_without_token_field_does_not_500(self):
        response = self.url_open(
            f"/mail/avatar/mail.message/{self.existing_message.id}"
            "/author_avatar/50x50?access_token=bogus"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )
