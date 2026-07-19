import base64
import email.message
import email.policy
import smtplib
import ssl
from collections import Counter
from unittest.mock import patch

import psycopg.errors

from odoo.exceptions import UserError
from odoo.tests import tagged, users
from odoo.tests.common import TransactionCase
from odoo.tools import config, mute_logger

from odoo.addons.base.models.ir_mail_server import (
    MailDeliveryException,
    OutgoingEmailError,
)
from odoo.addons.base.tests import mail_examples
from odoo.addons.base.tests.common import MockSmtplibCase


def _generate_self_signed_cert(common_name="smtp.example.com"):
    """Return ``(cert_pem, key_pem)`` bytes for a fresh self-signed RSA cert,
    so the SSL-context builders can run without a live SMTP server or fixtures.
    """
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


class _FakeSMTP:
    """SMTP stub"""

    def __init__(self):
        self.messages = []
        self.from_filter = "example.com"

    # Python 3 before 3.7.4
    def sendmail(
        self,
        smtp_from,
        smtp_to_list,
        message_str,
        mail_options=(),
        rcpt_options=(),
    ):
        self.messages.append(message_str)

    # Python 3.7.4+
    def send_message(
        self, message, smtp_from, smtp_to_list, mail_options=(), rcpt_options=()
    ):
        self.messages.append(message.as_string())


@tagged("mail_server")
class EmailConfigCase(TransactionCase):
    @patch.dict(config.options, {"email_from": "settings@example.com"})
    def test_default_email_from(self):
        """Email from setting is respected and comes from configuration."""
        message = self.env["ir.mail_server"]._build_email__(
            False,
            "recipient@example.com",
            "Subject",
            "The body of an email",
        )
        self.assertEqual(message["From"], "settings@example.com")

    def test_build_email_missing_from_raises_coded_error(self):
        """No resolvable sender must raise an OutgoingEmailError with a stable
        ``.code`` (NO_FOUND_FROM), which mail.mail uses to classify failures.
        Regression: these were plain UserError, degrading classification to
        'unknown'.
        """
        IrMailServer = self.env["ir.mail_server"]
        with patch.dict(config.options, {"email_from": False}):
            with self.assertRaises(OutgoingEmailError) as capture:
                IrMailServer._build_email__(
                    False, "recipient@example.com", "Subject", "Body"
                )
        self.assertEqual(capture.exception.code, IrMailServer.NO_FOUND_FROM)

    def test_build_email_attachment_malformed_mimetype(self):
        """A mimetype with extra slashes ("application/pdf/x") must be split on
        the first '/' only and must not crash attachment handling."""
        message = self.env["ir.mail_server"]._build_email__(
            "sender@example.com",
            "recipient@example.com",
            "Subject",
            "Body",
            attachments=[("weird.bin", b"data", "application/pdf/x")],
        )
        attachments = [
            part
            for part in message.walk()
            if part.get_content_disposition() == "attachment"
        ]
        # The point is that building did not raise ValueError on the extra
        # slash; the attachment itself is preserved.
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "weird.bin")

    def test_build_email_headers_override_standard_headers(self):
        """A ``headers`` entry must *override* an already-set standard header,
        not append a duplicate. Under EmailMessage/SMTP_POLICY singleton headers
        cap at one occurrence, so a plain append raised ValueError and aborted
        the send (reachable via the free-form ``mail.mail.headers`` field).
        """
        IrMailServer = self.env["ir.mail_server"]
        for header, override in [
            ("Subject", "Overridden Subject"),
            ("Reply-To", "boss@example.com"),
            ("From", "override@example.com"),
            ("Message-Id", "<pinned@example.com>"),
        ]:
            message = IrMailServer._build_email__(
                "sender@example.com",
                "recipient@example.com",
                "Original Subject",
                "Body",
                reply_to="orig-reply@example.com",
                headers={header: override},
            )
            self.assertEqual(
                message.get_all(header),
                [override],
                f"{header} from headers must replace, exactly once",
            )

    def test_build_email_rejects_header_injection(self):
        """MS-T3: CR/LF in a header value or name must raise (no header smuggling).

        The defense lives in CPython's ``email.policy``
        (``verify_generated_headers``, preserved by the cloned no-fold policy);
        this catches a future policy/clone change that disables it.
        """
        IrMailServer = self.env["ir.mail_server"]

        # A CR/LF in the Subject must not smuggle an extra Bcc header.
        with self.assertRaises(ValueError):
            IrMailServer._build_email__(
                "sender@example.com",
                "recipient@example.com",
                "Subject\r\nBcc: attacker@example.com",
                "Body",
            )

        # A CR/LF inside a user-supplied header value must also raise.
        with self.assertRaises(ValueError):
            IrMailServer._build_email__(
                "sender@example.com",
                "recipient@example.com",
                "Subject",
                "Body",
                headers={"X-Custom": "value\r\nBcc: attacker@example.com"},
            )

        # A CR/LF (or ':') in a header name must raise as well.
        with self.assertRaises(ValueError):
            IrMailServer._build_email__(
                "sender@example.com",
                "recipient@example.com",
                "Subject",
                "Body",
                headers={"X-Foo\r\nBcc: attacker@example.com": "v"},
            )


@tagged("mail_server")
class TestIrMailServer(TransactionCase, MockSmtplibCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "mail.default.from_filter", False
        )
        cls._init_mail_servers()

    def test_assert_base_values(self):
        self.assertFalse(self.env["ir.mail_server"]._get_default_bounce_address())
        self.assertFalse(self.env["ir.mail_server"]._get_default_from_address())

    def test_send_email_delivery_failure_reason_is_readable(self):
        """A delivery failure (send_message raising) must surface a clean
        multi-line message, never a Python tuple repr: ``mail.mail`` stores
        ``str(exc)`` verbatim into the admin-visible ``failure_reason``.
        """
        IrMailServer = self.env["ir.mail_server"]
        message = self._build_email("admin@example.com")

        class _RaisingSession:
            from_filter = False
            smtp_from = False
            _host = "smtp.probe.example.com"

            def send_message(self, *args, **kwargs):
                raise smtplib.SMTPDataError(554, b"5.7.1 rejected")

        with (
            patch.object(type(IrMailServer), "_disable_send", lambda _: False),
            mute_logger("odoo.addons.base.models.ir_mail_server"),
            self.assertRaises(MailDeliveryException) as capture,
        ):
            IrMailServer.send_email(message, smtp_session=_RaisingSession())

        rendered = str(capture.exception)
        # Regression: the two-arg MailDeliveryError used to render as
        # "('Mail Delivery Failed', '...')" — a tuple repr — when str()'d.
        self.assertNotIn("('", rendered)
        self.assertNotIn("', '", rendered)
        self.assertIn("smtp.probe.example.com", rendered)
        self.assertIn("SMTPDataError", rendered)

    def test_find_mail_server_parses_each_from_filter_once(self):
        """``_find_mail_server`` must not re-split the same ``from_filter``
        repeatedly across its match passes (perf regression guard)."""
        # ``mail_servers`` is passed explicitly below, so ``_find_mail_server``
        # never searches — these probe servers are the entire candidate set.
        IrMailServer = self.env["ir.mail_server"]
        servers = IrMailServer.create(
            [
                {
                    "name": f"probe{i}",
                    "smtp_host": f"host{i}.example.com",
                    "smtp_encryption": "none",
                    "smtp_authentication": "login",
                    "from_filter": f"probe{i}.example.com",
                }
                for i in range(5)
            ]
        )

        seen = []
        original = type(IrMailServer)._parse_from_filter

        def counting(self, from_filter):
            seen.append(from_filter)
            return original(self, from_filter)

        with patch.object(type(IrMailServer), "_parse_from_filter", counting):
            IrMailServer.sudo()._find_mail_server(
                "nobody@nomatch.example.org", mail_servers=servers
            )

        repeats = {ff: n for ff, n in Counter(seen).items() if n > 1}
        self.assertFalse(repeats, f"from_filter re-parsed: {repeats}")

    def test_bpo_34424_35805(self):
        """Ensure all email sent are bpo-34424 and bpo-35805 free"""
        fake_smtp = _FakeSMTP()
        msg = email.message.EmailMessage(policy=email.policy.SMTP)
        msg["From"] = '"Joé Doe" <joe@example.com>'
        msg["To"] = '"Joé Doe" <joe@example.com>'

        # Message-Id & References fields longer than 77 chars (bpo-35805)
        msg["Message-Id"] = (
            "<929227342217024.1596730490.324691772460938-example-30661-some.reference@test-123.example.com>"
        )
        msg["References"] = (
            "<345227342212345.1596730777.324691772483620-example-30453-other.reference@test-123.example.com>"
        )

        msg_on_the_wire = self._send_email(msg, fake_smtp)
        self.assertEqual(
            msg_on_the_wire,
            "From: =?utf-8?q?Jo=C3=A9?= Doe <joe@example.com>\r\n"
            "To: =?utf-8?q?Jo=C3=A9?= Doe <joe@example.com>\r\n"
            "Message-Id: <929227342217024.1596730490.324691772460938-example-30661-some.reference@test-123.example.com>\r\n"
            "References: <345227342212345.1596730777.324691772483620-example-30453-other.reference@test-123.example.com>\r\n"
            "\r\n",
        )

    def test_content_alternative_correct_order(self):
        """
        RFC-1521 7.2.3. The Multipart/alternative subtype
        > the alternatives appear in an order of increasing faithfulness
        > to the original content. In general, the best choice is the
        > LAST part of a type supported by the recipient system's local
        > environment.

        Also, the MIME-Version header should be present in BOTH the
        envelope AND the parts
        """
        fake_smtp = _FakeSMTP()
        msg = self._build_email(
            "test@example.com", body="<p>Hello world</p>", subtype="html"
        )
        msg_on_the_wire = self._send_email(msg, fake_smtp)

        self.assertGreater(
            msg_on_the_wire.index("text/html"),
            msg_on_the_wire.index("text/plain"),
            "The html part should be preferred (=appear after) to the text part",
        )
        self.assertEqual(
            msg_on_the_wire.count("==============="),
            2 + 2,  # +2 for the header and the footer
            "There should be 2 parts: one text and one html",
        )
        self.assertEqual(
            msg_on_the_wire.count("MIME-Version: 1.0"),
            3,
            "There should be 3 headers MIME-Version: one on the enveloppe, one on the html part, one on the text part",
        )

    def test_content_mail_body(self):
        bodies = [
            "content",
            "<p>content</p>",
            '<head><meta content="text/html; charset=utf-8" http-equiv="Content-Type"></head><body><p>content</p></body>',
            mail_examples.MISC_HTML_SOURCE,
            mail_examples.QUOTE_THUNDERBIRD_HTML,
        ]
        expected_list = [
            "content",
            "content",
            "content",
            "test1\n*test2*\ntest3\ntest4\ntest5\ntest6   test7\ntest8    test9\ntest10\ntest11\ntest12\ngoogle [1]\ntest link [2]\n\n\n[1] http://google.com\n[2] javascript:alert('malicious code')",
            "On 01/05/2016 10:24 AM, Raoul\nPoilvache wrote:\n\n* Test reply. The suite. *\n\n--\nRaoul Poilvache\n\nTop cool !!!\n\n--\nRaoul Poilvache",
        ]
        for body, expected in zip(bodies, expected_list, strict=False):
            message = self.env["ir.mail_server"]._build_email__(
                "john.doe@from.example.com",
                "destinataire@to.example.com",
                body=body,
                subject="Subject",
                subtype="html",
            )
            body_alternative = None
            for part in message.walk():
                if part.get_content_maintype() == "multipart":
                    continue  # skip container
                if part.get_content_type() == "text/plain":
                    if not part.get_payload():
                        continue
                    # remove ending new lines as it just adds noise
                    body_alternative = part.get_content().rstrip("\n")
            self.assertEqual(body_alternative, expected)

    @mute_logger("odoo.db")
    def test_mail_server_auth_cert_requires_tls(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.env["ir.mail_server"].create(
                {
                    "name": "test",
                    "smtp_host": "smtp_host",
                    "smtp_encryption": "none",
                    "smtp_authentication": "certificate",
                }
            )

    @users("admin")
    def test_mail_server_get_test_email_from(self):
        """Test the email used to test the mail server connection. Check
        from_filter parsing / default fallback value."""
        self.env.user.email = "mitchell.admin@example.com"
        test_server = self.env["ir.mail_server"].create(
            {
                "from_filter": "example_2.com, example_3.com",
                "name": "Test Server",
                "smtp_host": "smtp_host",
                "smtp_encryption": "none",
            }
        )
        for from_filter, expected_test_email in zip(
            [
                "example_2.com, example_3.com",
                "dummy.com, full_email@example_2.com, dummy2.com",
                # fallback on user's email
                " ",
                ",",
                False,
            ],
            [
                "noreply@example_2.com",
                "full_email@example_2.com",
                self.env.user.email,
                self.env.user.email,
                self.env.user.email,
            ],
            strict=False,
        ):
            with self.subTest(from_filter=from_filter):
                test_server.from_filter = from_filter
                email_from = test_server._get_test_email_from()
                self.assertEqual(email_from, expected_test_email)

    def test_mail_server_match_from_filter(self):
        """Test the from_filter field on the "ir.mail_server"."""
        # Should match
        tests = [
            ("admin@mail.example.com", "mail.example.com"),
            ("admin@mail.example.com", "mail.EXAMPLE.com"),
            ("admin@mail.example.com", "admin@mail.example.com"),
            ("admin@mail.example.com", False),
            (
                '"fake@test.mycompany.com" <admin@mail.example.com>',
                "mail.example.com",
            ),
            (
                '"fake@test.mycompany.com" <ADMIN@mail.example.com>',
                "mail.example.com",
            ),
            (
                '"fake@test.mycompany.com" <ADMIN@mail.example.com>',
                "test.mycompany.com, mail.example.com, test2.com",
            ),
        ]
        for email_addr, from_filter in tests:
            self.assertTrue(
                self.env["ir.mail_server"]._match_from_filter(email_addr, from_filter)
            )

        # Should not match
        tests = [
            ("admin@mail.example.com", "test@mail.example.com"),
            ("admin@mail.example.com", "test.mycompany.com"),
            ("admin@mail.example.com", "mail.éxample.com"),
            ("admin@mmail.example.com", "mail.example.com"),
            ("admin@mail.example.com", "mmail.example.com"),
            (
                '"admin@mail.example.com" <fake@test.mycompany.com>',
                "mail.example.com",
            ),
            (
                '"fake@test.mycompany.com" <ADMIN@mail.example.com>',
                "test.mycompany.com, wrong.mail.example.com, test3.com",
            ),
        ]
        for email_addr, from_filter in tests:
            self.assertFalse(
                self.env["ir.mail_server"]._match_from_filter(email_addr, from_filter)
            )

    @mute_logger("odoo.models.unlink")
    def test_mail_server_priorities(self):
        """Test if we choose the right mail server to send an email. Simulates
        simple Odoo DB so we have to spoof the FROM otherwise we cannot send
        any email."""
        for email_from, (expected_mail_server, expected_email_from) in zip(
            [
                "specific_user@test.mycompany.com",
                "unknown_email@test.mycompany.com",
                # no notification set, must be forced to spoof the FROM
                '"Test" <test@unknown_domain.com>',
            ],
            [
                (self.mail_server_user, "specific_user@test.mycompany.com"),
                (self.mail_server_domain, "unknown_email@test.mycompany.com"),
                (self.mail_server_default, '"Test" <test@unknown_domain.com>'),
            ],
            strict=False,
        ):
            with self.subTest(email_from=email_from):
                mail_server, mail_from = self.env["ir.mail_server"]._find_mail_server(
                    email_from=email_from
                )
                self.assertEqual(mail_server, expected_mail_server)
                self.assertEqual(mail_from, expected_email_from)

    @mute_logger("odoo.models.unlink")
    def test_mail_server_send_email(self):
        """Test main 'send_email' usage: check mail_server choice based on from
        filters, encapsulation, spoofing."""
        IrMailServer = self.env["ir.mail_server"]

        for mail_from, (
            expected_smtp_from,
            expected_msg_from,
            expected_mail_server,
        ) in zip(
            [
                "specific_user@test.mycompany.com",
                '"Name" <test@unknown_domain.com>',
                "test@unknown_domain.com",
                '"Name" <unknown_name@test.mycompany.com>',
            ],
            [
                # A mail server is configured for the email
                (
                    "specific_user@test.mycompany.com",
                    "specific_user@test.mycompany.com",
                    self.mail_server_user,
                ),
                # No mail server are configured for the email address, so it will use the
                # notifications email instead and encapsulate the old email
                (
                    "test@unknown_domain.com",
                    '"Name" <test@unknown_domain.com>',
                    self.mail_server_default,
                ),
                # same situation, but the original email has no name part
                (
                    "test@unknown_domain.com",
                    "test@unknown_domain.com",
                    self.mail_server_default,
                ),
                # A mail server is configured for the entire domain name, so we can use the bounce
                # email address because the mail server supports it
                (
                    "unknown_name@test.mycompany.com",
                    '"Name" <unknown_name@test.mycompany.com>',
                    self.mail_server_domain,
                ),
            ],
            strict=False,
        ):
            # test with and without providing an SMTP session, which should not impact test
            for provide_smtp in [False, True]:
                with self.subTest(mail_from=mail_from, provide_smtp=provide_smtp):
                    with self.mock_smtplib_connection():
                        if provide_smtp:
                            smtp_session = IrMailServer._connect__(smtp_from=mail_from)
                            message = self._build_email(mail_from=mail_from)
                            IrMailServer.send_email(message, smtp_session=smtp_session)
                        else:
                            message = self._build_email(mail_from=mail_from)
                            IrMailServer.send_email(message)

                    self.connect_mocked.assert_called_once()
                    self.assertEqual(len(self.emails), 1)
                    self.assertSMTPEmailsSent(
                        smtp_from=expected_smtp_from,
                        message_from=expected_msg_from,
                        mail_server=expected_mail_server,
                    )

        # remove the notification server
        # so <notifications.test@test.mycompany.com> will use the <test.mycompany.com> mail server
        # The mail server configured for the notifications email has been removed
        # but we can still use the mail server configured for test.mycompany.com
        # and so we will be able to use the bounce address
        # because we use the mail server for "test.mycompany.com"
        self.mail_server_notification.unlink()
        for provide_smtp in [False, True]:
            with self.mock_smtplib_connection():
                if provide_smtp:
                    smtp_session = IrMailServer._connect__(
                        smtp_from='"Name" <test@unknown_domain.com>'
                    )
                    message = self._build_email(
                        mail_from='"Name" <test@unknown_domain.com>'
                    )
                    IrMailServer.send_email(message, smtp_session=smtp_session)
                else:
                    message = self._build_email(
                        mail_from='"Name" <test@unknown_domain.com>'
                    )
                    IrMailServer.send_email(message)

            self.connect_mocked.assert_called_once()
            self.assertEqual(len(self.emails), 1)
            self.assertSMTPEmailsSent(
                smtp_from="test@unknown_domain.com",
                message_from='"Name" <test@unknown_domain.com>',
                from_filter=False,
            )

    @mute_logger("odoo.models.unlink", "odoo.addons.base.models.ir_mail_server")
    def test_mail_server_send_email_context_force(self):
        """Allow to force notifications_email / bounce_address from context
        to allow higher-level apps to send values until end of mail stack
        without hacking too much models."""
        # custom notification / bounce email from context
        context_server = self.env["ir.mail_server"].create(
            {
                "from_filter": "context.example.com",
                "name": "context",
                "smtp_host": "test",
            }
        )
        IrMailServer = self.env["ir.mail_server"].with_context(
            domain_notifications_email="notification@context.example.com",
            domain_bounce_address="bounce@context.example.com",
        )
        with self.mock_smtplib_connection():
            mail_server, smtp_from = IrMailServer._find_mail_server(
                email_from='"Name" <test@unknown_domain.com>'
            )
            self.assertEqual(mail_server, context_server)
            self.assertEqual(smtp_from, "notification@context.example.com")
            smtp_session = IrMailServer._connect__(smtp_from=smtp_from)
            message = self._build_email(mail_from='"Name" <test@unknown_domain.com>')
            IrMailServer.send_email(message, smtp_session=smtp_session)

        self.assertEqual(len(self.emails), 1)
        self.assertSMTPEmailsSent(
            smtp_from="bounce@context.example.com",
            message_from='"Name" <notification@context.example.com>',
            from_filter=context_server.from_filter,
        )

        # miss-configured database, no mail servers from filter
        # match the user / notification email
        self.env["ir.mail_server"].search([]).from_filter = "random.domain"
        with self.mock_smtplib_connection():
            message = self._build_email(mail_from="specific_user@test.com")
            IrMailServer.with_context(
                domain_notifications_email="test@custom_domain.com"
            ).send_email(message)

        self.connect_mocked.assert_called_once()
        self.assertSMTPEmailsSent(
            smtp_from="test@custom_domain.com",
            message_from='"specific_user" <test@custom_domain.com>',
            from_filter="random.domain",
        )

    @mute_logger("odoo.models.unlink")
    def test_mail_server_send_email_IDNA(self):
        """Test that the mail from / recipient envelop are encoded using IDNA"""
        with self.mock_smtplib_connection():
            message = self._build_email(mail_from="test@ééééééé.com")
            self.env["ir.mail_server"].send_email(message)

        self.assertEqual(len(self.emails), 1)
        self.assertSMTPEmailsSent(
            smtp_from="test@xn--9caaaaaaa.com",
            smtp_to_list=["dest@xn--example--i1a.com"],
            message_from="test@=?utf-8?b?w6nDqcOpw6nDqcOpw6k=?=.com",
            from_filter=False,
        )

    @mute_logger("odoo.models.unlink", "odoo.addons.base.models.ir_mail_server")
    @patch.dict(
        config.options,
        {
            "from_filter": "dummy@example.com, test.mycompany.com, dummy2@example.com",
            "smtp_server": "example.com",
        },
    )
    def test_mail_server_config_bin(self):
        """Test the configuration provided in the odoo-bin arguments. This config
        is used when no mail server exists. Test with and without giving a
        pre-configured SMTP session, should not impact results.

        Also check "mail.default.from_filter" parameter usage that should overwrite
        odoo-bin argument "--from-filter".
        """
        IrMailServer = self.env["ir.mail_server"]

        # Remove all mail server so we will use the odoo-bin arguments
        IrMailServer.search([]).unlink()
        self.assertFalse(IrMailServer.search([]))

        for mail_from, (expected_smtp_from, expected_msg_from) in zip(
            [
                # inside "from_filter" domain
                "specific_user@test.mycompany.com",
                '"Formatted Name" <specific_user@test.mycompany.com>',
                '"Formatted Name" <specific_user@test.MYCOMPANY.com>',
                '"Formatted Name" <SPECIFIC_USER@test.mycompany.com>',
                # outside "from_filter" domain
                "test@unknown_domain.com",
                '"Formatted Name" <test@unknown_domain.com>',
            ],
            [
                # inside "from_filter" domain: no rewriting
                (
                    "specific_user@test.mycompany.com",
                    "specific_user@test.mycompany.com",
                ),
                (
                    "specific_user@test.mycompany.com",
                    '"Formatted Name" <specific_user@test.mycompany.com>',
                ),
                (
                    "specific_user@test.MYCOMPANY.com",
                    '"Formatted Name" <specific_user@test.MYCOMPANY.com>',
                ),
                (
                    "SPECIFIC_USER@test.mycompany.com",
                    '"Formatted Name" <SPECIFIC_USER@test.mycompany.com>',
                ),
                # outside "from_filter" domain: spoofing, as fallback email can be found
                ("test@unknown_domain.com", "test@unknown_domain.com"),
                (
                    "test@unknown_domain.com",
                    '"Formatted Name" <test@unknown_domain.com>',
                ),
            ],
            strict=False,
        ):
            for provide_smtp in [
                False,
                True,
            ]:  # providing smtp session should not impact test
                with self.subTest(mail_from=mail_from, provide_smtp=provide_smtp):
                    with self.mock_smtplib_connection():
                        if provide_smtp:
                            smtp_session = IrMailServer._connect__(smtp_from=mail_from)
                            message = self._build_email(mail_from=mail_from)
                            IrMailServer.send_email(message, smtp_session=smtp_session)
                        else:
                            message = self._build_email(mail_from=mail_from)
                            IrMailServer.send_email(message)

                    self.connect_mocked.assert_called_once()
                    self.assertEqual(len(self.emails), 1)
                    self.assertSMTPEmailsSent(
                        smtp_from=expected_smtp_from,
                        message_from=expected_msg_from,
                        from_filter="dummy@example.com, test.mycompany.com, dummy2@example.com",
                    )

        # for from_filter in ICP, overwrite the one from odoo-bin
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.default.from_filter", "icp.example.com"
        )

        # Use an email in the domain of the config parameter "mail.default.from_filter"
        with self.mock_smtplib_connection():
            message = self._build_email(mail_from="specific_user@icp.example.com")
            IrMailServer.send_email(message)

        self.assertSMTPEmailsSent(
            smtp_from="specific_user@icp.example.com",
            message_from="specific_user@icp.example.com",
            from_filter="icp.example.com",
        )

    @mute_logger("odoo.models.unlink")
    @patch.dict(
        config.options,
        {"from_filter": "fake.com", "smtp_server": "cli_example.com"},
    )
    def test_mail_server_config_cli(self):
        """Test the mail server configuration when the "smtp_authentication" is
        "cli". It should take the configuration from the odoo-bin argument. The
        "from_filter" of the mail server should overwrite the one set in the CLI
        arguments.
        """
        IrMailServer = self.env["ir.mail_server"]
        # should be ignored by the mail server
        self.env["ir.config_parameter"].sudo().set_param(
            "mail.default.from_filter", "fake.com"
        )

        server_other = IrMailServer.create(
            [
                {
                    "name": "Server No From Filter",
                    "smtp_host": "smtp_host",
                    "smtp_encryption": "none",
                    "smtp_authentication": "cli",
                    "from_filter": "dummy@example.com, cli_example.com, dummy2@example.com",
                }
            ]
        )

        for mail_from, (
            expected_smtp_from,
            expected_msg_from,
            expected_mail_server,
        ) in zip(
            [
                # check that the CLI server take the configuration in the odoo-bin argument
                # except the from_filter which is taken on the mail server
                "test@cli_example.com",
                # other mail servers still work
                "specific_user@test.mycompany.com",
            ],
            [
                ("test@cli_example.com", "test@cli_example.com", server_other),
                (
                    "specific_user@test.mycompany.com",
                    "specific_user@test.mycompany.com",
                    self.mail_server_user,
                ),
            ],
            strict=False,
        ):
            with self.subTest(mail_from=mail_from):
                with self.mock_smtplib_connection():
                    message = self._build_email(mail_from=mail_from)
                    IrMailServer.send_email(message)

                self.assertSMTPEmailsSent(
                    smtp_from=expected_smtp_from,
                    message_from=expected_msg_from,
                    mail_server=expected_mail_server,
                )

    def test_eml_attachment_encoding(self):
        """Test that message/rfc822 attachments are encoded using 7bit, 8bit, or binary encoding per RFC."""
        IrMailServer = self.env["ir.mail_server"]

        # Create a sample .eml file content
        eml_content = b"From: user@example.com\nTo: user2@example.com\nSubject: Test Email\n\nThis is a test email."
        attachments = [("test.eml", eml_content, "message/rfc822")]

        # Build the email with the .eml attachment
        message = IrMailServer._build_email__(
            email_from="john.doe@from.example.com",
            email_to="destinataire@to.example.com",
            subject="Subject with .eml attachment",
            body="This email contains a .eml attachment.",
            attachments=attachments,
        )

        acceptable_encodings = {"7bit", "8bit", "binary"}
        found_rfc822_part = False

        for part in message.iter_attachments():
            if part.get_content_type() == "message/rfc822":
                found_rfc822_part = True
                # Get Content-Transfer-Encoding, defaulting to '7bit' if not present (per RFC)
                encoding = part.get("Content-Transfer-Encoding", "7bit").lower()

                self.assertIn(
                    encoding,
                    acceptable_encodings,
                    f"RFC violation: message/rfc822 attachment has Content-Transfer-Encoding '{encoding}'. "
                    f"Only 7bit, 8bit, or binary encoding is permitted per RFC 2046 Section 5.2.1.",
                )

        self.assertTrue(
            found_rfc822_part,
            "No message/rfc822 attachment found in the built email",
        )

    def test_eml_message_serialization_with_non_ascii(self):
        """Ensure an email with a message/rfc822 attachment containing non-ASCII chars can be serialized."""
        IrMailServer = self.env["ir.mail_server"]

        # .eml content with non-ASCII character
        eml_content = "From: user@example.com\nTo: user2@example.com\nSubject: Test\n\nBody with é"
        attachments = [("test.eml", eml_content.encode(), "message/rfc822")]

        message = IrMailServer._build_email__(
            email_from="john.doe@from.example.com",
            email_to="destinataire@to.example.com",
            subject="Serialization test",
            body="This email contains a .eml attachment.",
            attachments=attachments,
        )

        try:
            serialized = message.as_string().encode("utf-8")
        except UnicodeEncodeError as e:
            msg = "Email with non-ASCII .eml attachment could not be serialized"
            raise AssertionError(msg) from e

        self.assertIsInstance(serialized, bytes)


@tagged("mail_server")
class TestSslContexts(TransactionCase):
    """Unit coverage for the SSL-context builders.

    These paths lean on private urllib3/pyOpenSSL internals (``PyOpenSSLContext.
    _ctx``, ``match_hostname``, …) previously only exercised by the live-SMTPD
    suite; building the contexts directly guards against an upstream change
    silently breaking outgoing TLS.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cert_pem, cls.key_pem = _generate_self_signed_cert("smtp.example.com")
        # A second, unrelated key: valid PEM but does NOT match cert_pem.
        _, cls.mismatched_key_pem = _generate_self_signed_cert("smtp.example.com")

    def _make_cert_server(self, encryption, key_pem=None):
        return self.env["ir.mail_server"].create(
            {
                "name": f"cert-{encryption}",
                "smtp_host": "smtp.example.com",
                "smtp_authentication": "certificate",
                "smtp_encryption": encryption,
                "smtp_ssl_certificate": base64.b64encode(self.cert_pem),
                "smtp_ssl_private_key": base64.b64encode(key_pem or self.key_pem),
            }
        )

    def test_ssl_context_for_encryption_modes(self):
        """Strict variants validate host+peer; lax variants encrypt only."""
        IrMailServer = self.env["ir.mail_server"]
        for encryption in ("ssl_strict", "starttls_strict"):
            ctx = IrMailServer._ssl_context_for_encryption(encryption)
            self.assertTrue(ctx.check_hostname, encryption)
            self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED, encryption)
        for encryption in ("ssl", "starttls"):
            ctx = IrMailServer._ssl_context_for_encryption(encryption)
            self.assertFalse(ctx.check_hostname, encryption)
            self.assertEqual(ctx.verify_mode, ssl.CERT_NONE, encryption)

    def test_ssl_context_from_cert_files(self):
        """A cert/key pair on disk yields a client-auth context."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "cert.pem"
            key_path = Path(tmp) / "key.pem"
            cert_path.write_bytes(self.cert_pem)
            key_path.write_bytes(self.key_pem)
            ctx = self.env["ir.mail_server"]._ssl_context_from_cert_files(
                str(cert_path), str(key_path)
            )
            self.assertEqual(type(ctx).__name__, "PyOpenSSLContext")

    def test_ssl_context_from_cert_files_strict_verifies_peer(self):
        """Strict encryption with cert/key files builds a *verifying* context.

        Regression: verify_mode was hardcoded to CERT_NONE regardless of the
        requested encryption, silently downgrading ssl_strict/starttls_strict
        to no server-certificate validation on the CLI/config path.
        """
        import tempfile
        from pathlib import Path

        from OpenSSL.SSL import VERIFY_FAIL_IF_NO_PEER_CERT, VERIFY_NONE, VERIFY_PEER

        IrMailServer = self.env["ir.mail_server"]
        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "cert.pem"
            key_path = Path(tmp) / "key.pem"
            cert_path.write_bytes(self.cert_pem)
            key_path.write_bytes(self.key_pem)
            for encryption in ("ssl_strict", "starttls_strict"):
                ctx = IrMailServer._ssl_context_from_cert_files(
                    str(cert_path), str(key_path), encryption, "smtp.example.com"
                )
                self.assertEqual(
                    ctx._ctx.get_verify_mode(),
                    VERIFY_PEER | VERIFY_FAIL_IF_NO_PEER_CERT,
                    encryption,
                )
            for encryption in (None, "none", "ssl", "starttls"):
                ctx = IrMailServer._ssl_context_from_cert_files(
                    str(cert_path), str(key_path), encryption, "smtp.example.com"
                )
                self.assertEqual(ctx._ctx.get_verify_mode(), VERIFY_NONE, encryption)

    def test_connect_cert_files_strict_encryption_verifies(self):
        """End-to-end: strict encryption + client cert/key files must reach
        smtplib with a peer-verifying pyOpenSSL context, mirroring the
        record-based certificate path."""
        import tempfile
        from pathlib import Path

        from OpenSSL.SSL import VERIFY_FAIL_IF_NO_PEER_CERT, VERIFY_PEER

        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "cert.pem"
            key_path = Path(tmp) / "key.pem"
            cert_path.write_bytes(self.cert_pem)
            key_path.write_bytes(self.key_pem)
            captured = self._capture_connect_context(
                host="smtp.example.com",
                port=465,
                encryption="ssl_strict",
                ssl_certificate=str(cert_path),
                ssl_private_key=str(key_path),
            )
            ctx = captured["ssl"]
            self.assertEqual(type(ctx).__name__, "PyOpenSSLContext")
            self.assertEqual(
                ctx._ctx.get_verify_mode(),
                VERIFY_PEER | VERIFY_FAIL_IF_NO_PEER_CERT,
            )

    def test_ssl_context_from_certificate_builds_for_all_variants(self):
        """Both strict and lax certificate transports build a context whose
        private key is validated against the certificate."""
        IrMailServer = self.env["ir.mail_server"]
        for encryption in ("starttls", "starttls_strict", "ssl", "ssl_strict"):
            server = self._make_cert_server(encryption)
            ctx = IrMailServer._ssl_context_from_certificate(server, "smtp.example.com")
            self.assertEqual(type(ctx).__name__, "PyOpenSSLContext", encryption)

    def test_ssl_context_from_certificate_key_mismatch_raises_usererror(self):
        """A private key that does not match the certificate surfaces as a
        clean UserError (via _ssl_load_error), not a raw OpenSSL error."""
        server = self._make_cert_server(
            "starttls_strict", key_pem=self.mismatched_key_pem
        )
        with self.assertRaises(UserError):
            self.env["ir.mail_server"]._ssl_context_from_certificate(
                server, "smtp.example.com"
            )

    def _capture_connect_context(self, **connect_kwargs):
        """Open a connection through the raw-parameter path and return the
        ssl context that reached smtplib (SMTP_SSL ``context=`` or the one
        passed to ``starttls``). No socket is opened.
        """
        captured = {}

        class _FakeConn:
            def __init__(self, *a, **kw):
                captured["ssl"] = kw.get("context")

            def set_debuglevel(self, *a):
                pass

            def starttls(self, context=None):
                captured["starttls"] = context

            def ehlo_or_helo_if_needed(self):
                pass

        IrMailServer = self.env["ir.mail_server"]
        with (
            patch.object(type(IrMailServer), "_disable_send", lambda _: False),
            patch("smtplib.SMTP_SSL", _FakeConn),
            patch("smtplib.SMTP", _FakeConn),
        ):
            IrMailServer._connect__(**connect_kwargs)
        return captured

    def test_connect_raw_param_strict_encryption_verifies(self):
        """Regression: strict encryption passed as a raw parameter (no mail
        server record, no client cert) must build a *verifying* context.
        Previously the context stayed None, so smtplib fell back to an
        unverified stdlib context and silently downgraded 'strict'.
        """
        captured = self._capture_connect_context(
            host="smtp.example.test", port=465, encryption="ssl_strict"
        )
        ctx = captured["ssl"]
        self.assertIsNotNone(ctx, "ssl_strict must not connect with context=None")
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

        captured = self._capture_connect_context(
            host="smtp.example.test", port=587, encryption="starttls_strict"
        )
        ctx = captured["starttls"]
        self.assertIsNotNone(ctx, "starttls_strict must not STARTTLS with context=None")
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    def test_connect_raw_param_lax_encryption_unchanged(self):
        """Lax variants stay encryption-only (no server-cert validation)."""
        captured = self._capture_connect_context(
            host="smtp.example.test", port=465, encryption="ssl"
        )
        ctx = captured["ssl"]
        self.assertFalse(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)


class TestResolveTransport(TransactionCase):
    """Direct unit coverage for _resolve_smtp_transport — the socket-free half of
    _connect__. These pin the source-precedence rules (record vs CLI/config vs
    explicit params) that used to be untestable without opening a connection.
    """

    def test_resolve_from_record(self):
        """A login mail-server record fully describes the transport."""
        IrMailServer = self.env["ir.mail_server"]
        server = IrMailServer.create(
            {
                "name": "rec",
                "smtp_host": "mail.record.test",
                "smtp_port": 2525,
                "smtp_user": "u@record.test",
                "smtp_pass": "secret",
                "smtp_encryption": "starttls_strict",
                "smtp_authentication": "login",
                "from_filter": "record.test",
            }
        )
        t = IrMailServer._resolve_smtp_transport(server)
        self.assertEqual(t.server, "mail.record.test")
        self.assertEqual(t.port, 2525)
        self.assertEqual(t.user, "u@record.test")
        self.assertEqual(t.password, "secret")
        self.assertEqual(t.encryption, "starttls_strict")
        self.assertEqual(t.from_filter, "record.test")
        self.assertEqual(t.login_server, server)
        self.assertTrue(t.ssl_context.check_hostname)  # strict -> verifying

    def test_resolve_cli_auth_record_ignores_record_transport(self):
        """A 'cli'-authenticated record contributes ONLY its from_filter; its
        host/port/user go through the CLI/config path instead."""
        IrMailServer = self.env["ir.mail_server"]
        server = IrMailServer.create(
            {
                "name": "cli",
                "smtp_host": "ignored.test",
                "smtp_port": 9999,
                "smtp_authentication": "cli",
                "from_filter": "cli.test",
            }
        )
        with patch.dict(config.options, {"smtp_server": "cli.host", "smtp_port": 25}):
            t = IrMailServer._resolve_smtp_transport(server)
        self.assertEqual(
            t.server, "cli.host", "record host must be ignored for cli auth"
        )
        self.assertEqual(t.from_filter, "cli.test", "record from_filter is still used")
        self.assertEqual(t.login_server, server)

    def test_resolve_explicit_params_win_over_config(self):
        """Explicit host/port/user beat config on the param path."""
        IrMailServer = self.env["ir.mail_server"]
        empty = IrMailServer.browse()
        with patch.dict(
            config.options, {"smtp_server": "conf.host", "smtp_user": "conf"}
        ):
            t = IrMailServer._resolve_smtp_transport(
                empty, host="explicit.host", port=1234, user="explicit"
            )
        self.assertEqual(t.server, "explicit.host")
        self.assertEqual(t.port, 1234)
        self.assertEqual(t.user, "explicit")
        self.assertFalse(t.login_server, "no record -> empty login_server")

    def test_session_context_roundtrip(self):
        """Routing context stashed on a session reads back through the typed
        accessors; a bare session (never stashed) yields the (False, False)
        default, matching the old getattr(..., False) semantics.
        """
        from odoo.addons.base.models.ir_mail_server import _SmtpSessionContext

        IrMailServer = self.env["ir.mail_server"]

        class _BareSession:
            pass

        conn = _BareSession()
        # Bare, never-stashed session -> defaults, no AttributeError.
        self.assertEqual(
            IrMailServer._read_session_context(conn),
            _SmtpSessionContext(from_filter=False, smtp_from=False),
        )
        # Round-trip through the writer/reader pair.
        IrMailServer._stash_session_context(
            conn,
            _SmtpSessionContext(from_filter="example.com", smtp_from="a@example.com"),
        )
        ctx = IrMailServer._read_session_context(conn)
        self.assertEqual(ctx.from_filter, "example.com")
        self.assertEqual(ctx.smtp_from, "a@example.com")
        # Attribute names preserved for the test doubles / external readers.
        self.assertEqual(conn.from_filter, "example.com")
        self.assertEqual(conn.smtp_from, "a@example.com")
