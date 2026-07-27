import base64
import copy
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
from cryptography.x509 import load_pem_x509_certificates
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

# Fallback for the --smtp-timeout option, used when the option is absent (a unit
# test running without a parsed configuration).
SMTP_TIMEOUT = 60

# Loading admin-supplied PEM material fails with a different exception per backend:
# `cryptography` raises ValueError (binascii.Error for bad base64), pyOpenSSL raises
# SSLCryptoError, and PyOpenSSLContext.load_cert_chain re-raises as ssl.SSLError.
# All of them mean "bad certificate/key" and must surface as a UserError.
CERTIFICATE_LOAD_ERRORS = (
    SSLCryptoError,
    SSLError,
    ssl.SSLError,
    ValueError,
    TypeError,
)


class MailDeliveryError(Exception):
    """Mail delivery error.

    Message and optional detail are passed as separate positional args; ``str()``
    joins them with newlines so ``str(exc)`` (stored as ``mail.mail.failure_reason``)
    is clean multi-line text, not a tuple repr. ``.args`` is left untouched.
    """

    def __str__(self) -> str:
        return "\n".join(str(arg) for arg in self.args)


MailDeliveryException = MailDeliveryError


class OutgoingEmailError(UserError):
    """User-facing error raised while resolving/preparing an outgoing email.

    Carries a stable, non-translated ``code`` (one of the ``NO_*`` constants on
    :class:`IrMail_Server`) so queue processors like ``mail.mail`` can classify
    the failure without matching on the display text (which may be translated or
    detail-augmented).
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        self.code = code or message
        super().__init__(message)


def _log_smtp_debug(*args: Any) -> None:
    """Drop-in replacement for ``smtplib.SMTP._print_debug``.

    smtplib ``print()``s the session transcript straight to ``sys.stderr``,
    which bypasses ``--logfile``, the log level and every handler -- so on a
    server that logs to a file, enabling ``smtp_debug`` produced nothing in the
    log and leaked the AUTH exchange to stderr instead.
    """
    _logger.debug("%s", " ".join(str(arg) for arg in args))


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

    if err_depth == 0:
        peercert = {
            "subject": ((("commonName", x509.get_subject().CN),),),
            "subjectAltName": get_subj_alt_name(x509),
        }
        match_hostname(peercert, hostname)

    return True


class _SmtpTransport(NamedTuple):
    """Fully-resolved SMTP transport parameters, output of
    :meth:`IrMail_Server._resolve_smtp_transport`.

    Separating resolution (which config source wins, which SSL context to build)
    from the socket I/O in ``_connect__`` makes it unit-testable without a
    connection and funnels both config sources through one place so their
    SSL/verify handling cannot drift apart.
    """

    server: str | None
    port: int | None
    user: str | None
    password: str | None
    encryption: str | None
    debug: bool
    from_filter: str | None
    ssl_context: ssl.SSLContext | PyOpenSSLContext | None
    login_server: IrMail_Server
    timeout: float | None = SMTP_TIMEOUT


class _FromFilter(NamedTuple):
    """A ``from_filter`` reduced to the normalized senders it authorizes.

    ``emails`` holds whole addresses and ``domains`` whole domains; ``unparsed``
    counts the entries that are neither (e.g. ``"@@@"``). A filter is
    *unrestricted* only when it holds nothing at all -- separators and
    whitespace alone are not a restriction, but an entry that cannot be
    interpreted must never widen what a server may send as, so it is kept as a
    restriction that matches nothing.
    """

    emails: frozenset[str]
    domains: frozenset[str]
    unparsed: int = 0

    @property
    def unrestricted(self) -> bool:
        return not (self.emails or self.domains or self.unparsed)

    def matches(self, normalized_email: str | bool) -> bool:
        if self.unrestricted:
            return True
        return bool(normalized_email) and (
            normalized_email in self.emails
            or email_domain_extract(normalized_email) in self.domains
        )


class _SmtpSessionContext(NamedTuple):
    """Per-connection routing context, consulted by
    :meth:`IrMail_Server._prepare_email_message__` when deciding whether the
    envelope FROM may be rewritten so bounces come back (VERP / bounce alias).

    - ``from_filter``: which senders the selected server / CLI config may send as.
    - ``smtp_from``: envelope sender resolved while choosing the server.

    Carried as flat attributes on the smtp connection (not a wrapper) because
    ``send_email`` accepts a caller-supplied session whose ``quit()`` etc. must
    run on the real connection ``_connect__`` returns; test doubles in
    ``base/tests/common.py`` read these names too. Access goes through
    :meth:`_stash_session_context` / :meth:`_read_session_context` to keep the
    contract in one place.
    """

    from_filter: str | bool = False
    smtp_from: str | bool = False


class IrMail_Server(models.Model):
    """Represents an SMTP server, able to send outgoing emails, with SSL and TLS capabilities."""

    _name = "ir.mail_server"
    _description = "Mail Server"
    _order = "sequence, id"
    _allow_sudo_commands = False

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
        help="If enabled, the SMTP session transcript is written to the Odoo "
        "log at DEBUG level, from the first command after the connection is "
        "open (this is very verbose and includes the authentication exchange!). "
        "DEBUG logging must also be enabled for it to appear, e.g. "
        "--log-handler=odoo.addons.base.models.ir_mail_server:DEBUG",
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
                mail_server._load_certificate_material()

    def write(self, vals: dict[str, Any]) -> bool:
        """Prevent archiving a server that is still in use."""
        if not vals.get("active", True):
            self._check_archivable()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_use(self) -> None:
        """Prevent deleting a server that is still in use.

        Every reference to this model is a plain many2one with the default
        ``ondelete='set null'``, so without this guard deleting a server that
        :meth:`write` refuses to *archive* silently unhooks it from the mail
        templates and mailings that were sending through it. ``at_uninstall``
        is off so uninstalling the module that declared the usage still works.
        """
        self._check_archivable(deleting=True)

    def _check_archivable(self, deleting: bool = False) -> None:
        """Raise if any server in ``self`` is still referenced by an active usage.

        Only the servers actually being archived are reported: an override of
        :meth:`_active_usages_compute` that also describes servers outside
        ``self`` must not block the write, nor pluralize the message.
        """
        usages_per_server = self._active_usages_compute()
        servers = sorted(
            (server for server in self if usages_per_server.get(server.id)),
            key=lambda server: server.display_name,
        )
        if not servers:
            return

        is_multiple_server_usage = len(servers) > 1
        usage_details = []
        for server in servers:
            if is_multiple_server_usage:
                usage_details.append(
                    _(
                        "%s (Dedicated Outgoing Mail Server):",
                        server.display_name,
                    )
                )
            usage_details.extend(f"- {u}" for u in usages_per_server[server.id])

        # The four variants are spelled out because the translation extractor
        # only collects string literals passed directly to _().
        details = {
            "server_usage": ", ".join(server.display_name for server in servers),
            "usage_details": "\n".join(usage_details),
        }
        if deleting and is_multiple_server_usage:
            message = _(
                "You cannot delete these Outgoing Mail Servers (%(server_usage)s) because they are still used in the following case(s):\n%(usage_details)s",
                **details,
            )
        elif deleting:
            message = _(
                "You cannot delete this Outgoing Mail Server (%(server_usage)s) because it is still used in the following case(s):\n%(usage_details)s",
                **details,
            )
        elif is_multiple_server_usage:
            message = _(
                "You cannot archive these Outgoing Mail Servers (%(server_usage)s) because they are still used in the following case(s):\n%(usage_details)s",
                **details,
            )
        else:
            message = _(
                "You cannot archive this Outgoing Mail Server (%(server_usage)s) because it is still used in the following case(s):\n%(usage_details)s",
                **details,
            )
        raise UserError(message)

    def _active_usages_compute(self) -> dict[int, list[str]]:
        """Map each server id to user-friendly descriptions of its active usages.

        Override in modules that use this model to list the active elements that
        could send mail through a server in this recordset.

        :return: ``{ir_mail_server.id: usage_str_list}``
        :rtype: dict[int, list[str]]
        """
        return {}

    def _get_max_email_size(self, smtp_session: smtplib.SMTP | None = None) -> float:
        """Return the maximum size, in MB, of an email sent through this server.

        Callable on the empty recordset (no server selected), which falls back to
        the ``base.default_max_email_size`` parameter.

        When a session is given, the smaller of the configured value and the size
        the peer advertised in EHLO (RFC 1870) wins. Both bounds are real and
        neither subsumes the other: ``max_email_size`` is a policy an admin may
        deliberately set below what the provider accepts (it decides when
        attachments become links), while the advertised value is what the
        provider will enforce *now* -- the stored one is a snapshot somebody had
        to refresh by hand, and once the provider tightens its limit, every mail
        above it fails at DATA instead of being converted to links.
        """
        configured = self.max_email_size or (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_float("base.default_max_email_size", 10.0)
        )
        advertised = self._session_max_email_size(smtp_session)
        return min(configured, advertised) if advertised else configured

    @staticmethod
    def _session_max_email_size(smtp_session: smtplib.SMTP | None) -> float | None:
        """Size limit, in MB, the session advertised in EHLO, if any.

        ``SIZE`` is optional and may be advertised without a value ("this server
        supports the extension but declares no limit"), which is not a limit of
        zero.
        """
        size = (getattr(smtp_session, "esmtp_features", None) or {}).get("size")
        try:
            return float(size) / 1024**2 or None
        except TypeError, ValueError:
            return None

    def _from_filter_sender(self) -> str | None:
        """First whole address this server's ``from_filter`` authorizes.

        Order follows the admin-typed filter, so the answer is stable; parts
        that are not parseable addresses are skipped rather than handed to
        ``MAIL FROM`` on the strength of containing an ``@``.
        """
        self.ensure_one()
        return next(
            (
                normalized
                for part in self._parse_from_filter(self.from_filter)
                if (normalized := email_normalize(part))
            ),
            None,
        )

    def _from_filter_domain(self) -> str | None:
        """First whole domain this server's ``from_filter`` authorizes."""
        self.ensure_one()
        return next(
            (
                normalized
                for part in self._parse_from_filter(self.from_filter)
                if "@" not in part and (normalized := email_domain_normalize(part))
            ),
            None,
        )

    def _get_test_email_from(self) -> str:
        self.ensure_one()
        email_from = self._from_filter_sender()
        if not email_from and (domain := self._from_filter_domain()):
            email_from = f"noreply@{domain}"
        if not email_from:
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
        # Read access is granted well beyond system users (mass mailing users
        # get it, for instance) and this opens an authenticated session using
        # credentials those users cannot read, reporting reachability and
        # certificate details back to them. Autodetection also writes.
        self.check_access("write")
        if self._disable_send():
            raise UserError(
                _(
                    "Testing the SMTP connection is not possible because "
                    "outgoing emails are disabled (test mode or registry "
                    "initialization)."
                )
            )
        for server in self:
            smtp = None
            try:
                email_from = server._get_test_email_from()
                email_to = server._get_test_email_to()
                smtp = self._connect__(
                    mail_server_id=server.id,
                    allow_archived=True,
                    smtp_from=email_from,
                )
                code, repl = smtp.mail(email_from)
                if code != 250:
                    raise UserError(
                        _(
                            "The server refused the sender address (%(email_from)s) with error %(repl)s",
                            email_from=email_from,
                            repl=repl,
                        )
                    )
                code, repl = smtp.rcpt(email_to)
                if code not in (250, 251):
                    raise UserError(
                        _(
                            "The server refused the test recipient (%(email_to)s) with error %(repl)s",
                            email_to=email_to,
                            repl=repl,
                        )
                    )
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
                raise
            except Exception as e:
                raise self._connection_test_error(e, server) from e
            finally:
                if smtp is not None:
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
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _connection_test_error(self, exc: Exception, server: Self) -> UserError:
        """Translate a raw connection-test exception into a user-facing UserError.

        Ordered most-specific first: SMTP subclasses must precede
        ``smtplib.SMTPException`` so their tailored message wins. An unmatched
        exception is logged with traceback and wrapped in a generic message.

        ``UnicodeError`` covers the whole ``idna`` family (``idna.IDNAError``
        derives from it), which is what a non-encodable SMTP username domain
        raises out of :meth:`_open_smtp_connection`.

        The trailing ``OSError`` entry must stay last: ``smtplib.SMTPException``
        and ``ssl.SSLError`` both derive from it, so hoisting it would swallow
        every tailored message above.
        """
        handlers = (
            (
                UnicodeError,
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
                ConnectionError,
                lambda e: _(
                    "Could not establish a connection. Check the port number, and "
                    "that the server is reachable and accepts connections from "
                    "this machine.\n %s",
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
            (
                OSError,
                lambda e: _(
                    "The connection to the server failed. Check the server "
                    "address, the port number and your network.\n %s",
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
        """Whether email sending is disabled (during testing or registry init)."""
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
        resolve_server: bool = True,
    ) -> smtplib.SMTP | smtplib.SMTP_SSL | None:
        """Return a new SMTP connection to the given server, or ``None`` in test mode.

        :param str | None host: host or IP of the SMTP server, if mail_server_id not passed
        :param str | None encryption: ``'none'`` | ``'ssl'`` | ``'ssl_strict'`` | ``'starttls'`` | ``'starttls_strict'``.
            The 'strict' variants verify the server certificate against the OS trust store.
        :param smtp_from: FROM SMTP envelope, used to find the best mail server
        :param ssl_certificate: SSL certificate filename; used when no mail server
            is given, overrides ``--smtp-ssl-certificate-filename``
        :param ssl_private_key: SSL private key filename; used when no mail server
            is given, overrides ``--smtp-ssl-private-key-filename``
        :param mail_server_id: id of a specific mail server (overrides other parameters)
        :param bool allow_archived: if True, don't raise on an archived record
            (for testing)
        :param bool resolve_server: whether a falsy ``mail_server_id`` means "not
            resolved yet, pick a server now". Callers that already ran
            :meth:`_find_mail_server` -- ``mail.mail`` groups its batches by the
            outcome -- pass False, so a falsy id keeps its other meaning,
            "resolved: no server applies, use the CLI/config transport". Without
            it the search runs again for every batch, and agrees with the
            grouping only for as long as the caller keeps re-supplying the exact
            context it resolved under.
        """
        if self._disable_send():
            return None

        mail_server = None
        if mail_server_id:
            mail_server = self.sudo().browse(mail_server_id)
            self._check_forced_mail_server(mail_server, allow_archived, smtp_from)
        elif resolve_server and not host:
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

        Opens no connection, so it is directly unit-testable. Both config sources
        funnel their encryption->SSL-context decision through here, keeping the
        'strict' verification semantics from drifting between them.

        :param mail_server: resolved ``ir.mail_server`` record, or the empty
            recordset when the transport comes from CLI/config/params.
        """
        if mail_server and mail_server.smtp_authentication != "cli":
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
                timeout=self._get_smtp_timeout(),
            )

        if encryption is None and tools.config.get("smtp_ssl"):
            encryption = "starttls"

        cert_filename = ssl_certificate or tools.config.get(
            "smtp_ssl_certificate_filename"
        )
        key_filename = ssl_private_key or tools.config.get(
            "smtp_ssl_private_key_filename"
        )
        server = host or tools.config.get("smtp_server")
        if cert_filename and key_filename:
            if encryption in (None, "none"):
                _logger.warning(
                    "An SMTP client certificate is configured (%s) but the "
                    "transport to %s is unencrypted, so it will not be "
                    "presented; enable --smtp-ssl or pick an encryption mode.",
                    cert_filename,
                    server,
                )
            ssl_context = self._ssl_context_from_cert_files(
                cert_filename, key_filename, encryption, server
            )
        elif encryption not in (None, "none"):
            ssl_context = self._ssl_context_for_encryption(encryption)
        else:
            ssl_context = None

        return _SmtpTransport(
            server=server,
            port=tools.config.get("smtp_port", 25) if port is None else port,
            user=user or tools.config.get("smtp_user"),
            password=password or tools.config.get("smtp_password"),
            encryption=encryption,
            debug=smtp_debug or mail_server.smtp_debug,
            from_filter=(
                mail_server.from_filter
                if mail_server
                else self.env["ir.mail_server"]._get_default_from_filter()
            ),
            ssl_context=ssl_context,
            login_server=mail_server,
            timeout=self._get_smtp_timeout(),
        )

    @staticmethod
    def _get_smtp_timeout() -> float | None:
        """Socket timeout, in seconds, applied to every SMTP command.

        ``None`` (from ``--smtp-timeout 0``) blocks indefinitely. The timeout is
        per command, not per session, so a batch of N mails on one session can
        legitimately take far longer than this.
        """
        return tools.config.get("smtp_timeout", SMTP_TIMEOUT) or None

    @staticmethod
    def _get_smtp_local_hostname() -> str | None:
        """Hostname to announce in HELO/EHLO, or ``None`` to let smtplib decide.

        smtplib derives it from ``socket.getfqdn()``, which on a container or
        any host whose name does not resolve to a dotted FQDN degrades to a
        domain literal such as ``[172.17.0.2]``. MTAs that require a
        fully-qualified HELO reject the whole session for it, and the lookup
        also happens with the socket already open, outside ``--smtp-timeout``.
        """
        return tools.config.get("smtp_helo_name") or None

    def _open_smtp_connection(
        self, transport: _SmtpTransport, smtp_from: str | None
    ) -> smtplib.SMTP | smtplib.SMTP_SSL:
        """Open, secure and authenticate a socket for a resolved transport.

        Stashes ``from_filter`` / ``smtp_from`` on the returned connection for
        :meth:`_prepare_email_message__` (deciding whether the envelope FROM may
        be spoofed to receive bounces).
        """
        if not transport.server:
            raise UserError(
                _(
                    "Missing SMTP Server\n"
                    "Please define at least one SMTP server, "
                    "or provide the SMTP parameters explicitly.",
                )
            )

        local_hostname = self._get_smtp_local_hostname()
        if transport.encryption in ("ssl", "ssl_strict"):
            connection = smtplib.SMTP_SSL(
                transport.server,
                transport.port,
                local_hostname=local_hostname,
                timeout=transport.timeout,
                context=transport.ssl_context,
            )
        else:
            connection = smtplib.SMTP(
                transport.server,
                transport.port,
                local_hostname=local_hostname,
                timeout=transport.timeout,
            )
        try:
            if transport.debug:
                connection._print_debug = _log_smtp_debug
            connection.set_debuglevel(transport.debug)
            if transport.encryption in ("starttls", "starttls_strict"):
                connection.starttls(context=transport.ssl_context)

            if transport.user:
                smtp_user = transport.user
                local, at, domain = smtp_user.rpartition("@")
                if at:
                    smtp_user = local + at + idna.encode(domain).decode("ascii")
                transport.login_server._smtp_login__(
                    connection, smtp_user, transport.password or ""
                )

            connection.ehlo_or_helo_if_needed()
        except Exception:
            connection.close()
            raise

        self._stash_session_context(
            connection,
            _SmtpSessionContext(from_filter=transport.from_filter, smtp_from=smtp_from),
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
    def _session_supports_smtputf8(smtp_session: smtplib.SMTP | None) -> bool:
        """Whether the session can carry non-ASCII envelope addresses (RFC 6531).

        A session with no ESMTP feature map -- ``None`` in test mode, or a test
        double -- is assumed capable, so the ASCII rule only ever fires on a
        real connection that has told us, via EHLO, that it is not.
        """
        features = getattr(smtp_session, "esmtp_features", None)
        if features is None:
            return True
        return "smtputf8" in features

    @staticmethod
    def _read_session_context(smtp_session: smtplib.SMTP) -> _SmtpSessionContext:
        """Read the :class:`_SmtpSessionContext` stashed on a session.

        A never-stashed session (e.g. a raw smtplib connection passed straight to
        ``send_email``) yields the default ``(False, False)``.
        """
        return _SmtpSessionContext(
            from_filter=getattr(smtp_session, "from_filter", False),
            smtp_from=getattr(smtp_session, "smtp_from", False),
        )

    @staticmethod
    def _ssl_load_error(exc: Exception) -> UserError:
        """Translate a low-level certificate/key loading error into a UserError.

        Shared by every certificate-loading path so the messages live in one place.
        """
        if isinstance(exc, (SSLCryptoError, ssl.SSLError, ValueError)):
            return UserError(
                _(
                    "The private key or the certificate is not a valid file. \n%s",
                    str(exc),
                )
            )
        return UserError(
            _("Could not load your certificate / private key. \n%s", str(exc))
        )

    @staticmethod
    def _client_ssl_context(
        encryption: str | None, smtp_server: str | None
    ) -> PyOpenSSLContext:
        """Build the client-auth SSL context implied by ``encryption``, before any
        certificate material is loaded into it.

        Single source of truth for the peer/hostname verification policy, so the
        stored-certificate and certificate-file paths cannot drift apart.
        """
        ssl_context = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if encryption in ("ssl_strict", "starttls_strict"):
            ssl_context.set_default_verify_paths()
            ssl_context._ctx.set_verify(
                VERIFY_PEER | VERIFY_FAIL_IF_NO_PEER_CERT,
                functools.partial(
                    _verify_check_hostname_callback,
                    hostname=smtp_server,
                ),
            )
        else:
            ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def _load_certificate_material(self) -> tuple[list[Any], Any]:
        """Parse this server's stored PEM material into ``(chain, private_key)``.

        The whole PEM is loaded, not just its first block: CAs and ACME clients
        hand out ``fullchain.pem`` (leaf followed by the intermediates), and a
        server that cannot build a path to its trust anchor from the leaf alone
        rejects the client certificate. This mirrors what ``load_cert_chain``
        already does for the certificate-file path.

        Called from :meth:`_check_smtp_ssl_files` as well as from the SSL
        context builder, so material that cannot be used is refused when it is
        saved rather than hours later, from inside a cron send, as a delivery
        failure nobody is watching.
        """
        self.ensure_one()
        try:
            chain = load_pem_x509_certificates(
                base64.b64decode(self.smtp_ssl_certificate)
            )
            private_key = load_pem_private_key(
                base64.b64decode(self.smtp_ssl_private_key), password=None
            )
        except CERTIFICATE_LOAD_ERRORS as e:
            raise self._ssl_load_error(e) from None
        if chain[0].public_key() != private_key.public_key():
            raise UserError(
                _(
                    "The SSL certificate of %s does not match its private key.",
                    self.display_name,
                )
            )
        return chain, private_key

    def _ssl_context_from_certificate(
        self, mail_server: Self, smtp_server: str
    ) -> PyOpenSSLContext:
        """Build a client-auth SSL context from a mail server's stored PEM
        certificate/private key (``smtp_authentication == 'certificate'``).

        'strict' variants verify the peer and its hostname; lax variants don't.
        """
        ssl_context = self._client_ssl_context(mail_server.smtp_encryption, smtp_server)
        (leaf, *intermediates), private_key = mail_server._load_certificate_material()
        try:
            ssl_context._ctx.use_certificate(leaf)
            for intermediate in intermediates:
                ssl_context._ctx.add_extra_chain_cert(intermediate)
            ssl_context._ctx.use_privatekey(private_key)
        except CERTIFICATE_LOAD_ERRORS as e:
            raise self._ssl_load_error(e) from None
        return ssl_context

    def _ssl_context_from_cert_files(
        self,
        cert_filename: str,
        key_filename: str,
        encryption: str | None = None,
        smtp_server: str | None = None,
    ) -> PyOpenSSLContext:
        """Build a client-auth SSL context from certificate/key files on disk
        (CLI/config ``--smtp-ssl-*-filename`` arguments).

        'strict' variants verify the peer and its hostname (mirroring
        :meth:`_ssl_context_from_certificate`); lax variants don't.
        """
        ssl_context = self._client_ssl_context(encryption, smtp_server)
        try:
            ssl_context.load_cert_chain(cert_filename, keyfile=key_filename)
            ssl_context._ctx.check_privatekey()
        except CERTIFICATE_LOAD_ERRORS as e:
            raise self._ssl_load_error(e) from None
        return ssl_context

    @staticmethod
    def _ssl_context_for_encryption(encryption: str) -> ssl.SSLContext:
        """Build a standard TLS context for a (non-certificate) encrypted transport.

        'strict' variants validate the server certificate and hostname against
        the OS trust store; lax variants encrypt only.
        """
        ssl_context = ssl.create_default_context()
        if encryption in ("ssl_strict", "starttls_strict"):
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
        else:
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

        headers = headers or {}
        email_cc = email_cc or []
        email_bcc = email_bcc or []

        # odoo._monkeypatches.email replaces the stdlib policy with one that never
        # folds identification headers and folds user headers only at 998 chars.
        msg = EmailMessage(policy=email.policy.SMTP)
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
            del msg[key]
            # A header with no value is not a header: it serializes to a bare
            # "Key:" line, which is a syntax error the recipient's parser must
            # guess its way around. Callers build these dicts with patterns like
            # ``headers.setdefault("Return-Path", a.bounce_email or b.bounce_email)``,
            # so an unset source lands here as False rather than as an absent key.
            # Every falsy value is dropped, not just False/None/"": the header
            # registry renders a non-string falsy value (0) to an empty header too.
            if not value:
                continue
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
        """Return the default bounce (envelope) address, used when the message
        provides none. Defaults to the ``--email-from`` CLI/config parameter.
        """
        return tools.config.get("email_from")

    @api.model
    def _get_default_from_address(self) -> str | None:
        """Return the default "header from" address, used when none is received.
        Defaults to the ``--email-from`` CLI/config parameter.
        """
        return tools.config.get("email_from")

    @api.model
    def _get_default_from_filter(self) -> str | None:
        """Return the default from_filter, used when no specific ir.mail_server
        is selected. Defaults to the ``mail.default.from_filter`` ICP, then the
        ``--from-filter`` CLI/config parameter.
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

        The returned message is a *copy*: the envelope-only headers are consumed
        destructively (``Bcc`` and ``Return-Path`` are read, then dropped), so
        preparing the caller's own object twice would silently lose the blind
        recipients and the bounce address on the second pass -- exactly what a
        caller retrying after a ``MailDeliveryError``, as ``send_email``'s
        docstring invites, would do.

        :param message: the email to send; its Return-Path, From, etc. determine
            smtp_from and smtp_to. Left untouched.
        :param smtp_session: the opened SMTP session authenticating the sender
        :return: ``(smtp_from, smtp_to_list, message)`` — envelope sender
            (MAIL FROM), recipient addresses, and the message to send
        """
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

        message = self._detached_copy(message)
        self._alter_message__(message, smtp_from)

        if self._match_from_filter(bounce_address, from_filter):
            smtp_from = bounce_address

        smtp_from_rfc2822 = extract_rfc2822_addresses(smtp_from)
        if not smtp_from_rfc2822:
            raise OutgoingEmailError(
                f"Malformed 'Return-Path' or 'From' address: {smtp_from} - "
                "It should contain one valid plain ASCII email",
                code=self.NO_VALID_FROM,
            )
        smtp_from = smtp_from_rfc2822[-1]

        if not self._session_supports_smtputf8(smtp_session):
            self._check_ascii_envelope(smtp_from, smtp_to_list)

        return smtp_from, smtp_to_list, message

    @api.model
    def _check_ascii_envelope(self, smtp_from: str, smtp_to_list: list[str]) -> None:
        """Reject envelope addresses a non-SMTPUTF8 session cannot carry.

        ``extract_rfc2822_addresses`` punycodes the *domain* but passes a
        non-ASCII local part through unchanged, so an address reaches here still
        needing RFC 6531. Rejecting it now, with the same stable codes as any
        other bad address, turns what ``smtplib`` would otherwise raise from the
        middle of ``send_message`` -- an ``SMTPNotSupportedError`` that
        ``mail.mail`` files under the retry-forever ``unknown`` bucket -- into
        the permanent, correctly-classified failure it actually is.
        """
        if not smtp_from.isascii():
            raise OutgoingEmailError(
                f"Malformed 'Return-Path' or 'From' address: {smtp_from} - "
                "It should contain one valid plain ASCII email "
                "(this server does not support SMTPUTF8)",
                code=self.NO_VALID_FROM,
            )
        if non_ascii := [address for address in smtp_to_list if not address.isascii()]:
            raise OutgoingEmailError(
                f"Recipient address requires SMTPUTF8, which this server does "
                f"not support: {', '.join(non_ascii)}",
                code=self.NO_VALID_RECIPIENT,
            )

    @staticmethod
    def _detached_copy(message: EmailMessage) -> EmailMessage:
        """Return a copy of ``message`` that can be edited without touching it.

        ``copy.copy`` shares both mutable containers of an ``EmailMessage``, so
        each is rebound: ``_headers`` (only ``__delitem__`` rebinds it, so a
        plain ``msg[key] = value`` would append to the list the original still
        holds) and ``_payload`` when it is a list of parts (``attach()``
        appends to it). Both are cheap -- the parts themselves are shared, not
        cloned, so an 8 MiB attachment costs no extra memory.
        """
        detached = copy.copy(message)
        detached._headers = list(message._headers)
        if isinstance(message._payload, list):
            detached._payload = list(message._payload)
        return detached

    @api.model
    def _alter_message__(self, message: EmailMessage, smtp_from: str) -> None:
        """Rewrite the visible headers, then drop every header that only exists
        to feed the SMTP envelope.

        ``Bcc`` and ``Return-Path`` are *inputs* to
        :meth:`_prepare_email_message__` (recipients and envelope sender), just
        like ``X-Forge-To`` / ``X-Msg-To-Add`` are inputs to the ``To`` rewrite
        above. None of them may reach the wire: RFC 5321 §4.4 reserves
        ``Return-Path`` for the *delivering* MTA, which prepends its own from
        the envelope, so transmitting ours yields two conflicting ones.
        """
        if x_forge_to := message["X-Forge-To"]:
            del message["To"]
            message["To"] = x_forge_to
        elif x_msg_add_to := message["X-Msg-To-Add"]:
            to = message["To"] or ""
            to_normalized = tools.mail.email_normalize_all(to)
            additions = [
                address
                for address in tools.mail.email_split_and_format(x_msg_add_to)
                if tools.mail.email_normalize(address, strict=False)
                not in to_normalized
            ]
            del message["To"]
            # Join only non-empty parts: an absent To or a fully-redundant addition
            # would otherwise emit a dangling comma (``To: , x@y`` / ``To: x@y,``).
            if new_to := ", ".join(part for part in [str(to), *additions] if part):
                message["To"] = new_to

        if message["From"] != smtp_from:
            del message["From"]
            message["From"] = smtp_from

        del message["Bcc"]
        del message["Return-Path"]
        del message["X-Forge-To"]
        del message["X-Msg-To-Add"]

    @api.model
    def _prepare_smtp_to_list(
        self, message: EmailMessage, smtp_session: smtplib.SMTP
    ) -> list[str]:
        """Prepare the SMTP To address list from To / Cc / Bcc.

        Deduplication is global (not per header) and case-insensitive: an address
        listed in both To and Cc is one mailbox and must get exactly one RCPT TO,
        otherwise the recipient receives the message once per listing.

        Context key 'send_validated_to' restricts addresses to that list, matching
        the raw *and* normalized form so a caller that vets addresses in normalized
        form (as ``mail.mail`` does) does not silently drop a recipient whose header
        spells the same mailbox with different casing. 'send_smtp_skip_to' holds a
        recipients block list, matched on the normalized form.
        """
        validated_to = set(self.env.context.get("send_validated_to") or ())
        skip_to = set(self.env.context.get("send_smtp_skip_to") or ())

        smtp_to_list = []
        seen = set()
        for header in (message["To"], message["Cc"], message["Bcc"]):
            for address in extract_rfc2822_addresses(header):
                if not address:
                    continue
                normalized = email_normalize(address, strict=False)
                dedup_key = normalized or address.lower()
                if dedup_key in seen or normalized in skip_to:
                    continue
                if validated_to and not validated_to & {address, normalized}:
                    continue
                seen.add(dedup_key)
                smtp_to_list.append(address)
        return smtp_to_list

    @api.private
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
        """Send an email directly (no queuing, no retries).

        The caller should handle MailDeliveryException to ensure the mail is
        never lost. Server selection: ``mail_server_id`` wins and ignores the
        ``smtp_*`` args; else an explicit ``smtp_server``; else the default
        (highest priority) server; else the ``smtp_server`` config value (fails
        if unset).

        :param message: the email to send. The envelope sender comes from
            ``Return-Path`` or the default bounce address; recipients come from
            the combined ``To``/``CC``/``BCC`` headers. It is not modified, so
            the same object may be handed to a retry.
        :param smtp_session: optional pre-established session; overrides
            ``mail_server_id`` and the ``smtp_*`` args. Caller disconnects it.
        :param mail_server_id: optional id of ir.mail_server; overrides ``smtp_*`` args
        :param smtp_encryption: 'none', 'starttls', 'starttls_strict', 'ssl', or
            'ssl_strict'; 'strict' variants verify the server certificate against
            the OS trust store.
        :param smtp_ssl_certificate: SSL certificate filename for authentication
        :param smtp_ssl_private_key: SSL private key filename for authentication
        :return: the Message-ID of the sent message; otherwise raises
            MailDeliveryException and logs the root cause.
        """
        smtp = smtp_session
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
                _logger.warning(msg, exc_info=True)
                raise MailDeliveryError(_("Mail Delivery Failed"), msg) from e
            return message_id
        finally:
            if owns_connection and smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    with suppress(Exception):
                        smtp.close()

    def _find_mail_server_allowed_domain(self) -> fields.Domain:
        """Overridable domain getter for all mail servers that may be used as default."""
        return fields.Domain.TRUE

    def _find_mail_server(
        self, email_from: str | None, mail_servers: Self | None = None
    ) -> tuple[Self | None, str | None]:
        """Find the appropriate mail server for the given email address.

        :rtype: tuple[Self | None, str]
        :returns: A two-elements tuple: ``(Record<ir.mail_server>, email_from)``

          1. Mail server to use to send the email (``None`` if we use the odoo-bin arguments)
          2. Email FROM to use to send the email (in some case, it might be impossible
             to use the given email address directly if no mail server is configured for)
        """
        email_from_normalized = email_normalize(email_from)
        email_from_domain = email_domain_extract(email_from_normalized)
        # Normalized like every other address matched below, and like
        # _prepare_email_message__ normalizes the same context key. The value
        # comes from mail.alias.domain.default_from_email, whose own _check_name
        # validates the domain but deliberately never rewrites it -- so
        # "notifications@Example.COM" reaches here verbatim and, compared raw
        # against the normalized from_filter index, matched no server at all.
        notifications_email = email_normalize(
            self.env.context.get("domain_notifications_email")
            or self._get_default_from_address()
        )
        notifications_domain = email_domain_extract(notifications_email)

        if mail_servers is None:
            # _order ("sequence, id") rather than "sequence" alone: sequence
            # defaults to 10 on every server, so without the id tie-break the
            # winner among equal-priority servers is whatever physical row order
            # Postgres happens to return -- it changes after any update to a
            # competing row, a VACUUM FULL or a dump/restore.
            mail_servers = self.sudo().search(self._find_mail_server_allowed_domain())
        mail_servers = mail_servers.filtered("active")

        indexes: dict[int, _FromFilter] = {}

        def index(mail_server: Self) -> _FromFilter:
            entry = indexes.get(mail_server.id)
            if entry is None:
                entry = indexes[mail_server.id] = self._from_filter_index(
                    mail_server.from_filter
                )
            return entry

        def first_email_match(address):
            return next(
                (s for s in mail_servers if address in index(s).emails),
                None,
            )

        def first_domain_match(domain):
            return next(
                (s for s in mail_servers if domain in index(s).domains),
                None,
            )

        if email_from_normalized:
            if mail_server := first_email_match(email_from_normalized):
                return mail_server, email_from

            if mail_server := first_domain_match(email_from_domain):
                return mail_server, email_from

        mail_servers = self._filter_mail_servers_fallback(mail_servers)

        if notifications_email:
            if mail_server := first_email_match(notifications_email):
                return mail_server, notifications_email

            if mail_server := first_domain_match(notifications_domain):
                return mail_server, notifications_email

        if mail_server := next(
            (server for server in mail_servers if index(server).unrestricted), None
        ):
            return mail_server, notifications_email or email_from

        if mail_servers:
            _logger.warning(
                "No mail server matches the from_filter, using %s as fallback",
                notifications_email or email_from,
            )
            return mail_servers[0], notifications_email or email_from

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

        The from filter can be falsy (always match), a domain name, or a full
        email address; a comma-separated list of those matches on any entry.
        """
        return self._from_filter_index(from_filter).matches(email_normalize(email_from))

    @api.model
    def _from_filter_index(self, from_filter: str | None) -> _FromFilter:
        """Reduce a raw ``from_filter`` to the normalized senders it authorizes.

        Normalizing once per filter -- instead of once per (filter part, sender)
        pair -- is what keeps :meth:`_find_mail_server`'s four matching passes
        linear in the number of servers, and it is the single place that decides
        whether a part means an address or a domain.
        """
        emails, domains, unparsed = set(), set(), 0
        for part in self._parse_from_filter(from_filter):
            if "@" in part:
                normalized = email_normalize(part)
                if normalized:
                    emails.add(normalized)
                else:
                    unparsed += 1
            elif normalized := email_domain_normalize(part):
                domains.add(normalized)
            else:
                unparsed += 1
        return _FromFilter(frozenset(emails), frozenset(domains), unparsed)

    @api.model
    def _parse_from_filter(self, from_filter: str | None) -> list[str]:
        return [part.strip() for part in (from_filter or "").split(",") if part.strip()]

    @api.onchange("smtp_encryption")
    def _onchange_encryption(self) -> None:
        if self.smtp_encryption in ("ssl", "ssl_strict"):
            if self.smtp_port == 25:
                self.smtp_port = 465
        elif self.smtp_port == 465:
            self.smtp_port = 25
