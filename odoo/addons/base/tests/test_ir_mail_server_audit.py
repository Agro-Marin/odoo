import base64
import email.policy
import logging
import smtplib
import tempfile
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import config, mute_logger

from odoo.addons.base.models.ir_mail_server import MailDeliveryError, OutgoingEmailError

_IR_MAIL_SERVER_LOGGER = "odoo.addons.base.models.ir_mail_server"


@tagged("post_install", "-at_install")
class TestMailServerArchiveAndHeaders(TransactionCase):
    """Cover the ir.mail_server archive guard (write) and the anti-spoofing
    header rewrite (_alter_message__). Audit findings MS-T1, MS-T2, MS-L3."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]
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
        self.assertEqual(self.IrMailServer._active_usages_compute(), {})
        self.server_a.active = True
        self.server_a.write({"active": False})
        self.assertFalse(self.server_a.active)

    @mute_logger(_IR_MAIL_SERVER_LOGGER)
    def test_archive_ignores_usages_of_servers_not_being_archived(self):
        """``_active_usages_compute`` may describe servers outside ``self``.

        Regression: any non-empty return blocked the write, raising a UserError
        that named no server and listed no usage.
        """
        usages = {self.server_c.id: ["Charlie usage"]}
        with patch.object(
            type(self.IrMailServer),
            "_active_usages_compute",
            lambda self: usages,
        ):
            self.server_a.write({"active": False})
        self.assertFalse(self.server_a.active)

    @mute_logger(_IR_MAIL_SERVER_LOGGER)
    def test_archive_single_server_message_stays_singular(self):
        """The plural form keys off the servers actually blocked, not off the
        size of the whole usage map."""
        usages = {
            self.server_a.id: ["Alpha usage"],
            self.server_b.id: ["Bravo usage"],
        }
        with patch.object(
            type(self.IrMailServer),
            "_active_usages_compute",
            lambda self: usages,
        ):
            with self.assertRaises(UserError) as ctx:
                self.server_a.write({"active": False})
        message = str(ctx.exception)
        self.assertIn("You cannot archive this Outgoing Mail Server", message)
        self.assertNotIn("Bravo", message)
        self.assertNotIn("(Dedicated Outgoing Mail Server)", message)

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
        self.assertIn("You cannot archive this Outgoing Mail Server", message)
        self.assertIn("Alpha Server", message)
        self.assertIn("- Used by alias catchall", message)
        self.assertNotIn("(Dedicated Outgoing Mail Server)", message)
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
        self.assertIn("You cannot archive these Outgoing Mail Servers", message)
        self.assertIn("Alpha Server (Dedicated Outgoing Mail Server):", message)
        self.assertIn("Bravo Server (Dedicated Outgoing Mail Server):", message)
        self.assertIn("Charlie Server (Dedicated Outgoing Mail Server):", message)
        self.assertLess(message.index("Alpha Server"), message.index("Bravo Server"))
        self.assertLess(message.index("Bravo Server"), message.index("Charlie Server"))
        self.assertLess(message.index("Alpha usage"), message.index("Bravo usage"))
        self.assertLess(message.index("Bravo usage"), message.index("Charlie usage"))
        self.assertTrue(all(servers.mapped("active")))

    def _make_message(self):
        """Build a minimal SMTP-policy EmailMessage for header-rewrite tests."""
        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = "sender@example.com"
        message["Subject"] = "Subject"
        return message

    def test_alter_message_x_msg_to_add_empty_to(self):
        """With no original To, X-Msg-To-Add yields a clean To (just the added
        address).

        Note this asserts the *re-parsed* header, which normalizes stray commas
        away; ``TestAlterMessageWireFormat`` asserts the serialized form, where
        the leading comma was actually observable.
        """
        message = self._make_message()
        message["X-Msg-To-Add"] = "added@example.com"
        self.IrMailServer._alter_message__(
            message, "sender@example.com", ["added@example.com"]
        )
        self.assertEqual(message["To"], "added@example.com")
        self.assertIsNone(message["X-Msg-To-Add"])

    def test_alter_message_x_msg_to_add_dedupes_against_existing_to(self):
        """X-Msg-To-Add appends only the addresses not already in To, and with a
        non-empty original To there is no leading comma."""
        message = self._make_message()
        message["To"] = "keep@example.com"
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
        self.assertEqual(message["To"], "forged@example.com")
        self.assertIsNone(message["Bcc"])
        self.assertIsNone(message["X-Forge-To"])
        self.assertIsNone(message["X-Msg-To-Add"])
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
            patch.object(
                type(IrMailServer), "_disable_send", classmethod(lambda cls: False)
            ),
            self.assertLogs(_IR_MAIL_SERVER_LOGGER, level="WARNING") as capture,
            self.assertRaises(MailDeliveryError) as ctx,
        ):
            IrMailServer.send_email(
                self._make_message(), smtp_session=_FailingSMTPSession()
            )

        self.assertIsInstance(ctx.exception.__cause__, smtplib.SMTPDataError)
        rendered = str(ctx.exception)
        self.assertTrue(rendered.startswith("Mail Delivery Failed\n"))
        self.assertIn("Mail delivery failed via SMTP server 'unknown'", rendered)
        self.assertIn("SMTPDataError", rendered)
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


@tagged("post_install", "-at_install")
class TestSmtpRecipientList(TransactionCase):
    """``_prepare_smtp_to_list`` builds the envelope recipient list (one RCPT TO
    per entry), so any duplicate in it is a duplicate delivery."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def _message(self, to=None, cc=None, bcc=None):
        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = "sender@example.com"
        for header, value in (("To", to), ("Cc", cc), ("Bcc", bcc)):
            if value:
                message[header] = value
        return message

    def test_recipient_repeated_across_headers_is_sent_once(self):
        """An address in To *and* Cc *and* Bcc is one mailbox: one RCPT TO.

        Regression: dedup ran per header, so a recipient who was also CC'd (and
        BCC'd) received the same message two or three times.
        """
        message = self._message(
            to="dup@example.com, only_to@example.com",
            cc="dup@example.com",
            bcc="dup@example.com, only_bcc@example.com",
        )
        self.assertEqual(
            self.IrMailServer._prepare_smtp_to_list(message, None),
            ["dup@example.com", "only_to@example.com", "only_bcc@example.com"],
        )

    def test_recipient_dedup_is_case_insensitive(self):
        """``Dup@Example.COM`` and ``dup@example.com`` are the same mailbox."""
        message = self._message(to="Dup@Example.COM", cc="dup@example.com")
        self.assertEqual(
            self.IrMailServer._prepare_smtp_to_list(message, None),
            ["Dup@Example.COM"],
        )

    def test_recipient_order_is_to_then_cc_then_bcc(self):
        """First-seen order is preserved across the three headers."""
        message = self._message(
            to="a@example.com", cc="b@example.com", bcc="c@example.com"
        )
        self.assertEqual(
            self.IrMailServer._prepare_smtp_to_list(message, None),
            ["a@example.com", "b@example.com", "c@example.com"],
        )

    def test_validated_to_accepts_normalized_match(self):
        """``send_validated_to`` holds normalized addresses (that is what
        ``mail.mail`` passes), so a header spelling the same mailbox with
        different casing must not be dropped."""
        message = self._message(to='"Alice B" <Alice@Example.COM>')
        self.assertEqual(
            self.IrMailServer.with_context(
                send_validated_to=["alice@example.com"]
            )._prepare_smtp_to_list(message, None),
            ["Alice@Example.COM"],
        )

    def test_validated_to_still_filters_unvetted_addresses(self):
        """The allow-list keeps filtering: an address absent from it is dropped."""
        message = self._message(to="alice@example.com, mallory@example.com")
        self.assertEqual(
            self.IrMailServer.with_context(
                send_validated_to=["alice@example.com"]
            )._prepare_smtp_to_list(message, None),
            ["alice@example.com"],
        )

    def test_skip_list_still_blocks_recipients(self):
        """``send_smtp_skip_to`` (normalized block list) is unaffected by dedup."""
        message = self._message(to="bad@example.com, good@example.com")
        self.assertEqual(
            self.IrMailServer.with_context(
                send_smtp_skip_to=["bad@example.com"]
            )._prepare_smtp_to_list(message, None),
            ["good@example.com"],
        )


@tagged("post_install", "-at_install")
class TestAlterMessageWireFormat(TransactionCase):
    """``_alter_message__`` header rewrites are asserted on the *serialized*
    message. Reading ``message["To"]`` back hides a malformed header, because
    the header registry re-parses and silently drops stray commas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def _to_line(self, message):
        return next(
            (
                line
                for line in message.as_string().splitlines()
                if line.startswith("To:")
            ),
            None,
        )

    def _message(self, to, x_msg_to_add):
        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = "sender@example.com"
        message["Subject"] = "Subject"
        if to:
            message["To"] = to
        message["X-Msg-To-Add"] = x_msg_to_add
        return message

    def test_no_original_to_emits_no_leading_comma(self):
        """Regression: an absent To produced ``To: , added@example.com``."""
        message = self._message(None, "added@example.com")
        self.IrMailServer._alter_message__(message, "sender@example.com", [])
        self.assertEqual(self._to_line(message), "To: added@example.com")

    def test_fully_redundant_addition_emits_no_trailing_comma(self):
        """Regression: an addition already in To produced ``To: keep@…, ``."""
        message = self._message("keep@example.com", "keep@example.com")
        self.IrMailServer._alter_message__(message, "sender@example.com", [])
        self.assertEqual(self._to_line(message), "To: keep@example.com")

    def test_genuine_addition_is_appended(self):
        message = self._message("keep@example.com", "extra@example.com")
        self.IrMailServer._alter_message__(message, "sender@example.com", [])
        self.assertEqual(
            self._to_line(message), "To: keep@example.com, extra@example.com"
        )


@tagged("post_install", "-at_install")
class TestEnvelopeOnlyHeaders(TransactionCase):
    """Headers that only exist to feed the SMTP envelope must never reach the
    wire: the delivering MTA prepends its own ``Return-Path`` from the envelope
    (RFC 5321 §4.4), so transmitting ours leaves the recipient with two.

    ``mail.thread`` sets ``Return-Path`` on every notification email (to route
    bounces to the alias domain), so this was on virtually all outgoing mail.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def _message(self):
        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = "sender@example.com"
        message["To"] = "rcpt@example.com"
        message["Bcc"] = "hidden@example.com"
        message["Return-Path"] = "bounce@example.com"
        message["Subject"] = "Subject"
        return message

    def test_return_path_feeds_the_envelope_then_is_stripped(self):
        message = self._message()
        smtp_from, smtp_to_list, message = self.IrMailServer._prepare_email_message__(
            message, None
        )
        self.assertEqual(
            smtp_from,
            "bounce@example.com",
            "Return-Path still selects the envelope sender",
        )
        self.assertIn("hidden@example.com", smtp_to_list)
        self.assertIsNone(message["Return-Path"])
        self.assertIsNone(message["Bcc"])
        self.assertNotIn("Return-Path", message.as_string())

    def test_alter_message_strips_return_path(self):
        message = self._message()
        self.IrMailServer._alter_message__(
            message, "sender@example.com", ["rcpt@example.com"]
        )
        self.assertIsNone(message["Return-Path"])

    def test_falsy_header_value_emits_no_header(self):
        """Regression: a header whose value is falsy serialized to a bare
        ``Key:`` line -- a syntax error, not an empty header.

        Callers build these dicts as
        ``headers.setdefault("Return-Path", a.bounce_email or b.bounce_email)``,
        so an unconfigured source arrives here as ``False``.
        """
        message = self.IrMailServer._build_email__(
            email_from="sender@example.com",
            email_to="rcpt@example.com",
            subject="Subject",
            body="body",
            headers={
                "X-Unset": False,
                "X-None": None,
                "X-Empty": "",
                # not a string: the header registry renders it to an empty
                # header too, so it must be dropped like the rest
                "X-Zero": 0,
                "X-Kept": "value",
                "X-Kept-Numeric": "0",
            },
        )
        wire = message.as_string()
        for header in ("X-Unset", "X-None", "X-Empty", "X-Zero"):
            self.assertIsNone(message[header])
            self.assertNotIn(f"{header}:", wire)
        self.assertIn("X-Kept: value", wire)
        self.assertIn("X-Kept-Numeric: 0", wire)


@tagged("post_install", "-at_install")
class TestFromFilterIndex(TransactionCase):
    """``from_filter`` parsing/matching lives in one place (``_from_filter_index``)
    so ``_match_from_filter`` and ``_find_mail_server``'s fallback cannot disagree
    about what a filter means."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def test_index_splits_addresses_from_domains(self):
        index = self.IrMailServer._from_filter_index(
            " Notify@Example.COM , Example.NET ,, "
        )
        self.assertEqual(index.emails, frozenset({"notify@example.com"}))
        self.assertEqual(index.domains, frozenset({"example.net"}))
        self.assertFalse(index.unrestricted)

    def test_separator_only_filter_is_unrestricted(self):
        """Regression: ``" , "`` is truthy, so it counted as a restriction that
        nothing could satisfy -- the server matched no sender, yet was excluded
        from the "no from_filter" fallback too, leaving it dead."""
        for from_filter in (" , ", ",,", "   ", "", False):
            with self.subTest(from_filter=from_filter):
                self.assertTrue(
                    self.IrMailServer._from_filter_index(from_filter).unrestricted
                )
                self.assertTrue(
                    self.IrMailServer._match_from_filter(
                        "anyone@example.com", from_filter
                    )
                )

    def test_unparseable_part_restricts_without_matching(self):
        """A junk entry must not fail open (it is still a restriction) and must
        not fail sideways either.

        Regression: ``_match_from_filter`` compared ``email_normalize(part)`` to
        ``email_normalize(sender)``, so a junk filter matched any sender that
        also failed to normalize -- ``False == False``.
        """
        index = self.IrMailServer._from_filter_index("@@@, example.com")
        self.assertEqual(index.emails, frozenset())
        self.assertEqual(index.domains, frozenset({"example.com"}))
        self.assertEqual(index.unparsed, 1)

        junk = self.IrMailServer._from_filter_index("@@@")
        self.assertFalse(junk.unrestricted, "junk must not authorize every sender")
        self.assertFalse(self.IrMailServer._match_from_filter("not an email", "@@@"))
        self.assertFalse(
            self.IrMailServer._match_from_filter("real@example.com", "@@@")
        )

    def test_match_from_filter_address_and_domain(self):
        from_filter = "notify@example.com, other.com"
        for sender, expected in (
            ("Notify@Example.com", True),
            ("someone@other.com", True),
            ("someone@example.com", False),
            ("notify@third.com", False),
            (False, False),
        ):
            with self.subTest(sender=sender):
                self.assertIs(
                    self.IrMailServer._match_from_filter(sender, from_filter), expected
                )

    def test_find_mail_server_treats_separator_only_filter_as_unrestricted(self):
        servers = self.IrMailServer.create(
            [
                {
                    "name": "restricted",
                    "smtp_host": "smtp_host",
                    "sequence": 10,
                    "from_filter": "restricted.example.com",
                },
                {
                    "name": "junk filter",
                    "smtp_host": "smtp_host",
                    "sequence": 20,
                    "from_filter": " , ",
                },
            ]
        )
        found, _email_from = self.IrMailServer.sudo()._find_mail_server(
            "someone@elsewhere.example.com", servers
        )
        self.assertEqual(
            found,
            servers[1],
            "the unrestricted server is picked through the regular fallback",
        )


@tagged("post_install", "-at_install")
class TestTransportAndSizeLimits(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def test_cli_authentication_still_honours_smtp_debug(self):
        """A ``cli`` server delegates host/auth/encryption to the CLI, but
        ``smtp_debug`` is a property of the record's UI and was dropped."""
        server = self.IrMailServer.create(
            {
                "name": "cli",
                "smtp_host": "ignored",
                "smtp_authentication": "cli",
                "smtp_debug": True,
                "from_filter": "example.com",
            }
        )
        transport = self.IrMailServer._resolve_smtp_transport(server)
        self.assertTrue(transport.debug)
        self.assertEqual(transport.from_filter, "example.com")

    def test_max_email_size_survives_a_non_numeric_parameter(self):
        """``base.default_max_email_size`` is admin-editable free text; a typo
        must not raise out of every outgoing email."""
        self.env["ir.config_parameter"].sudo().set_param(
            "base.default_max_email_size", "ten"
        )
        with self.assertLogs("odoo.addons.base.models.ir_config_parameter", "WARNING"):
            self.assertEqual(self.IrMailServer._get_max_email_size(), 10.0)

    def test_max_email_size_prefers_the_server_value(self):
        server = self.IrMailServer.create(
            {"name": "sized", "smtp_host": "smtp_host", "max_email_size": 42.5}
        )
        self.assertEqual(server._get_max_email_size(), 42.5)


class _Session:
    """SMTP session double exposing only the ESMTP feature map."""

    def __init__(self, features):
        if features is not None:
            self.esmtp_features = features


@tagged("post_install", "-at_install")
class TestSmtputf8Envelope(TransactionCase):
    """A non-ASCII envelope address is a permanent failure on a server without
    RFC 6531, and must be reported as one.

    ``extract_rfc2822_addresses`` punycodes the domain but passes a non-ASCII
    local part through, so such an address used to reach ``smtplib``, which
    raised ``SMTPNotSupportedError`` mid-``send_message``. ``mail.mail`` filed
    that under the generic ``unknown`` bucket, i.e. retry forever.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def _message(self, email_from="sender@example.com", email_to="rcpt@example.com"):
        message = EmailMessage(policy=email.policy.SMTP)
        message["From"] = email_from
        message["To"] = email_to
        message["Subject"] = "Subject"
        return message

    def test_session_capability_detection(self):
        self.assertTrue(
            self.IrMailServer._session_supports_smtputf8(_Session({"smtputf8": ""})),
        )
        self.assertFalse(
            self.IrMailServer._session_supports_smtputf8(_Session({"size": "10"})),
        )
        self.assertFalse(
            self.IrMailServer._session_supports_smtputf8(_Session({})),
            "a server that spoke EHLO without SMTPUTF8 cannot carry unicode",
        )
        for unknown in (None, _Session(None)):
            self.assertTrue(
                self.IrMailServer._session_supports_smtputf8(unknown),
                "no feature map (test mode / double): assume capable",
            )

    def test_non_ascii_sender_is_a_permanent_from_failure(self):
        message = self._message(email_from="jos\xe9@example.com")
        with self.assertRaises(OutgoingEmailError) as ctx:
            self.IrMailServer._prepare_email_message__(message, _Session({}))
        self.assertEqual(ctx.exception.code, self.IrMailServer.NO_VALID_FROM)
        self.assertIn("SMTPUTF8", str(ctx.exception))

    def test_non_ascii_recipient_is_a_permanent_recipient_failure(self):
        message = self._message(email_to="r\xe9cipient@example.com")
        with self.assertRaises(OutgoingEmailError) as ctx:
            self.IrMailServer._prepare_email_message__(message, _Session({}))
        self.assertEqual(ctx.exception.code, self.IrMailServer.NO_VALID_RECIPIENT)

    def test_non_ascii_allowed_when_the_server_advertises_smtputf8(self):
        """The check must not regress internationalized email on capable servers."""
        message = self._message(
            email_from="jos\xe9@example.com", email_to="r\xe9cipient@example.com"
        )
        smtp_from, smtp_to_list, _msg = self.IrMailServer._prepare_email_message__(
            message, _Session({"smtputf8": ""})
        )
        self.assertEqual(smtp_from, "jos\xe9@example.com")
        self.assertEqual(smtp_to_list, ["r\xe9cipient@example.com"])

    def test_ascii_envelope_is_untouched_on_a_plain_server(self):
        message = self._message()
        smtp_from, smtp_to_list, _msg = self.IrMailServer._prepare_email_message__(
            message, _Session({})
        )
        self.assertEqual(smtp_from, "sender@example.com")
        self.assertEqual(smtp_to_list, ["rcpt@example.com"])


@tagged("post_install", "-at_install")
class TestSmtpTimeout(TransactionCase):
    """The per-command socket timeout is an operational knob (--smtp-timeout),
    not a constant recompiled into the module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def test_timeout_comes_from_the_configuration(self):
        with patch.dict(config.options, {"smtp_timeout": 12}):
            self.assertEqual(self.IrMailServer._get_smtp_timeout(), 12)

    def test_zero_disables_the_timeout(self):
        with patch.dict(config.options, {"smtp_timeout": 0}):
            self.assertIsNone(
                self.IrMailServer._get_smtp_timeout(),
                "0 means block indefinitely, not 'time out immediately'",
            )

    def test_transport_carries_the_timeout_from_both_config_sources(self):
        server = self.IrMailServer.create(
            {"name": "timeout", "smtp_host": "smtp_host", "smtp_encryption": "none"}
        )
        with patch.dict(config.options, {"smtp_timeout": 7}):
            self.assertEqual(
                self.IrMailServer._resolve_smtp_transport(server).timeout, 7
            )
            self.assertEqual(
                self.IrMailServer._resolve_smtp_transport(
                    self.IrMailServer.browse(), host="smtp_host"
                ).timeout,
                7,
            )


@tagged("post_install", "-at_install")
class TestCertificateLoadErrors(TransactionCase):
    """Both certificate-loading paths must reject invalid admin-supplied PEM
    material with a UserError.

    Regression: the ``except`` clauses only listed pyOpenSSL's exceptions, but
    ``cryptography`` raises ``ValueError`` and ``PyOpenSSLContext.load_cert_chain``
    raises ``ssl.SSLError``, so a bad certificate escaped as a raw traceback and
    ``_ssl_load_error`` was never reached.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.IrMailServer = cls.env["ir.mail_server"]

    def test_invalid_stored_certificate_raises_user_error(self):
        server = self.IrMailServer.create(
            {
                "name": "bad-cert",
                "smtp_host": "smtp.example.com",
                "smtp_authentication": "certificate",
                "smtp_encryption": "starttls_strict",
                "smtp_ssl_certificate": base64.b64encode(b"not a certificate"),
                "smtp_ssl_private_key": base64.b64encode(b"not a key"),
            }
        )
        with self.assertRaises(UserError) as ctx:
            self.IrMailServer._ssl_context_from_certificate(server, "smtp.example.com")
        self.assertIn("not a valid file", str(ctx.exception))

    def test_invalid_certificate_files_raise_user_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert_path = Path(tmp) / "cert.pem"
            key_path = Path(tmp) / "key.pem"
            cert_path.write_bytes(b"not a certificate")
            key_path.write_bytes(b"not a key")
            with self.assertRaises(UserError) as ctx:
                self.IrMailServer._ssl_context_from_cert_files(
                    str(cert_path), str(key_path), "starttls_strict", "smtp.example.com"
                )
        self.assertIn("not a valid file", str(ctx.exception))

    def test_non_base64_certificate_field_raises_user_error(self):
        """A corrupted Binary field value must not escape as binascii.Error."""
        server = self.IrMailServer.create(
            {
                "name": "corrupt-cert",
                "smtp_host": "smtp.example.com",
                "smtp_authentication": "certificate",
                "smtp_encryption": "starttls",
                "smtp_ssl_certificate": b"!!!not base64!!!",
                "smtp_ssl_private_key": b"!!!not base64!!!",
            }
        )
        with self.assertRaises(UserError):
            self.IrMailServer._ssl_context_from_certificate(server, "smtp.example.com")
