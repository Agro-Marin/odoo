"""Regression coverage for /mail/avatar/mail.message/.../author_avatar/...

Covers four bugs discovered during the controller audit:

* Empty ``message_su`` (non-existent ``res_id`` + token) used to raise
  ``KeyError: False`` from ``request.env[False]`` and surface as HTTP 500.
  That distinguishes existent from non-existent message ids to an
  unauthenticated caller, so the route must instead serve the placeholder.
* Non-numeric ``pid`` used to raise ``ValueError`` from ``int(pid)`` inside
  the credentialed branch — but only when ``res_id`` resolved to an existing
  message, producing a 500 vs 200 differential that leaked existence.
* Bearer ``access_token`` validation against a ``mail.thread`` model that
  lacked the configured token field (default ``access_token``) used to
  raise ``KeyError`` from ``portal.utils.validate_thread_with_token`` and
  surface as HTTP 500 — same existence-leak shape as above.
* The no-credentials branch must still serve a 200 with image bytes.
"""

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPortalAvatarFallback(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # An existing mail.message so the controller's `candidate_su` is truthy
        # and we exercise the credentialed branch (where the int(pid) crash lived).
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
        """No token / hash / pid → 200, placeholder image bytes."""
        response = self.url_open("/mail/avatar/mail.message/1/author_avatar/50x50")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_invalid_token_with_missing_message_does_not_500(self):
        """Missing ``res_id`` plus a bogus token must NOT leak existence via 500.

        Regression for the ``KeyError: False`` raised by
        ``request.env[message_su.model]`` when ``message_su`` was empty.
        """
        response = self.url_open(
            "/mail/avatar/mail.message/99999999/author_avatar/50x50?access_token=bogus"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_invalid_hash_pid_with_missing_message_does_not_500(self):
        """Same as above but using the HMAC credential path."""
        response = self.url_open(
            "/mail/avatar/mail.message/99999999/author_avatar/50x50?_hash=bogus&pid=1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_non_numeric_pid_on_existing_message_does_not_500(self):
        """Non-numeric ``pid`` on an existing ``res_id`` must not 500.

        Pre-fix: ``int("abc")`` raised inside the call to
        ``_get_thread_with_access``, but only when ``candidate_su`` was
        truthy — i.e. only when the message existed. The 500-vs-200
        differential leaked message existence to unauthenticated callers.
        """
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
        """Same shape, missing message id — the no-leak invariant must hold both ways."""
        response = self.url_open(
            "/mail/avatar/mail.message/99999999/author_avatar/50x50?_hash=bogus&pid=abc"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )

    def test_non_numeric_pid_with_access_token_does_not_500(self):
        """``access_token`` branch must also survive a non-numeric ``pid``.

        Pre-fix: outer guard ``access_token or (_hash and pid)`` entered the
        block on token alone, but ``pid and int(pid)`` was still evaluated
        at the inner call site and crashed.
        """
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
        """``access_token`` must not crash on a thread missing the token field.

        ``mail.thread._mail_post_token_field`` defaults to ``"access_token"``
        but the field itself is declared on ``portal.mixin``. Reaching a
        bare ``mail.thread`` (here ``res.partner``) through a public route
        used to raise ``KeyError: 'access_token'`` from
        :func:`portal.utils.validate_thread_with_token`, producing a 500
        that leaked message existence to unauthenticated callers.
        """
        response = self.url_open(
            f"/mail/avatar/mail.message/{self.existing_message.id}"
            "/author_avatar/50x50?access_token=bogus"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.content[:8].startswith(b"\x89PNG"),
            f"Expected PNG bytes, got {response.content[:8]!r}",
        )
