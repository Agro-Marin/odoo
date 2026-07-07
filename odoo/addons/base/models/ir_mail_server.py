import base64
import datetime
import email.policy
import functools
import logging
import smtplib
import ssl
from contextlib import suppress
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import make_msgid
from socket import gaierror
from typing import Any, NamedTuple, Self

import idna
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509 import load_pem_x509_certificate
from OpenSSL.crypto import Error as SSLCryptoError
from OpenSSL.SSL import VERIFY_FAIL_IF_NO_PEER_CERT, VERIFY_PEER
from OpenSSL.SSL import Error as SSLError
from urllib3.contrib.pyopenssl import PyOpenSSLContext, get_subj_alt_name
from urllib3.util.ssl_match_hostname import CertificateError, match_hostname

from odoo import _, api, fields, models, modules, tools
from odoo.exceptions import UserError
from odoo.libs.email import extract_rfc2822_addresses
from odoo.tools import (
    email_domain_extract,
    email_domain_normalize,
    email_normalize,
    encapsulate_email,
    human_size,
)

_logger = logging.getLogger(__name__)
_test_logger = logging.getLogger("odoo.tests")

SMTP_TIMEOUT = 60


class MailDeliveryError(Exception):
    """Specific exception subclass for mail delivery errors.

    A short human message plus optional detail are passed as separate
    positional args (e.g. ``MailDeliveryError("Mail Delivery Failed", detail)``).
    ``str()`` joins them with newlines so the rendered text — and therefore the
    ``mail.mail.failure_reason`` stored by queue processors via ``str(exc)`` — is
    a clean multi-line message rather than a ``('a', 'b')`` tuple repr. ``.args``
    is left untouched, so callers that inspect the individual args still work.
    """

    def __str__(self) -> str:
        return "\n".join(str(arg) for arg in self.args)


# Backward-compatibility alias — external modules import MailDeliveryException
MailDeliveryException = MailDeliveryError


class OutgoingEmailError(UserError):
    """User-facing error raised while resolving/preparing an outgoing email.

    Carries a stable, non-translated ``code`` (one of the ``NO_*`` message
    constants on :class:`IrMail_Server`) so that queue processors such as
    ``mail.mail`` can classify the failure (``failure_type``) without matching
    on the — possibly translated or detail-augmented — message text.

    This subclass exists because those constants double as control-flow keys:
    ``mail.mail`` historically matched them via ``except AssertionError`` /
    ``e.args[0]``, but the model raises ``UserError`` (never an
    ``AssertionError``), so the ``mail_email_invalid`` / ``mail_from_*``
    classification silently degraded to ``unknown``. Matching on ``.code``
    restores it and decouples display text from control flow.
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        self.code = code or message
        super().__init__(message)


# Python 3: patch SMTP's internal printer/debugger
def _print_debug(self: Any, *args: Any) -> None:
    _logger.debug(" ".join(str(a) for a in args))


smtplib.SMTP._print_debug = _print_debug

# Python 3: workaround for bpo-35805, only partially fixed in Python 3.8.
RFC5322_IDENTIFICATION_HEADERS = {
    "message-id",
    "in-reply-to",
    "references",
    "resent-msg-id",
}
USER_DEFINED_HEADERS = {"bcc", "cc", "from", "reply-to", "subject", "to"}
_NO_FOLD_POLICY = email.policy.SMTP.clone(max_line_length=None)
_MAX_FOLD_POLICY = email.policy.SMTP.clone(max_line_length=998)  # rfc5322#section-2.1.1


class IdentificationFieldsNoFoldPolicy(email.policy.EmailPolicy):
    # Override _fold() to avoid folding identification fields, excluded by RFC2047 section 5
    # These are particularly important to preserve, as MTAs will often rewrite non-conformant
    # Message-ID headers, causing a loss of thread information (replies are lost)
    # Also override _fold() for user-defined headers that may not fit on 78 characters,
    # as Python's folding algorithm is unreliable and fails to handle all weird cases.
    def _fold(self, name: str, value: str, *args: Any, **kwargs: Any) -> str:
        lname = name.lower()
        if lname in RFC5322_IDENTIFICATION_HEADERS:
            return _NO_FOLD_POLICY._fold(name, value, *args, **kwargs)
        if lname in USER_DEFINED_HEADERS:
            return _MAX_FOLD_POLICY._fold(name, value, *args, **kwargs)
        return super()._fold(name, value, *args, **kwargs)


# Our preferred outgoing/parsing policy (see the class above). ``_NO_FOLD_POLICY``
# and ``_MAX_FOLD_POLICY`` above were cloned from the *stock* ``email.policy.SMTP``
# on purpose — they are built before the reassignment below.
SMTP_POLICY = IdentificationFieldsNoFoldPolicy(linesep=email.policy.SMTP.linesep)

# Reassign the stdlib singleton so that code addressing the policy by its canonical
# name — ``email.policy.SMTP`` — picks up ours without importing from this module.
# This is a deliberate injection point, not an accident: inbound parsers such as
# ``mail.mail_thread`` and enterprise ``l10n_cl_edi`` reference ``email.policy.SMTP``
# directly and rely on this override. Prefer the ``SMTP_POLICY`` name in new code.
email.policy.SMTP = SMTP_POLICY


def _verify_check_hostname_callback(
    cnx: Any,
    x509: Any,
    err_no: int,
    err_depth: int,
    return_code: int,
    *,
    hostname: str,
) -> bool:
    """Callback for pyOpenSSL's verify_mode.

    By default pyOpenSSL only checks ``err_no``; we also verify that the SMTP
    server ``hostname`` matches the ``x509`` certificate's Common Name (CN) or
    Subject Alternative Name (SAN).
    """
    if err_no:
        return False

    if err_depth == 0:  # leaf certificate
        peercert = {
            "subject": ((("commonName", x509.get_subject().CN),),),
            "subjectAltName": get_subj_alt_name(x509),
        }
        match_hostname(peercert, hostname)  # it raises when it does not match

    return True


class _SmtpTransport(NamedTuple):
    """Fully-resolved SMTP transport parameters, the single output of
    :meth:`IrMail_Server._resolve_smtp_transport`.

    Separating *resolution* (which source wins: record fields vs CLI/config vs
    explicit params, and which SSL context to build) from the *socket I/O* in
    ``_connect__`` makes the resolution — the subtle, fallback-heavy, and
    historically bug-prone part — unit-testable without opening a connection,
    and forces both configuration sources through one place so their SSL/verify
    handling cannot silently drift apart again.
    """

    server: str | None
    port: int | None
    user: str | None
    password: str | None
    encryption: str | None
    debug: bool
    from_filter: str | None
    ssl_context: Any
    # ir.mail_server record used for _smtp_login__ (empty recordset on the
    # CLI/param path, so OAuth overrides fall back to plain LOGIN).
    login_server: Any


class _SmtpSessionContext(NamedTuple):
    """Per-connection routing context, resolved at connect time and consulted by
    :meth:`IrMail_Server._prepare_email_message__` when deciding whether the
    envelope FROM may be rewritten so bounces come back (VERP / bounce alias).

    - ``from_filter``: the ``from_filter`` of the selected server / CLI config,
      i.e. which senders this transport is allowed to send as.
    - ``smtp_from``: the envelope sender resolved while choosing the server.

    It is carried as flat ``from_filter`` / ``smtp_from`` attributes on the smtp
    connection object rather than wrapping it, on purpose: ``send_email`` accepts
    a *caller-supplied* session and callers (e.g. ``mail.mail``) invoke smtplib
    methods — ``quit()`` — on the exact object ``_connect__`` returns, so that
    object must remain a real connection. The test doubles in
    ``base/tests/common.py`` also read these attribute names. Every access goes
    through :meth:`IrMail_Server._stash_session_context` /
    :meth:`IrMail_Server._read_session_context` so the contract lives in one
    place instead of scattered ``getattr(session, "from_filter", ...)`` calls.
    """

    from_filter: str | bool = False
    smtp_from: str | bool = False


class IrMail_Server(models.Model):
    """Represents an SMTP server, able to send outgoing emails, with SSL and TLS capabilities."""

    _name = "ir.mail_server"
    _description = "Mail Server"
    _order = "sequence, id"
    _allow_sudo_commands = False

    # Outgoing-email validation messages. These double as stable failure
    # *codes*: they are stored verbatim in ``mail.mail.failure_reason`` and
    # matched by queue processors (see ``OutgoingEmailError.code``), so they are
    # intentionally kept as plain, non-translated ASCII identifiers.
    NO_VALID_RECIPIENT = "At least one valid recipient address should be specified for outgoing emails (To/Cc/Bcc)"
    NO_FOUND_FROM = (
        "You must either provide a sender address explicitly or configure "
        "using the combination of `mail.catchall.domain` and `mail.default.from` "
        "ICPs, in the server configuration file or with the --email-from startup "
        "parameter."
    )
    NO_FOUND_SMTP_FROM = (
        "The Return-Path or From header is required for any outbound email"
    )
    NO_VALID_FROM = "Malformed 'Return-Path' or 'From' address. It should contain one valid plain ASCII email"

    name = fields.Char(string="Name", required=True, index=True)
    from_filter = fields.Char(
        "FROM Filtering",
        help="Comma-separated list of addresses or domains for which this server can be used.\n"
        'e.g.: "notification@odoo.com" or "odoo.com"',
    )
    smtp_host = fields.Char(string="SMTP Server", help="Hostname or IP of SMTP server")
    smtp_port = fields.Integer(
        string="SMTP Port",
        default=25,
        help="SMTP Port. Usually 465 for SSL, and 25 or 587 for other cases.",
    )
    smtp_authentication = fields.Selection(
        [
            ("login", "Username"),
            ("certificate", "SSL Certificate"),
            ("cli", "Command Line Interface"),
        ],
        string="Authenticate with",
        required=True,
        default="login",
    )
    smtp_authentication_info = fields.Text(
        "Authentication Info", compute="_compute_smtp_authentication_info"
    )
    smtp_user = fields.Char(
        string="Username",
        help="Optional username for SMTP authentication",
        groups="base.group_system",
    )
    smtp_pass = fields.Char(
        string="Password",
        help="Optional password for SMTP authentication",
        groups="base.group_system",
    )
    smtp_encryption = fields.Selection(
        [
            ("none", "None"),
            ("starttls_strict", "TLS (STARTTLS), encryption and validation"),
            ("starttls", "TLS (STARTTLS), encryption only"),
            ("ssl_strict", "SSL/TLS, encryption and validation"),
            ("ssl", "SSL/TLS, encryption only"),
        ],
        string="Connection Encryption",
        required=True,
        default="none",
        help="Choose the connection encryption scheme:\n"
        "- None: SMTP sessions are done in cleartext.\n"
        "- TLS (STARTTLS): TLS encryption is requested at start of SMTP session (Recommended)\n"
        "- SSL/TLS: SMTP sessions are encrypted with SSL/TLS through a dedicated port (default: 465)\n"
        "\n"
        "Choose an additional variant for SSL or TLS:\n"
        "- encryption and validation: encrypt the data and authenticate the server using its SSL certificate (Recommended)\n"
        "- encryption only: encrypt the data but skip server authentication",
    )
    smtp_ssl_certificate = fields.Binary(
        "SSL Certificate",
        groups="base.group_system",
        attachment=False,
        help="SSL certificate used for authentication",
    )
    smtp_ssl_private_key = fields.Binary(
        "SSL Private Key",
        groups="base.group_system",
        attachment=False,
        help="SSL private key used for authentication",
    )
    smtp_debug = fields.Boolean(
        string="Debugging",
        help="If enabled, the full output of SMTP sessions will "
        "be written to the server log at DEBUG level "
        "(this is very verbose and may include confidential info!)",
    )
    max_email_size = fields.Float(string="Max Email Size")
    sequence = fields.Integer(
        string="Priority",
        default=10,
        help="When no specific mail server is requested for a mail, the highest priority one "
        "is used. Default priority is 10 (smaller number = higher priority)",
    )
    active = fields.Boolean(default=True)

    _certificate_requires_tls = models.Constraint(
        "CHECK(smtp_encryption != 'none' OR smtp_authentication != 'certificate')",
        "Certificate-based authentication requires a TLS transport",
    )

    @api.depends("smtp_authentication")
    def _compute_smtp_authentication_info(self) -> None:
        info_by_type = {
            "login": _(
                "Connect to your server through your usual username and password. \n"
                "This is the most basic SMTP authentication process and "
                "may not be accepted by all providers. \n"
            ),
            "certificate": _(
                "Authenticate by using SSL certificates, belonging to your domain name. \n"
                "SSL certificates allow you to authenticate your mail server for the entire domain name."
            ),
            "cli": _(
                'Use the SMTP configuration set in the "Command Line Interface" arguments.'
            ),
        }
        for server in self:
            if info := info_by_type.get(server.smtp_authentication):
                server.smtp_authentication_info = info
            else:
                server.smtp_authentication_info = False

    @api.constrains(
        "smtp_authentication", "smtp_ssl_certificate", "smtp_ssl_private_key"
    )
    def _check_smtp_ssl_files(self) -> None:
        for mail_server in self:
            if mail_server.smtp_authentication == "certificate":
                if not mail_server.smtp_ssl_private_key:
                    raise UserError(
                        _(
                            "SSL private key is missing for %s.",
                            mail_server.name,
                        )
                    )
                if not mail_server.smtp_ssl_certificate:
                    raise UserError(
                        _(
                            "SSL certificate is missing for %s.",
                            mail_server.name,
                        )
                    )

    def write(self, vals: dict[str, Any]) -> bool:
        """Ensure we cannot archive a server in-use"""
        usages_per_server = {}
        if not vals.get("active", True):
            usages_per_server = self._active_usages_compute()

        if not usages_per_server:
            return super().write(vals)

        # Write cannot be performed as some server are used, build detailed usage per server
        usage_details_per_server = {}
        is_multiple_server_usage = len(usages_per_server) > 1
        for server in self:
            if server.id not in usages_per_server:
                continue
            usage_details = []
            if is_multiple_server_usage:
                usage_details.append(
                    _(
                        "%s (Dedicated Outgoing Mail Server):",
                        server.display_name,
                    )
                )
            usage_details.extend(f"- {u}" for u in usages_per_server[server.id])
            usage_details_per_server[server] = usage_details

        # Raise the error with the ordered list of servers and concatenated detailed usages
        servers_ordered_by_name = sorted(
            usage_details_per_server.keys(), key=lambda r: r.display_name
        )
        error_server_usage = ", ".join(
            server.display_name for server in servers_ordered_by_name
        )
        error_usage_details = "\n".join(
            line
            for server in servers_ordered_by_name
            for line in usage_details_per_server[server]
        )
        if is_multiple_server_usage:
            raise UserError(
                _(
                    "You cannot archive these Outgoing Mail Servers (%(server_usage)s) because they are still used in the following case(s):\n%(usage_details)s",
                    server_usage=error_server_usage,
                    usage_details=error_usage_details,
                )
            )
        raise UserError(
            _(
                "You cannot archive this Outgoing Mail Server (%(server_usage)s) because it is still used in the following case(s):\n%(usage_details)s",
                server_usage=error_server_usage,
                usage_details=error_usage_details,
            )
        )

    def _active_usages_compute(self) -> dict[int, list[str]]:
        """Map each server id to user-friendly descriptions of its active usages.

        Override in modules that use this model to list the active elements that
        could send mail through a server in this recordset.

        :return: ``{ir_mail_server.id: usage_str_list}``
        :rtype: dict[int, list[str]]
        """
        return {}

    def _get_max_email_size(self) -> float:
        # NB: intentionally supports an empty recordset (falls back to the
        # config default), so no ensure_one() — callers may pass the default
        # server as an empty ir.mail_server recordset.
        if self.max_email_size:
            return self.max_email_size
        return float(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("base.default_max_email_size", "10")
        )

    def _get_test_email_from(self) -> str:
        self.ensure_one()
        email_from = False
        if from_filter_parts := self._parse_from_filter(self.from_filter):
            # find first found complete email in filter parts
            email_from = next(
                (email for email in from_filter_parts if "@" in email), False
            )
            # no complete email -> consider noreply
            if not email_from:
                email_from = f"noreply@{from_filter_parts[0]}"
        if not email_from:
            # Fallback to current user email if there's no from filter
            email_from = self.env.user.email
        if not email_from or "@" not in email_from:
            raise UserError(
                _(
                    "Please configure an email on the current user to simulate "
                    "sending an email message via this outgoing server"
                )
            )
        return email_from

    def _get_test_email_to(self) -> str:
        return "noreply@odoo.com"

    def test_smtp_connection(
        self, autodetect_max_email_size: bool = False
    ) -> dict[str, Any]:
        """Test the connection and if autodetect_max_email_size, set auto-detected max email size.

        :param bool autodetect_max_email_size: whether to autodetect the max email size
        :return: client action to notify the user of the result of the operation (connection test or
            auto-detection successful depending on the ``autodetect_max_email_size`` parameter)
        :rtype: dict[str, Any]

        :raises UserError: if the connection fails and if ``autodetect_max_email_size`` and
            the server doesn't support the auto-detection of email max size
        """
        for server in self:
            smtp = False
            try:
                # simulate sending an email from current user's address - without sending it!
                email_from = server._get_test_email_from()
                email_to = server._get_test_email_to()
                smtp = self._connect__(
                    mail_server_id=server.id,
                    allow_archived=True,
                    smtp_from=email_from,
                )
                # Testing the MAIL FROM step should detect sender filter problems
                code, repl = smtp.mail(email_from)
                if code != 250:
                    raise UserError(
                        _(
                            "The server refused the sender address (%(email_from)s) with error %(repl)s",
                            email_from=email_from,
                            repl=repl,
                        )
                    )
                # Testing the RCPT TO step should detect most relaying problems
                code, repl = smtp.rcpt(email_to)
                if code not in (250, 251):
                    raise UserError(
                        _(
                            "The server refused the test recipient (%(email_to)s) with error %(repl)s",
                            email_to=email_to,
                            repl=repl,
                        )
                    )
                # Beginning the DATA step should detect some deferred rejections
                # Can't use self.data() as it would actually send the mail!
                smtp.putcmd("data")
                code, repl = smtp.getreply()
                if code != 354:
                    raise UserError(
                        _(
                            "The server refused the test connection with error %(repl)s",
                            repl=repl,
                        )
                    )
                if autodetect_max_email_size:
                    max_size = smtp.esmtp_features.get("size")
                    if not max_size:
                        raise UserError(
                            _(
                                'The server "%(server_name)s" doesn\'t return the maximum email size.',
                                server_name=server.name,
                            )
                        )
                    server.max_email_size = float(max_size) / (1024**2)
            except UserError:
                # UserErrors raised by the probe steps above already carry a
                # tailored message — surface them verbatim.
                raise
            except Exception as e:
                raise self._connection_test_error(e, server) from e
            finally:
                if smtp:
                    with suppress(Exception):
                        smtp.close()

        if autodetect_max_email_size:
            message = _(
                "Email maximum size updated (%(details)s).",
                details=", ".join(
                    f"{server.name}: {human_size(server.max_email_size * 1024**2)}"
                    for server in self
                ),
            )
        else:
            message = _("Connection Test Successful!")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},  # force a form reload
            },
        }

    def _connection_test_error(self, exc: Exception, server: Self) -> UserError:
        """Translate a raw connection-test exception into a user-facing UserError.

        Ordered most-specific first; the SMTP subclasses must precede
        ``smtplib.SMTPException`` so their tailored message wins. An unmatched
        exception is logged (with traceback) and wrapped in a generic message —
        the only branch that logs, since the others are self-explanatory.
        """
        handlers = (
            (
                (UnicodeError, idna.core.InvalidCodepoint),
                lambda e: _("Invalid server name!\n %s", e),
            ),
            (
                (TimeoutError, gaierror),
                lambda e: _(
                    "No response received. Check server address and port number.\n %s",
                    e,
                ),
            ),
            (
                smtplib.SMTPServerDisconnected,
                lambda e: _(
                    "The server has closed the connection unexpectedly. Check configuration served on this port number.\n %s",
                    e,
                ),
            ),
            (
                smtplib.SMTPResponseException,
                lambda e: _("Server replied with following exception:\n %s", e),
            ),
            (
                smtplib.SMTPNotSupportedError,
                lambda e: _("An option is not supported by the server:\n %s", e),
            ),
            (
                smtplib.SMTPException,
                lambda e: _(
                    "An SMTP exception occurred. Check port number and connection security type.\n %s",
                    e,
                ),
            ),
            (
                CertificateError,
                lambda e: _(
                    "An SSL exception occurred. Check connection security type.\n CertificateError: %s",
                    e,
                ),
            ),
            (
                (ssl.SSLError, SSLError),
                lambda e: _(
                    "An SSL exception occurred. Check connection security type.\n %s",
                    e,
                ),
            ),
        )
        for exc_types, make_message in handlers:
            if isinstance(exc, exc_types):
                return UserError(make_message(exc))

        _logger.warning(
            "Connection test on %s failed with a generic error.",
            server,
            exc_info=exc,
        )
        return UserError(
            _("Connection Test Failed! Here is what we got instead:\n %s", exc)
        )

    def action_retrieve_max_email_size(self) -> dict[str, Any]:
        self.ensure_one()
        return self.test_smtp_connection(autodetect_max_email_size=True)

    @classmethod
    def _disable_send(cls) -> bool:
        """Whether to disable sending e-mails"""
        # no e-mails during testing or when registry is initializing
        return modules.module.current_test or cls.pool._init

    def _connect__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        encryption: str | None = None,
        smtp_from: str | None = None,
        ssl_certificate: str | None = None,
        ssl_private_key: str | None = None,
        smtp_debug: bool = False,
        mail_server_id: int | None = None,
        allow_archived: bool = False,
    ) -> smtplib.SMTP | smtplib.SMTP_SSL | None:
        """Returns a new SMTP connection to the given SMTP server.
        When running in test mode, this method does nothing and returns `None`.

        :param str | None host: host or IP of SMTP server to connect to, if mail_server_id not passed
        :param int | None port: SMTP port to connect to
        :param str | None user: optional username to authenticate with
        :param str | None password: optional password to authenticate with
        :param str | None encryption: optional, ``'none'`` | ``'ssl'`` | ``'ssl_strict'`` | ``'starttls'`` | ``'starttls_strict'``.
            The 'strict' variants verify the remote server's certificate against the operating system trust store.
        :param smtp_from: FROM SMTP envelop, used to find the best mail server
        :param ssl_certificate: filename of the SSL certificate used for authentication.
            Used when no mail server is given; overrides the ``--smtp-ssl-certificate-filename`` odoo-bin argument
        :param ssl_private_key: filename of the SSL private key used for authentication.
            Used when no mail server is given; overrides the ``--smtp-ssl-private-key-filename`` odoo-bin argument
        :param bool smtp_debug: toggle debugging of SMTP sessions (all i/o
                           will be output in logs)
        :param mail_server_id: ID of specific mail server to use (overrides other parameters)
        :param bool allow_archived: by default (False), an exception is raised when calling this method on an
            archived record (using mail_server_id param). It can be set to True for testing so that the exception is
            no longer raised.
        """
        # Do not actually connect while running in test mode
        if self._disable_send():
            return None

        mail_server = None
        if mail_server_id:
            mail_server = self.sudo().browse(mail_server_id)
            self._check_forced_mail_server(mail_server, allow_archived, smtp_from)
        elif not host:
            mail_server, smtp_from = self.sudo()._find_mail_server(smtp_from)
        if not mail_server:
            mail_server = self.env["ir.mail_server"]

        transport = self._resolve_smtp_transport(
            mail_server,
            host=host,
            port=port,
            user=user,
            password=password,
            encryption=encryption,
            ssl_certificate=ssl_certificate,
            ssl_private_key=ssl_private_key,
            smtp_debug=smtp_debug,
        )
        return self._open_smtp_connection(transport, smtp_from)

    def _resolve_smtp_transport(
        self,
        mail_server: Self,
        *,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        encryption: str | None = None,
        ssl_certificate: str | None = None,
        ssl_private_key: str | None = None,
        smtp_debug: bool = False,
    ) -> _SmtpTransport:
        """Resolve the effective SMTP transport (host/port/auth/encryption/SSL
        context) from a mail-server record *or* from CLI/config/explicit params.

        Pure with respect to the socket: it opens no connection, so it is
        directly unit-testable. Both configuration sources funnel their
        encryption→SSL-context decision through here, which is what keeps the
        'strict' verification semantics from drifting between them.

        :param mail_server: resolved ``ir.mail_server`` record, or the empty
            recordset when the transport comes from CLI/config/params.
        """
        if mail_server and mail_server.smtp_authentication != "cli":
            # Transport fully described by the mail-server record.
            is_certificate = mail_server.smtp_authentication == "certificate"
            encryption = mail_server.smtp_encryption
            if is_certificate:
                ssl_context = self._ssl_context_from_certificate(
                    mail_server, mail_server.smtp_host
                )
            elif encryption != "none":
                ssl_context = self._ssl_context_for_encryption(encryption)
            else:
                ssl_context = None
            return _SmtpTransport(
                server=mail_server.smtp_host,
                port=mail_server.smtp_port,
                user=None if is_certificate else mail_server.smtp_user,
                password=None if is_certificate else mail_server.smtp_pass,
                encryption=encryption,
                debug=smtp_debug or mail_server.smtp_debug,
                from_filter=mail_server.from_filter,
                ssl_context=ssl_context,
                login_server=mail_server,
            )

        # We were passed individual smtp parameters, or nothing, or a
        # "cli"-authenticated mail server. In all these cases the transport
        # comes entirely from the CLI/config: a "cli" mail server record
        # contributes ONLY its from_filter — its smtp_host/port/encryption/
        # user/pass/debug fields are deliberately ignored here.
        if encryption is None and tools.config.get("smtp_ssl"):
            encryption = "starttls"  # smtp_ssl => STARTTLS as of v7

        cert_filename = ssl_certificate or tools.config.get(
            "smtp_ssl_certificate_filename"
        )
        key_filename = ssl_private_key or tools.config.get(
            "smtp_ssl_private_key_filename"
        )
        if cert_filename and key_filename:
            ssl_context = self._ssl_context_from_cert_files(cert_filename, key_filename)
        elif encryption not in (None, "none"):
            # Without a client certificate, the raw-parameter path still has to
            # honour the encryption strictness the caller asked for. Skipping
            # this left ``ssl_context`` None, so smtplib fell back to an
            # *unverified* stdlib context (CERT_NONE) — silently downgrading
            # ``ssl_strict`` / ``starttls_strict`` to no server-certificate
            # validation, the opposite of what ``send_email`` documents.
            ssl_context = self._ssl_context_for_encryption(encryption)
        else:
            ssl_context = None

        return _SmtpTransport(
            server=host or tools.config.get("smtp_server"),
            port=tools.config.get("smtp_port", 25) if port is None else port,
            user=user or tools.config.get("smtp_user"),
            password=password or tools.config.get("smtp_password"),
            encryption=encryption,
            debug=smtp_debug,
            from_filter=(
                mail_server.from_filter
                if mail_server
                else self.env["ir.mail_server"]._get_default_from_filter()
            ),
            ssl_context=ssl_context,
            login_server=mail_server,
        )

    def _open_smtp_connection(
        self, transport: _SmtpTransport, smtp_from: str | None
    ) -> smtplib.SMTP | smtplib.SMTP_SSL:
        """Open, secure and authenticate a socket for a resolved transport.

        Stashes ``from_filter`` / ``smtp_from`` on the returned connection for
        :meth:`_prepare_email_message__` to consult when deciding whether the
        envelope FROM may be spoofed to receive bounces.
        """
        if not transport.server:
            raise UserError(
                _(
                    "Missing SMTP Server\n"
                    "Please define at least one SMTP server, "
                    "or provide the SMTP parameters explicitly.",
                )
            )

        if transport.encryption in ("ssl", "ssl_strict"):
            connection = smtplib.SMTP_SSL(
                transport.server,
                transport.port,
                timeout=SMTP_TIMEOUT,
                context=transport.ssl_context,
            )
        else:
            connection = smtplib.SMTP(
                transport.server, transport.port, timeout=SMTP_TIMEOUT
            )
        connection.set_debuglevel(transport.debug)
        if transport.encryption in ("starttls", "starttls_strict"):
            # starttls() will perform ehlo() if needed first
            # and will discard the previous list of services
            # after successfully performing STARTTLS command,
            # (as per RFC 3207) so for example any AUTH
            # capability that appears only on encrypted channels
            # will be correctly detected for next step
            connection.starttls(context=transport.ssl_context)

        if transport.user:
            # Attempt authentication - will raise if AUTH service not supported
            smtp_user = transport.user
            local, at, domain = smtp_user.rpartition("@")
            if at:
                smtp_user = local + at + idna.encode(domain).decode("ascii")
            transport.login_server._smtp_login__(
                connection, smtp_user, transport.password or ""
            )

        # Some methods of SMTP don't check whether EHLO/HELO was sent.
        # Anyway, as it may have been sent by login(), all subsequent usages should consider this command as sent.
        connection.ehlo_or_helo_if_needed()

        # Record routing context so _prepare_email_message__ knows whether it may
        # rewrite the envelope FROM to receive bounces (see _SmtpSessionContext).
        self._stash_session_context(
            connection,
            _SmtpSessionContext(
                from_filter=transport.from_filter, smtp_from=smtp_from
            ),
        )
        return connection

    @staticmethod
    def _stash_session_context(
        connection: smtplib.SMTP, context: _SmtpSessionContext
    ) -> None:
        """Record :class:`_SmtpSessionContext` on an SMTP connection."""
        connection.from_filter = context.from_filter
        connection.smtp_from = context.smtp_from

    @staticmethod
    def _read_session_context(smtp_session: smtplib.SMTP) -> _SmtpSessionContext:
        """Read the :class:`_SmtpSessionContext` stashed on a session.

        A bare, caller-supplied session that was never stashed (e.g. a raw
        smtplib connection passed straight to ``send_email``) yields the default
        ``(False, False)``, preserving the previous ``getattr(..., False)``
        semantics.
        """
        return _SmtpSessionContext(
            from_filter=getattr(smtp_session, "from_filter", False),
            smtp_from=getattr(smtp_session, "smtp_from", False),
        )

    @staticmethod
    def _ssl_load_error(exc: Exception) -> UserError:
        """Translate a low-level certificate/key loading error into a UserError.

        Shared by every certificate-loading path so the two user-facing
        messages live in exactly one place.
        """
        if isinstance(exc, SSLCryptoError):
            return UserError(
                _(
                    "The private key or the certificate is not a valid file. \n%s",
                    str(exc),
                )
            )
        return UserError(
            _("Could not load your certificate / private key. \n%s", str(exc))
        )

    def _ssl_context_from_certificate(
        self, mail_server: Self, smtp_server: str
    ) -> PyOpenSSLContext:
        """Build a client-auth SSL context from a mail server's stored PEM
        certificate/private key (``smtp_authentication == 'certificate'``).

        The 'strict' encryption variants verify the peer and its hostname; the
        lax variants disable verification.
        """
        try:
            ssl_context = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
            if mail_server.smtp_encryption in ("ssl_strict", "starttls_strict"):
                ssl_context.set_default_verify_paths()
                ssl_context._ctx.set_verify(
                    VERIFY_PEER | VERIFY_FAIL_IF_NO_PEER_CERT,
                    functools.partial(
                        _verify_check_hostname_callback,
                        hostname=smtp_server,
                    ),
                )
            else:  # ssl, starttls
                ssl_context.verify_mode = ssl.CERT_NONE
            ssl_context._ctx.use_certificate(
                load_pem_x509_certificate(
                    base64.b64decode(mail_server.smtp_ssl_certificate)
                )
            )
            ssl_context._ctx.use_privatekey(
                load_pem_private_key(
                    base64.b64decode(mail_server.smtp_ssl_private_key),
                    password=None,
                )
            )
            # Check that the private key matches the certificate
            ssl_context._ctx.check_privatekey()
        except (SSLCryptoError, SSLError) as e:
            raise self._ssl_load_error(e) from None
        return ssl_context

    def _ssl_context_from_cert_files(
        self, cert_filename: str, key_filename: str
    ) -> PyOpenSSLContext:
        """Build a client-auth SSL context from certificate/key files on disk
        (CLI/config ``--smtp-ssl-*-filename`` arguments)."""
        try:
            ssl_context = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.verify_mode = ssl.CERT_NONE
            ssl_context.load_cert_chain(cert_filename, keyfile=key_filename)
            # Check that the private key matches the certificate
            ssl_context._ctx.check_privatekey()
        except (SSLCryptoError, SSLError) as e:
            raise self._ssl_load_error(e) from None
        return ssl_context

    @staticmethod
    def _ssl_context_for_encryption(encryption: str) -> ssl.SSLContext:
        """Build a standard TLS context for a (non-certificate) encrypted
        transport. 'strict' variants validate the server certificate and
        hostname against the OS trust store; lax variants encrypt only.
        """
        ssl_context = ssl.create_default_context()
        if encryption in ("ssl_strict", "starttls_strict"):
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
        else:  # ssl, starttls
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def _check_forced_mail_server(
        self, mail_server: Self, allow_archived: bool, smtp_from: str | None
    ) -> None:
        """Validate that a forced outgoing mail server may be used.

        :param mail_server: the server explicitly forced by the caller.
        :param allow_archived: whether an archived server is acceptable.
        :param smtp_from: envelope sender; unused here but part of the override
            hook contract (the ``mail`` module uses it to forbid forcing a
            user-owned server whose ``from_filter`` does not match the sender).
        """
        if not allow_archived and not mail_server.active:
            raise UserError(
                _(
                    'The server "%s" cannot be used because it is archived.',
                    mail_server.display_name,
                )
            )

    def _smtp_login__(
        self, connection: smtplib.SMTP, smtp_user: str, smtp_password: str
    ) -> None:
        """Authenticate the SMTP connection.

        Can be overridden in other modules for different authentication methods.
        Can be called on the model itself or on a singleton.

        :param connection: the SMTP connection to authenticate
        :param smtp_user: the user for the authentication
        :param smtp_password: the password for the authentication
        """
        connection.login(smtp_user, smtp_password)

    def _build_email__(
        self,
        email_from: str | None,
        email_to: str | list[str],
        subject: str,
        body: str,
        email_cc: list[str] | None = None,
        email_bcc: list[str] | None = None,
        reply_to: str | bool = False,
        attachments: list[tuple[str, bytes, str]] | None = None,
        message_id: str | None = None,
        references: str | None = None,
        object_id: str | bool = False,
        subtype: str = "plain",
        headers: dict[str, str] | None = None,
        body_alternative: str | None = None,
        subtype_alternative: str = "plain",
    ) -> EmailMessage:
        """Construct an RFC2822 email message from the given arguments.

        :param str | None email_from: sender email address
        :param str | list[str] email_to: list of recipient addresses (to be joined with commas)
        :param str subject: email subject (no pre-encoding/quoting necessary)
        :param str body: email body, of the type ``subtype`` (by default, plaintext).
                            If html subtype is used, the message will be automatically converted
                            to plaintext and wrapped in multipart/alternative, unless an explicit
                            ``body_alternative`` version is passed.
        :param str | None body_alternative: optional alternative body, of the type specified in ``subtype_alternative``
        :param str | bool reply_to: optional value of Reply-To header
        :param str | bool object_id: optional tracking identifier, to be included in the message-id for
                                 recognizing replies. Suggested format for object-id is "res_id-model",
                                 e.g. "12345-crm.lead".
        :param str subtype: optional mime subtype for the text body (usually 'plain' or 'html'),
                               must match the format of the ``body`` parameter. Default is 'plain',
                               making the content part of the mail "text/plain".
        :param str subtype_alternative: optional mime subtype of ``body_alternative`` (usually 'plain'
                                           or 'html'). Default is 'plain'.
        :param list[tuple[str, bytes, str]] | None attachments: list of (filename, content, mimetype) tuples
        :param str | None message_id: optional value for the Message-Id header; generated when omitted
        :param str | None references: optional value for the References header (parent message ids)
        :param list[str] | None email_cc: optional list of string values for CC header (to be joined with commas)
        :param list[str] | None email_bcc: optional list of string values for BCC header (to be joined with commas)
        :param dict[str, str] | None headers: optional map of headers to set on the outgoing mail (may override the
                             other headers, including Subject, Reply-To, Message-Id, etc.)
        :rtype: EmailMessage
        :return: the new RFC2822 email message
        """
        email_from = (
            email_from
            or self.env.context.get("domain_notifications_email")
            or self._get_default_from_address()
        )
        if not email_from:
            raise OutgoingEmailError(self.NO_FOUND_FROM)

        headers = headers or {}  # need valid dict later
        email_cc = email_cc or []
        email_bcc = email_bcc or []

        msg = EmailMessage(policy=SMTP_POLICY)
        if not message_id:
            if object_id:
                message_id = tools.mail.generate_tracking_message_id(object_id)
            else:
                message_id = make_msgid()
        msg["Message-Id"] = message_id
        if references:
            msg["references"] = references
        msg["Subject"] = subject
        msg["From"] = email_from
        msg["Reply-To"] = reply_to or email_from
        msg["To"] = email_to
        if email_cc:
            msg["Cc"] = email_cc
        if email_bcc:
            msg["Bcc"] = email_bcc
        msg["Date"] = datetime.datetime.now(datetime.UTC)
        for key, value in headers.items():
            # ``headers`` is documented to *override* previously-set headers
            # (Subject, Reply-To, Message-Id, ...). Under EmailMessage/SMTP_POLICY
            # a plain ``msg[key] = value`` *appends*, and singleton headers cap at
            # one occurrence, so overriding any of them would raise ValueError
            # ("There may be at most 1 ... headers"). Delete first (no-op when
            # absent) so the override actually replaces, matching _alter_message__.
            del msg[key]
            msg[key] = value

        email_body = body or ""
        if subtype == "html" and not body_alternative:
            msg["MIME-Version"] = "1.0"
            msg.add_alternative(
                tools.html2plaintext(email_body),
                subtype="plain",
                charset="utf-8",
            )
            msg.add_alternative(email_body, subtype=subtype, charset="utf-8")
        elif body_alternative:
            msg["MIME-Version"] = "1.0"
            msg.add_alternative(
                body_alternative, subtype=subtype_alternative, charset="utf-8"
            )
            msg.add_alternative(email_body, subtype=subtype, charset="utf-8")
        else:
            msg.set_content(email_body, subtype=subtype, charset="utf-8")

        if attachments:
            for fname, fcontent, mime in attachments:
                # split on the first "/" only: a malformed mimetype with extra
                # slashes (e.g. "application/pdf/x") would otherwise raise
                # ValueError on unpacking. Local name avoids shadowing ``subtype``.
                maintype, att_subtype = (
                    mime.split("/", 1)
                    if mime and "/" in mime
                    else ("application", "octet-stream")
                )
                if maintype == "message" and att_subtype == "rfc822":
                    msg.add_attachment(
                        BytesParser().parsebytes(fcontent), filename=fname
                    )
                else:
                    msg.add_attachment(fcontent, maintype, att_subtype, filename=fname)
        return msg

    @api.model
    def _get_default_bounce_address(self) -> str | None:
        """Computes the default bounce address. It is used to set the envelop
        address if no envelop address is provided in the message.

        :return: defaults to the ``--email-from`` CLI/config parameter.
        :rtype: str | None
        """
        return tools.config.get("email_from")

    @api.model
    def _get_default_from_address(self) -> str | None:
        """Computes the default from address. It is used for the "header from"
        address when no other has been received.

        :return: defaults to the ``--email-from`` CLI/config parameter.
        :rtype: str | None
        """
        return tools.config.get("email_from")

    @api.model
    def _get_default_from_filter(self) -> str | None:
        """Computes the default from_filter. It is used when no specific
        ir.mail_server is used when sending emails, hence having no value for
        from_filter.

        :return: defaults to 'mail.default.from_filter', then
          ``--from-filter`` CLI/config parameter.
        :rtype: str | None
        """
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.default.from_filter", tools.config.get("from_filter"))
        )

    def _prepare_email_message__(
        self, message: EmailMessage, smtp_session: smtplib.SMTP
    ) -> tuple[str, list[str], EmailMessage]:
        """Prepare the SMTP information (from, to, message) before sending.

        :param message: the email.message.Message to send, information like the
            Return-Path, the From, etc... will be used to find the smtp_from and to smtp_to
        :param smtp_session: the opened SMTP session to use to authenticate the sender

        :return: smtp_from, smtp_to_list, message
            smtp_from: envelope sender (MAIL FROM) of the email
            smtp_to_list: list of recipient email addresses
            message: the email message to send
        """
        # Use the default bounce address **only if** no Return-Path was
        # provided by caller.  Caller may be using Variable Envelope Return
        # Path (VERP) to detect no-longer valid email addresses.
        # context may force a value, e.g. mail.alias.domain usage
        bounce_address = (
            self.env.context.get("domain_bounce_address")
            or message["Return-Path"]
            or self._get_default_bounce_address()
            or message["From"]
        )

        smtp_from = message["From"] or bounce_address
        if not smtp_from:
            raise OutgoingEmailError(self.NO_FOUND_SMTP_FROM)

        smtp_to_list = self._prepare_smtp_to_list(message, smtp_session)
        if not smtp_to_list:
            raise OutgoingEmailError(self.NO_VALID_RECIPIENT)

        # Try to not spoof the mail from headers; fetch session-based or contextualized
        # values for encapsulation computation
        session_context = self._read_session_context(smtp_session)
        from_filter = session_context.from_filter
        smtp_from = session_context.smtp_from or smtp_from
        notifications_email = email_normalize(
            self.env.context.get("domain_notifications_email")
            or self._get_default_from_address()
        )
        if (
            notifications_email
            and email_normalize(smtp_from) == notifications_email
            and email_normalize(message["From"]) != notifications_email
        ):
            smtp_from = encapsulate_email(message["From"], notifications_email)

        # alter message
        self._alter_message__(message, smtp_from, smtp_to_list)

        # Check if it's still possible to put the bounce address as smtp_from
        if self._match_from_filter(bounce_address, from_filter):
            # Mail headers FROM will be spoofed to be able to receive bounce notifications
            # Because the mail server support the domain of the bounce address
            smtp_from = bounce_address

        # The email's "Envelope From" (Return-Path) must only contain ASCII characters.
        smtp_from_rfc2822 = extract_rfc2822_addresses(smtp_from)
        if not smtp_from_rfc2822:
            # ``code`` classifies the failure (mail_from_invalid); the message
            # names the offending address and becomes the stored failure_reason.
            raise OutgoingEmailError(  # pylint: disable=missing-gettext
                f"Malformed 'Return-Path' or 'From' address: {smtp_from} - "
                "It should contain one valid plain ASCII email",
                code=self.NO_VALID_FROM,
            )
        smtp_from = smtp_from_rfc2822[-1]

        return smtp_from, smtp_to_list, message

    @api.model
    def _alter_message__(
        self, message: EmailMessage, smtp_from: str, smtp_to_list: list[str]
    ) -> None:
        # `To:` header forged, e.g. for posting on discuss.channels, to avoid confusion
        if x_forge_to := message["X-Forge-To"]:
            # del is a no-op on missing headers; avoids KeyError from replace_header()
            del message["To"]
            message["To"] = x_forge_to
        # `To:` header extended, e.g. for adding "virtual" recipients, aka fake recipients
        # that do not impact SMTP To
        elif x_msg_add_to := message["X-Msg-To-Add"]:
            to = message["To"] or ""
            to_normalized = tools.mail.email_normalize_all(to)
            del message["To"]
            message["To"] = ", ".join(
                [
                    to,
                    ", ".join(
                        address
                        for address in tools.mail.email_split_and_format(x_msg_add_to)
                        if tools.mail.email_normalize(address, strict=False)
                        not in to_normalized
                    ),
                ]
            )

        if message["From"] != smtp_from:
            del message["From"]
            message["From"] = smtp_from

        # cleanup unwanted headers
        del message["Bcc"]  # see odoo/odoo@2445f9e3c22db810d61996afde883e4ca608f15b
        del message["X-Forge-To"]
        del message["X-Msg-To-Add"]
        del message["X-Msg-To-Consolidate"]

    @api.model
    def _prepare_smtp_to_list(
        self, message: EmailMessage, smtp_session: smtplib.SMTP
    ) -> list[str]:
        """Prepare SMTP To address list, based on To / Cc / Bcc.

        Optional 'send_validated_to' context key filter restricts addresses to
        be part of that list.

        Optional 'send_smtp_skip_to' context key holds a recipients block list
        """
        email_to = message["To"]
        email_cc = message["Cc"]
        email_bcc = message["Bcc"]

        # Support optional pre-validated To list, used notably when formatted
        # emails may create fake emails using extract_rfc2822_addresses, e.g.
        # '"Bike@Home" <email@domain.com>' which can be considered as containing
        # 2 emails by extract_rfc2822_addresses
        validated_to = self.env.context.get("send_validated_to") or []

        # Support optional skip To list
        skip_to_lst = self.env.context.get("send_smtp_skip_to") or []

        # All recipient addresses must only contain ASCII characters
        return [
            address
            for base in [email_to, email_cc, email_bcc]
            # be sure a given address does not return duplicates (but duplicates
            # in final smtp to list is still ok)
            for address in tools.misc.unique(extract_rfc2822_addresses(base))
            if (
                address
                and (not validated_to or address in validated_to)
                and email_normalize(address, strict=False) not in skip_to_lst
            )
        ]

    @api.model
    def send_email(
        self,
        message: EmailMessage,
        mail_server_id: int | None = None,
        smtp_server: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        smtp_encryption: str | None = None,
        smtp_ssl_certificate: str | None = None,
        smtp_ssl_private_key: str | None = None,
        smtp_debug: bool = False,
        smtp_session: smtplib.SMTP | None = None,
    ) -> str:
        """Sends an email directly (no queuing).

        No retries are done, the caller should handle MailDeliveryException in order to ensure that
        the mail is never lost.

        If the mail_server_id is provided, sends using this mail server, ignoring other smtp_* arguments.
        If mail_server_id is None and smtp_server is None, use the default mail server (highest priority).
        If mail_server_id is None and smtp_server is not None, use the provided smtp_* arguments.
        If both mail_server_id and smtp_server are None, look for an 'smtp_server' value in server config,
        and fails if not found.

        :param message: the email.message.Message to send. The envelope sender will be extracted from the
                        ``Return-Path`` (if present), or will be set to the default bounce address.
                        The envelope recipients will be extracted from the combined list of ``To``,
                        ``CC`` and ``BCC`` headers.
        :param smtp_session: optional pre-established SMTP session. When provided,
                             overrides `mail_server_id` and all the `smtp_*` parameters.
                             Passing the matching `mail_server_id` may yield better debugging/log
                             messages. The caller is in charge of disconnecting the session.
        :param mail_server_id: optional id of ir.mail_server to use for sending. overrides other smtp_* arguments.
        :param smtp_server: optional hostname of SMTP server to use
        :param smtp_encryption: optional TLS mode, one of 'none', 'starttls', 'starttls_strict', 'ssl', or 'ssl_strict'.
            The 'strict' variants verify the remote server's certificate against the operating system trust store.
        :param smtp_port: optional SMTP port, if mail_server_id is not passed
        :param smtp_user: optional SMTP user, if mail_server_id is not passed
        :param smtp_password: optional SMTP password to use, if mail_server_id is not passed
        :param smtp_ssl_certificate: filename of the SSL certificate used for authentication
        :param smtp_ssl_private_key: filename of the SSL private key used for authentication
        :param smtp_debug: optional SMTP debug flag, if mail_server_id is not passed
        :return: the Message-ID of the message that was just sent, if successfully sent, otherwise raises
                 MailDeliveryException and logs root cause.
        """
        smtp = smtp_session
        # A caller-supplied smtp_session is the caller's to disconnect (see
        # docstring); a connection we open here is ours to always close, even
        # when preparation or delivery raises — otherwise the socket leaks.
        owns_connection = not smtp_session
        if not smtp:
            smtp = self._connect__(
                smtp_server,
                smtp_port,
                smtp_user,
                smtp_password,
                smtp_encryption,
                smtp_from=message["From"],
                ssl_certificate=smtp_ssl_certificate,
                ssl_private_key=smtp_ssl_private_key,
                smtp_debug=smtp_debug,
                mail_server_id=mail_server_id,
            )

        try:
            smtp_from, smtp_to_list, message = self._prepare_email_message__(
                message, smtp
            )

            # Do not actually send emails in testing mode!
            if self._disable_send():
                _test_logger.debug("skip sending email in test mode")
                return message["Message-Id"]

            message_id = message["Message-Id"]
            try:
                smtp.send_message(message, smtp_from, smtp_to_list)
            except smtplib.SMTPServerDisconnected:
                raise
            except Exception as e:
                msg = _(
                    "Mail delivery failed via SMTP server '%(server)s'.\n%(exception_name)s: %(message)s",
                    server=smtp_server or getattr(smtp, "_host", "unknown"),
                    exception_name=e.__class__.__name__,
                    message=e,
                )
                # WARNING (not INFO) so production log levels see delivery
                # failures, with the SMTP traceback; chaining ``from e`` keeps
                # the root cause on the raised error without changing its
                # rendered message (= the stored mail.mail failure_reason).
                _logger.warning(msg, exc_info=True)
                raise MailDeliveryError(_("Mail Delivery Failed"), msg) from e
            return message_id
        finally:
            # ``smtp`` is None in test mode (_connect__ short-circuits).
            if owns_connection and smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    # QUIT over a dead socket may raise before close(); force it.
                    with suppress(Exception):
                        smtp.close()

    def _find_mail_server_allowed_domain(self) -> list[Any]:
        """Overridable domain getter for all mail servers that may be used as default."""
        return fields.Domain.TRUE

    def _find_mail_server(
        self, email_from: str | None, mail_servers: Self | None = None
    ) -> tuple[Self | None, str]:
        """Find the appropriate mail server for the given email address.

        :rtype: tuple[Self | None, str]
        :returns: A two-elements tuple: ``(Record<ir.mail_server>, email_from)``

          1. Mail server to use to send the email (``None`` if we use the odoo-bin arguments)
          2. Email FROM to use to send the email (in some case, it might be impossible
             to use the given email address directly if no mail server is configured for)
        """
        email_from_normalized = email_normalize(email_from)
        email_from_domain = email_domain_extract(email_from_normalized)
        notifications_email = self.env.context.get(
            "domain_notifications_email"
        ) or email_normalize(self._get_default_from_address())
        notifications_domain = email_domain_extract(notifications_email)

        if mail_servers is None:
            mail_servers = self.sudo().search(
                self._find_mail_server_allowed_domain(), order="sequence"
            )
        # 0. Archived mail server should never be used
        mail_servers = mail_servers.filtered("active")

        # Parse each server's from_filter at most once: ``first_match`` is called
        # up to four times below and every call would otherwise re-split the same
        # comma-separated strings for every candidate server.
        parsed_filters: dict[int, list[str]] = {}

        def filter_parts(mail_server: Self) -> list[str]:
            parts = parsed_filters.get(mail_server.id)
            if parts is None:
                parts = parsed_filters[mail_server.id] = self._parse_from_filter(
                    mail_server.from_filter
                )
            return parts

        def first_match(target, normalize_method):
            for mail_server in mail_servers:
                if any(
                    normalize_method(part) == target
                    for part in filter_parts(mail_server)
                ):
                    return mail_server
            return None

        # 1. Try to find a mail server for the right mail from
        # Skip if passed email_from is False (example Odoobot has no email address)
        if email_from_normalized:
            if mail_server := first_match(email_from_normalized, email_normalize):
                return mail_server, email_from

            if mail_server := first_match(email_from_domain, email_domain_normalize):
                return mail_server, email_from

        mail_servers = self._filter_mail_servers_fallback(mail_servers)

        # 2. Try to find a mail server for <notifications@domain.com>
        if notifications_email:
            if mail_server := first_match(notifications_email, email_normalize):
                return mail_server, notifications_email

            if mail_server := first_match(notifications_domain, email_domain_normalize):
                return mail_server, notifications_email

        # 3. Take the first mail server without "from_filter" because
        # nothing else has been found... Will spoof the FROM because
        # we have no other choices (will use the notification email if available
        # otherwise we will use the user email)
        if mail_server := mail_servers.filtered(lambda m: not m.from_filter):
            return mail_server[0], notifications_email or email_from

        # 4. Return the first mail server even if it was configured for another domain
        if mail_servers:
            _logger.warning(
                "No mail server matches the from_filter, using %s as fallback",
                notifications_email or email_from,
            )
            return mail_servers[0], notifications_email or email_from

        # 5: SMTP config in odoo-bin arguments
        from_filter = self.env["ir.mail_server"]._get_default_from_filter()

        if self._match_from_filter(email_from, from_filter):
            return None, email_from

        if notifications_email and self._match_from_filter(
            notifications_email, from_filter
        ):
            return None, notifications_email

        _logger.warning(
            "The from filter of the CLI configuration does not match the notification email "
            "or the user email, using %s as fallback",
            notifications_email or email_from,
        )
        return None, notifications_email or email_from

    @api.model
    def _filter_mail_servers_fallback(self, servers: Self) -> Self:
        """Filter the mail servers that can be used as fallback, or for default email from."""
        return servers

    @api.model
    def _match_from_filter(
        self, email_from: str | None, from_filter: str | None
    ) -> bool:
        """Return True if the given email address matches the "from_filter" field.

        The from filter can be Falsy (always match),
        a domain name or a full email address.
        """
        if not from_filter:
            return True

        normalized_mail_from = email_normalize(email_from)
        normalized_domain = email_domain_extract(normalized_mail_from)

        for email_filter in self._parse_from_filter(from_filter):
            if (
                "@" in email_filter
                and email_normalize(email_filter) == normalized_mail_from
            ):
                return True
            if (
                "@" not in email_filter
                and email_domain_normalize(email_filter) == normalized_domain
            ):
                return True
        return False

    @api.model
    def _parse_from_filter(self, from_filter: str | None) -> list[str]:
        return [part.strip() for part in (from_filter or "").split(",") if part.strip()]

    @api.onchange("smtp_encryption")
    def _onchange_encryption(self) -> None:
        # Only rewrite the port when it still holds the default of the mode
        # being left (25 for none/starttls, 465 for ssl); a user-entered custom
        # port (e.g. 587 or 2525) must survive an encryption toggle.
        #
        # The historical "SMTP_SSL not in smtplib.__all__" warning branch was
        # dead code on this stack: this module imports ``ssl`` unconditionally,
        # so on an ssl-less Python it would fail to import long before the
        # onchange could run (and smtplib always exposes SMTP_SSL when ssl is
        # importable).
        if self.smtp_encryption in ("ssl", "ssl_strict"):
            if self.smtp_port == 25:
                self.smtp_port = 465
        elif self.smtp_port == 465:
            self.smtp_port = 25
