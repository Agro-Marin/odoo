"""Regression tests for the third mail hardening audit.

Each test pins a specific bug found in the audit so a future refactor cannot
silently reintroduce it. Kept backend-only (no browser) for fast, deterministic
runs; the SSRF guard and link-preview head parser are exercised as pure units
(literal IPs, so no DNS/network is touched).
"""

import io
from unittest.mock import patch

import requests

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.mail.tests.common import MailCommon
from odoo.addons.mail.tools import link_preview


@tagged("post_install", "-at_install")
class TestLinkPreviewSSRF(TransactionCase):
    def test_url_is_safe_rejects_internal_targets(self):
        """The server-side link-preview fetch must refuse non-public targets.

        Any user who can post a message controls the URL, so without this guard
        the sudo/public fetch is an SSRF primitive (cloud metadata, localhost,
        private ranges, non-http schemes). Literal IPs keep this DNS-free.
        """
        for url in (
            "http://127.0.0.1/",
            "http://localhost:8069/web",  # resolves to loopback
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://[::1]/",  # ipv6 loopback
            "http://100.64.0.1/",  # CGNAT / shared address space
            "ftp://example.com/",  # non-http(s) scheme
            "file:///etc/passwd",
            "http://0.0.0.0/",
        ):
            self.assertFalse(
                link_preview._url_is_safe(url), f"{url} should be rejected"
            )

    def test_url_is_safe_allows_public_hosts(self):
        for url in ("http://8.8.8.8/", "https://1.1.1.1/", "http://93.184.216.34/"):
            self.assertTrue(link_preview._url_is_safe(url), f"{url} should be allowed")

    def test_fetch_revalidates_each_redirect_hop(self):
        """A public first hop must not be able to 302 into the internal network."""
        calls = []

        class _RedirectResp:
            is_redirect = True
            headers = {"location": "http://169.254.169.254/latest/meta-data/"}

            def close(self):
                pass

        def _fake_get(url, **kwargs):
            calls.append(url)
            return _RedirectResp()

        session = requests.Session()
        with patch.object(session, "get", side_effect=_fake_get):
            resp = link_preview._fetch_link_preview_response(
                "http://8.8.8.8/", session, {}
            )
        # First (public) hop fetched, redirect target is internal -> refused.
        self.assertIsNone(resp)
        self.assertEqual(calls, ["http://8.8.8.8/"])


@tagged("post_install", "-at_install")
class TestLinkPreviewHead(TransactionCase):
    def _html_response(self, content):
        response = requests.Response()
        response.status_code = 200
        response._content = content
        response.encoding = None  # force the chardet path
        response.raw = io.BytesIO(content)
        response.headers["Content-Type"] = "text/html"
        return response

    def test_head_scan_caps_unbounded_body(self):
        """A body streamed with no </head> must not be buffered without bound."""
        # 2 MB of content, no </head> sentinel.
        big = b"<html><head><title>x</title>" + b"a" * (2 * 1024 * 1024)
        response = self._html_response(big)
        # Must return without exhausting memory; the parser still finds <title>.
        result = link_preview.get_link_preview_from_html("http://8.8.8.8/", response)
        self.assertTrue(result)
        self.assertEqual(result["og_title"], "x")

    def test_chardet_none_encoding_no_crash(self):
        content = b"<html><head><title>hi</title></head></html>"
        response = self._html_response(content)
        with patch.object(
            link_preview.chardet, "detect", return_value={"encoding": None}
        ):
            result = link_preview.get_link_preview_from_html(
                "http://8.8.8.8/", response
            )
        self.assertEqual(result["og_title"], "hi")


@tagged("post_install", "-at_install")
class TestVolumeGuestComodel(MailCommon):
    def test_guest_id_targets_mail_guest(self):
        """res.users.settings.volumes.guest_id must reference mail.guest.

        It was declared against res.partner while used everywhere with a
        mail.guest id -> FK violation (or a silent bind to an unrelated
        partner sharing the id, leaking that partner's name).
        """
        field = self.env["res.users.settings.volumes"]._fields["guest_id"]
        self.assertEqual(field.comodel_name, "mail.guest")

    def test_set_volume_for_guest_persists(self):
        settings = self.env["res.users.settings"]._find_or_create_for_user(
            self.env.user
        )
        guest = self.env["mail.guest"].create({"name": "Vol Guest"})
        settings.set_volume_setting(False, 0.7, guest_id=guest.id)
        volume = settings.volume_settings_ids.filtered(lambda v: v.guest_id == guest)
        self.assertEqual(len(volume), 1)
        self.assertEqual(volume.volume, 0.7)
        self.assertFalse(volume.partner_id)


@tagged("post_install", "-at_install")
class TestAliasCheckUnique(MailCommon):
    def test_check_unique_incoherent_lists_raises_valueerror(self):
        """The coherency guard must raise its intended ValueError, not crash.

        alias_names may hold False and alias_domains is a plain list, so the old
        ', '.join(alias_names) / alias_domains.mapped('name') both raised and
        masked the real error.
        """
        domain = self.env["mail.alias.domain"].search([], limit=1)
        self.assertTrue(domain, "test setup expects at least one alias domain")
        with self.assertRaises(ValueError):
            # 2 names vs 1 domain, and a False name to exercise the join.
            self.env["mail.alias"]._check_unique(["valid", False], [domain])


@tagged("post_install", "-at_install")
class TestBounceParsing(MailCommon):
    def test_malformed_multipart_report_bounce_no_crash(self):
        """A malformed multipart/report bounce with an empty payload must not
        crash message parsing.

        email_part.get_payload()[0] raised IndexError (reproduced end-to-end at
        mail_thread.py) and propagated out of message_process, losing the whole
        inbound message (deleted on POP for POP servers).
        """
        import email
        import email.policy

        raw = (
            b"From: MAILER-DAEMON@example.com\r\n"
            b"To: catchall@example.com\r\n"
            b"Subject: Undelivered Mail Returned to Sender\r\n"
            b"Content-Type: multipart/report; report-type=delivery-status;"
            b' boundary="b"\r\n'
            b"MIME-Version: 1.0\r\n"
            b"\r\n"
            b"--b--\r\n"  # boundary closes immediately: no body parts
        )
        msg = email.message_from_bytes(raw, policy=email.policy.SMTP)
        message_dict = {
            "email_from": "mailer-daemon@example.com",
            "to": "catchall@example.com",
            "body": "",
        }
        # Must return a dict (bounce info), not raise IndexError.
        res = self.env["mail.thread"]._message_parse_extract_bounce(msg, message_dict)
        self.assertIsInstance(res, dict)
