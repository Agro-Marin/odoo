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

SMTP_TIMEOUT = 60

CERTIFICATE_LOAD_ERRORS = (
    SSLCryptoError,
    SSLError,
    ssl.SSLError,
    ValueError,
    TypeError,
)


class MailDeliveryError(Exception):
    def __str__(self) -> str:
        return "\n".join(str(arg) for arg in self.args)


MailDeliveryException = MailDeliveryError


class OutgoingEmailError(UserError):
    def __init__(self, message: str, code: str | None = None) -> None:
        self.code = code or message
        super().__init__(message)


def _log_smtp_debug(*args: Any) -> None:
    _logger.debug("%s", " ".join(str(arg) for arg in args))


def _check_hostname_callback(
    cnx: Any,
    x509: Any,
    err_no: int,
    err_depth: int,
    return_code: int,
    *,
    hostname: str,
) -> bool:
    if err_no:
        return False

    if err_depth == 0:
        # SAN only, deliberately. `match_hostname` consults `subject` solely
        # under `hostname_checks_common_name`, which stays off: CN-as-hostname
        # was deprecated by RFC 6125 and no public CA has issued it since 2017.
        # Supplying a `subject` here bought nothing and cost a deprecated
        # `X509.get_subject()` call whose value was discarded on every strict
        # handshake. `TestVerifyHostnameCallback` pins the rule.
        match_hostname({"subjectAltName": get_subj_alt_name(x509)}, hostname)

    return True


class _SmtpTransport(NamedTuple):
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
    from_filter: str | bool = False
    smtp_from: str | bool = False


class IrMail_Server(models.Model):
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
        if not vals.get("active", True):
            self._check_archivable()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_use(self) -> None:
        self._check_archivable(deleting=True)

    def _check_archivable(self, deleting: bool = False) -> None:
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
        return {}

    def _get_max_email_size(self, smtp_session: smtplib.SMTP | None = None) -> float:
        configured = self.max_email_size or (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_float("base.default_max_email_size", 10.0)
        )
        advertised = self._session_max_email_size(smtp_session)
        return min(configured, advertised) if advertised else configured

    @staticmethod
    def _session_max_email_size(smtp_session: smtplib.SMTP | None) -> float | None:
        size = (getattr(smtp_session, "esmtp_features", None) or {}).get("size")
        try:
            return float(size) / 1024**2 or None
        except TypeError, ValueError:
            return None

    def _from_filter_sender(self) -> str | None:
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
                raise self._prepare_connection_test_error(e, server) from e
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

    def _prepare_connection_test_error(self, exc: Exception, server: Self) -> UserError:
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
        if self._disable_send():
            return None

        mail_server = None
        if mail_server_id:
            mail_server = self.sudo().browse(mail_server_id)
            self._check_forced_mail_server(mail_server, allow_archived, smtp_from)
        elif resolve_server and not host:
            mail_server, smtp_from = self.sudo()._get_mail_server(smtp_from)
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
        return tools.config.get("smtp_timeout", SMTP_TIMEOUT) or None

    @staticmethod
    def _get_smtp_local_hostname() -> str | None:
        return tools.config.get("smtp_helo_name") or None

    def _open_smtp_connection(
        self, transport: _SmtpTransport, smtp_from: str | None
    ) -> smtplib.SMTP | smtplib.SMTP_SSL:
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
        connection.from_filter = context.from_filter
        connection.smtp_from = context.smtp_from

    @staticmethod
    def _session_supports_smtputf8(smtp_session: smtplib.SMTP | None) -> bool:
        features = getattr(smtp_session, "esmtp_features", None)
        if features is None:
            return True
        return "smtputf8" in features

    @staticmethod
    def _read_session_context(smtp_session: smtplib.SMTP) -> _SmtpSessionContext:
        return _SmtpSessionContext(
            from_filter=getattr(smtp_session, "from_filter", False),
            smtp_from=getattr(smtp_session, "smtp_from", False),
        )

    @staticmethod
    def _prepare_ssl_load_error(exc: Exception) -> UserError:
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
        ssl_context = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if encryption in ("ssl_strict", "starttls_strict"):
            ssl_context.set_default_verify_paths()
            ssl_context._ctx.set_verify(
                VERIFY_PEER | VERIFY_FAIL_IF_NO_PEER_CERT,
                functools.partial(
                    _check_hostname_callback,
                    hostname=smtp_server,
                ),
            )
        else:
            ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    def _load_certificate_material(self) -> tuple[list[Any], Any]:
        self.ensure_one()
        try:
            chain = load_pem_x509_certificates(
                base64.b64decode(self.smtp_ssl_certificate)
            )
            private_key = load_pem_private_key(
                base64.b64decode(self.smtp_ssl_private_key), password=None
            )
        except CERTIFICATE_LOAD_ERRORS as e:
            raise self._prepare_ssl_load_error(e) from None
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
        ssl_context = self._client_ssl_context(mail_server.smtp_encryption, smtp_server)
        (leaf, *intermediates), private_key = mail_server._load_certificate_material()
        try:
            ssl_context._ctx.use_certificate(leaf)
            for intermediate in intermediates:
                ssl_context._ctx.add_extra_chain_cert(intermediate)
            ssl_context._ctx.use_privatekey(private_key)
        except CERTIFICATE_LOAD_ERRORS as e:
            raise self._prepare_ssl_load_error(e) from None
        return ssl_context

    def _ssl_context_from_cert_files(
        self,
        cert_filename: str,
        key_filename: str,
        encryption: str | None = None,
        smtp_server: str | None = None,
    ) -> PyOpenSSLContext:
        ssl_context = self._client_ssl_context(encryption, smtp_server)
        try:
            ssl_context.load_cert_chain(cert_filename, keyfile=key_filename)
            ssl_context._ctx.check_privatekey()
        except CERTIFICATE_LOAD_ERRORS as e:
            raise self._prepare_ssl_load_error(e) from None
        return ssl_context

    @staticmethod
    def _ssl_context_for_encryption(encryption: str) -> ssl.SSLContext:
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
        connection.login(smtp_user, smtp_password)

    def _prepare_email__(
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
        return tools.config.get("email_from")

    @api.model
    def _get_default_from_address(self) -> str | None:
        return tools.config.get("email_from")

    @api.model
    def _get_default_from_filter(self) -> str | None:
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.default.from_filter", tools.config.get("from_filter"))
        )

    def _prepare_email_message__(
        self, message: EmailMessage, smtp_session: smtplib.SMTP
    ) -> tuple[str, list[str], EmailMessage]:
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
        detached = copy.copy(message)
        detached._headers = list(message._headers)
        if isinstance(message._payload, list):
            detached._payload = list(message._payload)
        return detached

    @api.model
    def _alter_message__(self, message: EmailMessage, smtp_from: str) -> None:
        if x_forge_to := message["X-Forge-To"]:
            del message["To"]
            message["To"] = x_forge_to
        elif x_msg_add_to := message["X-Msg-To-Add"]:
            to = message["To"] or ""
            # Dedupe within the header as well as against `To`. This becomes the
            # visible `To:` line, and a producer may legitimately list the same
            # correspondent more than once: `_notify_get_recipients` returns one
            # entry per notification transport, so a partner who is both a channel
            # member and a mentioned recipient appears twice, and
            # `_notify_by_email_get_base_mail_values` copies every share-flagged
            # entry into this header. Filtering only against `To` let that reach
            # the recipient as `To: bob@example.com, bob@example.com`.
            # `email_split_and_format` drops what it cannot parse, so in practice
            # every address here normalizes; the falsy branch is defence, because
            # collapsing two unnormalizable addresses into one would lose a
            # recipient, which is worse than the duplicate this fixes.
            seen = set(tools.mail.email_normalize_all(to))
            additions = []
            for address in tools.mail.email_split_and_format(x_msg_add_to):
                normalized = tools.mail.email_normalize(address, strict=False)
                if normalized and normalized in seen:
                    continue
                if normalized:
                    seen.add(normalized)
                additions.append(address)
            del message["To"]
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
        return fields.Domain.TRUE

    def _get_mail_server(
        self, email_from: str | None, mail_servers: Self | None = None
    ) -> tuple[Self | None, str | None]:
        email_from_normalized = email_normalize(email_from)
        email_from_domain = email_domain_extract(email_from_normalized)
        notifications_email = email_normalize(
            self.env.context.get("domain_notifications_email")
            or self._get_default_from_address()
        )
        notifications_domain = email_domain_extract(notifications_email)

        if mail_servers is None:
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
        return servers

    @api.model
    def _match_from_filter(
        self, email_from: str | None, from_filter: str | None
    ) -> bool:
        return self._from_filter_index(from_filter).matches(email_normalize(email_from))

    @api.model
    def _from_filter_index(self, from_filter: str | None) -> _FromFilter:
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
    def _onchange_smtp_encryption(self) -> None:
        if self.smtp_encryption in ("ssl", "ssl_strict"):
            if self.smtp_port == 25:
                self.smtp_port = 465
        elif self.smtp_port == 465:
            self.smtp_port = 25
