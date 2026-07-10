import email.policy
import logging
import smtplib
from email.message import EmailMessage
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_mail_server import MailDeliveryError

# Path of the model module, used to mute its logger around tested paths.
_IR_MAIL_SERVER_LOGGER = "odoo.addons.base.models.ir_mail_server"


@tagged("post_install", "-at_install")
class TestMailServerArchiveAndHeaders(TransactionCase):
    """Cover the ir.mail_server archive guard (write) and the anti-spoofing
    header rewrite (_alter_message__). Audit findings MS-T1, MS-T2, MS-L3."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]
        # Names sort differently from creation order, so error-message ordering
        # by display_name can be asserted.
        cls.server_b, cls.server_a, cls.server_c = cls.IrMailServer.create(
            [
                {
                    "name": "Bravo Server",
                    "smtp_host": "smtp_host",
                    "smtp_encryption": "none",
                    "from_filter": "bravo.example.com",
                },
                {
                    "name": "Alpha Server",
                    "smtp_host": "smtp_host",
                    "smtp_encryption": "none",
                    "from_filter": "alpha.example.com",
                },
                {
                    "name": "Charlie Server",
                    "smtp_host": "smtp_host",
                    "smtp_encryption": "none",
                    "from_filter": "charlie.example.com",
                },
            ]
        )

    # ------------------------------------------------------------------
    # MS-T1: write() archive guard
    # ------------------------------------------------------------------

    def test_smtp_connection_test_disabled_send_raises_clean_error(self):
        """With _disable_send() active, _connect__ returns None and
        test_smtp_connection must raise a clear UserError, not an AttributeError
        wrapped in a misleading 'Connection Test Failed' message."""
        self.assertTrue(self.IrMailServer._disable_send())
        with self.assertRaises(UserError) as ctx:
            self.server_a.test_smtp_connection()
        self.assertIn("outgoing emails are disabled", str(ctx.exception))

    def test_archive_unused_server_succeeds(self):
        """In base, _active_usages_compute returns {} so archiving always works."""
        # Sanity: the base implementation reports no usage.
        self.assertEqual(self.IrMailServer._active_usages_compute(), {})
        self.server_a.active = True
        self.server_a.write({"active": False})
        self.assertFalse(self.server_a.active)

    def test_archive_non_active_write_skips_usage_check(self):
        """A write that does not flip active to False never consults usages.

        The guard only runs on explicit archive, so writing an unrelated field
        on an in-use server still goes through.
        """
        usages = {self.server_a.id: ["Some usage"]}
        with patch.object(
            type(self.IrMailServer),
            "_active_usages_compute",
            lambda self: usages,
        ):
            # Not setting active -> guard short-circuits, write succeeds.
            self.server_a.write({"name": "Alpha Renamed"})
        self.assertEqual(self.server_a.name, "Alpha Renamed")
        self.assertTrue(self.server_a.active)

    @mute_logger(_IR_MAIL_SERVER_LOGGER)
    def test_archive_single_used_server_message(self):
        """Archiving one in-use server raises the singular-form error message."""
        usages = {self.server_a.id: ["Used by alias catchall"]}
        with patch.object(
            type(self.IrMailServer),
            "_active_usages_compute",
            lambda self: usages,
        ):
            with self.assertRaises(UserError) as ctx:
                self.server_a.write({"active": False})
        message = str(ctx.exception)
        # Singular wording, server name and usage detail are present.
        self.assertIn("You cannot archive this Outgoing Mail Server", message)
        self.assertIn("Alpha Server", message)
        self.assertIn("- Used by alias catchall", message)
        # The single-server branch must NOT use the "Dedicated Outgoing Mail
        # Server" per-server header (that is only for the multi-server branch).
        self.assertNotIn("(Dedicated Outgoing Mail Server)", message)
        # The write was blocked: the server stays active.
        self.assertTrue(self.server_a.active)

    @mute_logger(_IR_MAIL_SERVER_LOGGER)
    def test_archive_multiple_used_servers_message_and_ordering(self):
        """Archiving several in-use servers raises the plural-form message,
        with servers and detail lines ordered by display_name."""
        servers = self.server_b | self.server_a | self.server_c
        usages = {
            self.server_a.id: ["Alpha usage"],
            self.server_b.id: ["Bravo usage"],
            self.server_c.id: ["Charlie usage"],
        }
        with patch.object(
            type(self.IrMailServer),
            "_active_usages_compute",
            lambda self: usages,
        ):
            with self.assertRaises(UserError) as ctx:
                servers.write({"active": False})
        message = str(ctx.exception)
        # Plural wording is used for multiple servers.
        self.assertIn("You cannot archive these Outgoing Mail Servers", message)
        # Each server carries the dedicated-server per-server header line.
        self.assertIn("Alpha Server (Dedicated Outgoing Mail Server):", message)
        self.assertIn("Bravo Server (Dedicated Outgoing Mail Server):", message)
        self.assertIn("Charlie Server (Dedicated Outgoing Mail Server):", message)
        # The header server list is sorted by display_name: Alpha, Bravo, Charlie.
        self.assertLess(message.index("Alpha Server"), message.index("Bravo Server"))
        self.assertLess(message.index("Bravo Server"), message.index("Charlie Server"))
        # Detail lines follow the same ordering as their owning servers.
        self.assertLess(message.index("Alpha usage"), message.index("Bravo usage"))
        self.assertLess(message.index("Bravo usage"), message.index("Charlie usage"))
        self.assertTrue(all(servers.mapped("active")))

    # ------------------------------------------------------------------
    # MS-T2: _alter_message__ anti-spoofing header build
    # ------------------------------------------------------------------

    def _make_message(self):
        """Build a minimal SMTP-policy EmailMessage for header-rewrite tests."""
        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = "sender@example.com"
        message["Subject"] = "Subject"
        return message

    def test_alter_message_x_msg_to_add_empty_to(self):
        """With no original To, X-Msg-To-Add yields a clean To (just the added
        address, no leading ', '). Refutes the MS-L3 leading-comma claim.
        """
        message = self._make_message()
        message["X-Msg-To-Add"] = "added@example.com"
        # smtp_from equals From so the From header is left untouched.
        self.IrMailServer._alter_message__(
            message, "sender@example.com", ["added@example.com"]
        )
        self.assertEqual(message["To"], "added@example.com")
        # The control header is scrubbed afterwards.
        self.assertIsNone(message["X-Msg-To-Add"])

    def test_alter_message_x_msg_to_add_dedupes_against_existing_to(self):
        """X-Msg-To-Add appends only the addresses not already in To, and with a
        non-empty original To there is no leading comma."""
        message = self._make_message()
        message["To"] = "keep@example.com"
        # 'keep@example.com' is already present and must be filtered out.
        message["X-Msg-To-Add"] = "keep@example.com, extra@example.com"
        self.IrMailServer._alter_message__(
            message, "sender@example.com", ["keep@example.com"]
        )
        self.assertEqual(message["To"], "keep@example.com, extra@example.com")

    def test_alter_message_x_forge_to_overrides_and_scrubs_headers(self):
        """X-Forge-To replaces the To header entirely and all control headers
        (Bcc, X-Forge-To, X-Msg-To-Add) are removed."""
        message = self._make_message()
        message["To"] = "original@example.com"
        message["Bcc"] = "hidden@example.com"
        message["X-Forge-To"] = "forged@example.com"
        message["X-Msg-To-Add"] = "ignored@example.com"
        self.IrMailServer._alter_message__(
            message, "sender@example.com", ["forged@example.com"]
        )
        # X-Forge-To wins over the original To (and short-circuits X-Msg-To-Add).
        self.assertEqual(message["To"], "forged@example.com")
        # Anti-spoofing scrubbing removed every control header and the Bcc.
        self.assertIsNone(message["Bcc"])
        self.assertIsNone(message["X-Forge-To"])
        self.assertIsNone(message["X-Msg-To-Add"])
        # From was rewritten to the provided smtp_from since it differed.
        self.assertEqual(message["From"], "sender@example.com")


class _FailingSMTPSession:
    """SMTP session double whose delivery always fails.

    ``from_filter``/``smtp_from`` mirror the ``(False, False)`` defaults of
    ``_read_session_context`` for a session that was never stashed.
    """

    from_filter = False
    smtp_from = False

    def send_message(self, message, smtp_from, smtp_to_list):
        raise smtplib.SMTPDataError(554, b"5.7.1 rejected")


@tagged("post_install", "-at_install")
class TestMailServerSendFailureObservability(TransactionCase):
    """``send_email`` delivery failures must be observable: logged at WARNING
    with the SMTP traceback, and the ``MailDeliveryError`` must chain the root
    cause (``from e``) while keeping its rendered message (the ``mail.mail``
    failure_reason) intact."""

    def _make_message(self):
        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = "sender@example.com"
        message["To"] = "recipient@example.com"
        message["Subject"] = "Subject"
        return message

    def test_send_email_failure_warns_and_chains(self):
        IrMailServer = self.env["ir.mail_server"]
        with (
            # _disable_send() short-circuits delivery in test mode; force the
            # real send path so the failure branch is exercised.
            patch.object(
                type(IrMailServer), "_disable_send", classmethod(lambda cls: False)
            ),
            self.assertLogs(_IR_MAIL_SERVER_LOGGER, level="WARNING") as capture,
            self.assertRaises(MailDeliveryError) as ctx,
        ):
            IrMailServer.send_email(
                self._make_message(), smtp_session=_FailingSMTPSession()
            )

        # The exception chain carries the root SMTP error (not `from None`).
        self.assertIsInstance(ctx.exception.__cause__, smtplib.SMTPDataError)
        # The rendered message (mail.mail failure_reason) is unchanged: short
        # human message, then the detailed delivery report.
        rendered = str(ctx.exception)
        self.assertTrue(rendered.startswith("Mail Delivery Failed\n"))
        self.assertIn("Mail delivery failed via SMTP server 'unknown'", rendered)
        self.assertIn("SMTPDataError", rendered)
        # Logged at WARNING with the traceback attached (exc_info=True).
        record = next(
            r for r in capture.records if "Mail delivery failed" in r.getMessage()
        )
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIsNotNone(record.exc_info)


@tagged("post_install", "-at_install")
class TestMailServerOnchangeEncryption(TransactionCase):
    """``_onchange_encryption`` rewrites ``smtp_port`` only when it still holds
    the default of the mode being left (25 or 465); custom ports survive a
    toggle."""

    def _new_server(self, encryption, port):
        return self.env["ir.mail_server"].new(
            {
                "name": "Onchange Server",
                "smtp_host": "smtp_host",
                "smtp_encryption": encryption,
                "smtp_port": port,
            }
        )

    def test_default_port_follows_encryption(self):
        """Default ports keep tracking the encryption mode: 25 <-> 465."""
        server = self._new_server("none", 25)
        server.smtp_encryption = "ssl"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 465)
        server.smtp_encryption = "none"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 25)
        # The strict variants behave like their plain counterparts.
        server.smtp_encryption = "ssl_strict"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 465)
        server.smtp_encryption = "starttls_strict"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 25)

    def test_custom_port_survives_toggle(self):
        """A custom port (e.g. 2525) is never clobbered by the onchange."""
        server = self._new_server("none", 2525)
        server.smtp_encryption = "ssl"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 2525)
        server.smtp_encryption = "starttls"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 2525)

    def test_starttls_submission_port_survives_ssl_toggle(self):
        """587 (STARTTLS submission) is not a mode default: toggling to SSL
        and back must leave it untouched."""
        server = self._new_server("starttls", 587)
        server.smtp_encryption = "ssl_strict"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 587)
        server.smtp_encryption = "starttls"
        server._onchange_encryption()
        self.assertEqual(server.smtp_port, 587)
