import contextlib
import logging
import shutil
import smtplib
import socket
import ssl
import unittest
import warnings
from base64 import b64encode
from os import getenv
from pathlib import Path
from socket import getaddrinfo
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tools import config, file_path, mute_logger

from .common import TransactionCaseWithUserDemo
from odoo.addons.base.models.ir_mail_server import IrMail_Server

try:
    import aiosmtpd
    import aiosmtpd.controller
    import aiosmtpd.handlers
    import aiosmtpd.smtp
except ImportError:
    aiosmtpd = None


SMTP_TIMEOUT = 5
PASSWORD = "secretpassword"
_openssl = shutil.which("openssl")
_logger = logging.getLogger(__name__)

if getenv("ODOO_RUNBOT") and not _openssl:
    _logger.warning(
        "detected runbot environment but openssl not found in PATH, TestIrMailServerSMTPD will be skipped"
    )
if getenv("ODOO_RUNBOT") and not aiosmtpd:
    _logger.warning(
        "detected runbot environment but aiosmtpd not installed, TestIrMailServerSMTPD will be skipped"
    )


def _find_free_local_address():
    addr = aiosmtpd.controller.get_localhost()
    family = socket.AF_INET if addr == "127.0.0.1" else socket.AF_INET6
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind((addr, 0))
        port = sock.getsockname()[1]
    return family, addr, port


def _smtp_authenticate(server, session, enveloppe, mechanism, data):
    result = aiosmtpd.smtp.AuthResult(success=data.password == PASSWORD.encode())
    _logger.debug("AUTH %s", "successfull" if result.success else "failed")
    return result


class Certificate:
    def __init__(self, key, cert):
        self.key = key and Path(file_path(key, filter_ext=".pem"))
        self.cert = Path(file_path(cert, filter_ext=".pem"))

    def __repr__(self):
        return f"Certificate({self.key=}, {self.cert=})"


class _EhloRecordingHandler(aiosmtpd.handlers.Debugging if aiosmtpd else object):
    def __init__(self):
        super().__init__()
        self.hostnames = []

    async def handle_EHLO(self, server, session, envelope, hostname, responses):
        self.hostnames.append(hostname)
        session.host_name = hostname
        return responses


@unittest.skipUnless(aiosmtpd, "aiosmtpd couldn't be imported")
@unittest.skipUnless(_openssl, "openssl not found in path")
@patch.dict(config.options, {"smtp_server": "", "smtp_timeout": SMTP_TIMEOUT})
class TestIrMailServerSMTPD(TransactionCaseWithUserDemo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class Session(aiosmtpd.smtp.Session):
            @property
            def login_data(self):
                return self._login_data

            @login_data.setter
            def login_data(self, value):
                self._login_data = value

        patcher = patch("aiosmtpd.smtp.Session", Session)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

        warnings.filterwarnings(
            "ignore",
            "Requiring AUTH while not requiring TLS can lead to security vulnerabilities!",
            category=UserWarning,
        )

        class CustomFilter(logging.Filter):
            def filter(self, record):
                if record.msg == "auth_required == True but auth_require_tls == False":
                    return False
                return (
                    record.msg
                    != "tls_context.verify_mode not in {CERT_NONE, CERT_OPTIONAL}; this might cause client connection problems"
                )

        logging.getLogger("mail.log").addFilter(CustomFilter())

        logging.getLogger("mail.log").setLevel(_logger.getEffectiveLevel() + 10)

        cls.ssl_ca, cls.ssl_client, cls.ssl_server, cls.ssl_self_signed = [
            Certificate(None, "base/tests/ssl/ca.cert.pem"),
            Certificate(
                "base/tests/ssl/client.key.pem",
                "base/tests/ssl/client.cert.pem",
            ),
            Certificate(
                "base/tests/ssl/server.key.pem",
                "base/tests/ssl/server.cert.pem",
            ),
            Certificate(
                "base/tests/ssl/self_signed.key.pem",
                "base/tests/ssl/self_signed.cert.pem",
            ),
        ]

        class TEST_SMTP(smtplib.SMTP):
            def starttls(self, *, context):
                if context is None:
                    context = ssl._create_stdlib_context()
                context.load_verify_locations(cafile=str(cls.ssl_ca.cert))
                super().starttls(context=context)

        class TEST_SMTP_SSL(smtplib.SMTP_SSL):
            def _get_socket(self, *args, **kwargs):
                self.context.load_verify_locations(cafile=str(cls.ssl_ca.cert))
                return super()._get_socket(*args, **kwargs)

        patcher = patch("smtplib.SMTP", TEST_SMTP)
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        patcher = patch("smtplib.SMTP_SSL", TEST_SMTP_SSL)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

        family, addr, cls.port = _find_free_local_address()
        cls.localhost = getaddrinfo(addr, cls.port, family)
        cls.startClassPatcher(patch("socket.getaddrinfo", cls.getaddrinfo))

    def setUp(self):
        super().setUp()
        patcher = patch.object(IrMail_Server, "_disable_send", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    @classmethod
    def getaddrinfo(cls, host, port, *args, **kwargs):
        if host in ("localhost", "notlocalhost") and port == cls.port:
            return cls.localhost
        return getaddrinfo(host, port, family=0, type=0, proto=0, flags=0)

    @contextlib.contextmanager
    def start_smtpd(
        self,
        encryption,
        ssl_context=None,
        auth_required=True,
        stop_on_cleanup=True,
        handler=None,
    ):
        encryption = encryption.removesuffix("_strict")
        assert encryption in ("none", "ssl", "starttls")
        assert encryption == "none" or ssl_context

        kwargs = {}
        if encryption == "starttls":
            kwargs.update(
                {
                    "require_starttls": True,
                    "tls_context": ssl_context,
                }
            )
        elif encryption == "ssl":
            kwargs["ssl_context"] = ssl_context
        if auth_required:
            kwargs["authenticator"] = _smtp_authenticate

        smtpd_thread = aiosmtpd.controller.Controller(
            handler if handler is not None else aiosmtpd.handlers.Debugging(),
            hostname=aiosmtpd.controller.get_localhost(),
            server_hostname="localhost",
            port=self.port,
            auth_required=auth_required,
            auth_require_tls=False,
            enable_SMTPUTF8=True,
            **kwargs,
        )
        try:
            smtpd_thread.start()
            yield smtpd_thread
        finally:
            smtpd_thread.stop()

    def _announced_name(self):
        handler = _EhloRecordingHandler()
        with self.start_smtpd("none", auth_required=False, handler=handler):
            self.env["ir.mail_server"].create(
                {
                    "name": "helo probe",
                    "from_filter": "localhost",
                    "smtp_host": "localhost",
                    "smtp_port": self.port,
                    "smtp_authentication": "login",
                    "smtp_user": "",
                    "smtp_pass": "",
                }
            ).test_smtp_connection()
        self.assertTrue(handler.hostnames, "the server received no EHLO")
        return handler.hostnames[0]

    @mute_logger("mail.log")
    def test_configured_name_reaches_the_server(self):
        with patch.dict(config.options, {"smtp_helo_name": "mail.example.com"}):
            self.assertEqual(self._announced_name(), "mail.example.com")

    @mute_logger("mail.log")
    def test_unset_option_keeps_the_smtplib_default(self):
        fqdn = socket.getfqdn()
        expected = (
            fqdn if "." in fqdn else f"[{socket.gethostbyname(socket.gethostname())}]"
        )
        with patch.dict(config.options, {"smtp_helo_name": ""}):
            self.assertEqual(self._announced_name(), expected)

    @mute_logger("mail.log")
    def test_the_option_actually_changes_the_wire(self):
        with patch.dict(config.options, {"smtp_helo_name": ""}):
            default_name = self._announced_name()
        with patch.dict(config.options, {"smtp_helo_name": "mail.example.com"}):
            configured_name = self._announced_name()
        self.assertNotEqual(default_name, configured_name)

    @mute_logger("mail.log")
    def test_authentication_certificate_matrix(self):
        mail_server = self.env["ir.mail_server"].create(
            {
                "name": "test smtpd",
                "from_filter": "localhost",
                "smtp_host": "localhost",
                "smtp_port": self.port,
                "smtp_authentication": "login",
                "smtp_user": "",
                "smtp_pass": "",
            }
        )

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(self.ssl_server.cert, self.ssl_server.key)
        ssl_context.load_verify_locations(cafile=self.ssl_ca.cert)
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        self_signed_key = b64encode(self.ssl_self_signed.key.read_bytes())
        self_signed_cert = b64encode(self.ssl_self_signed.cert.read_bytes())
        client_key = b64encode(self.ssl_client.key.read_bytes())
        client_cert = b64encode(self.ssl_client.cert.read_bytes())
        matrix = [
            (
                "login",
                "missing",
                "",
                "",
                (
                    r"The server has closed the connection unexpectedly\. "
                    r"Check configuration served on this port number\.\n "
                    r"Connection unexpectedly closed"
                ),
            ),
            (
                "certificate",
                "self signed",
                self_signed_cert,
                self_signed_key,
                (
                    r"The server has closed the connection unexpectedly\. "
                    r"Check configuration served on this port number\.\n "
                    r"Connection unexpectedly closed"
                ),
            ),
            ("certificate", "valid client", client_cert, client_key, None),
        ]

        for encryption in ("starttls", "starttls_strict", "ssl", "ssl_strict"):
            mail_server.smtp_encryption = encryption
            with self.start_smtpd(encryption, ssl_context, auth_required=False):
                for (
                    authentication,
                    name,
                    certificate,
                    private_key,
                    error_pattern,
                ) in matrix:
                    with self.subTest(encryption=encryption, certificate=name):
                        mail_server.write(
                            {
                                "smtp_authentication": authentication,
                                "smtp_ssl_certificate": certificate,
                                "smtp_ssl_private_key": private_key,
                            }
                        )
                        if error_pattern:
                            timeout = (
                                0.1 if "timed out" in error_pattern else SMTP_TIMEOUT
                            )
                            with (
                                self.assertRaises(UserError) as error_capture,
                                patch.dict(config.options, {"smtp_timeout": timeout}),
                            ):
                                mail_server.test_smtp_connection()
                            self.assertRegex(
                                error_capture.exception.args[0], error_pattern
                            )
                        else:
                            mail_server.test_smtp_connection()

    def test_authentication_login_matrix(self):
        mail_server = self.env["ir.mail_server"].create(
            {
                "name": "test smtpd",
                "from_filter": "localhost",
                "smtp_host": "localhost",
                "smtp_port": self.port,
                "smtp_authentication": "login",
                "smtp_user": "",
                "smtp_pass": "",
            }
        )

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(self.ssl_server.cert, self.ssl_server.key)

        MISSING = ""
        INVALID = "bad password"
        matrix = [
            (False, MISSING, None),
            (
                True,
                MISSING,
                r"The server refused the sender address \(noreply@localhost\) with error .*",
            ),
            (
                True,
                INVALID,
                (
                    r"The server has closed the connection unexpectedly\. "
                    r"Check configuration served on this port number\.\n "
                    r"Connection unexpectedly closed:.* timed out"
                ),
            ),
            (True, PASSWORD, None),
        ]

        for encryption in (
            "none",
            "starttls",
            "starttls_strict",
            "ssl",
            "ssl_strict",
        ):
            mail_server.smtp_encryption = encryption
            for auth_required, password, error_pattern in matrix:
                mail_server.smtp_user = password and self.user_demo.email
                mail_server.smtp_pass = password
                with self.subTest(
                    encryption=encryption,
                    auth_required=auth_required,
                    password=password,
                ):
                    with self.start_smtpd(encryption, ssl_context, auth_required):
                        if error_pattern:
                            timeout = (
                                0.1 if "timed out" in error_pattern else SMTP_TIMEOUT
                            )
                            with (
                                self.assertRaises(UserError) as capture,
                                patch.dict(config.options, {"smtp_timeout": timeout}),
                            ):
                                mail_server.test_smtp_connection()
                            self.assertRegex(capture.exception.args[0], error_pattern)
                        else:
                            mail_server.test_smtp_connection()

    @mute_logger("mail.log")
    def test_encryption_matrix(self):
        mail_server = self.env["ir.mail_server"].create(
            {
                "name": "test smtpd",
                "from_filter": "localhost",
                "smtp_host": "localhost",
                "smtp_port": self.port,
                "smtp_authentication": "login",
                "smtp_user": "",
                "smtp_pass": "",
            }
        )

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(self.ssl_server.cert, self.ssl_server.key)

        matrix = [
            (
                "none",
                "ssl",
                (
                    r"The server has closed the connection unexpectedly\. "
                    r"Check configuration served on this port number\.\n "
                    r"Connection unexpectedly closed: timed out"
                ),
            ),
            (
                "none",
                "starttls",
                r"The server refused the sender address \(noreply@localhost\) with error .*",
            ),
            (
                "starttls",
                "none",
                (
                    r"An option is not supported by the server:\n "
                    r"STARTTLS extension not supported by server\."
                ),
            ),
            (
                "starttls",
                "ssl",
                (
                    r"The server has closed the connection unexpectedly\. "
                    r"Check configuration served on this port number\.\n "
                    r"Connection unexpectedly closed: timed out"
                ),
            ),
            (
                "ssl",
                "none",
                (
                    r"An SSL exception occurred\. "
                    r"Check connection security type\.\n "
                    r".*?wrong version number"
                ),
            ),
            (
                "ssl",
                "starttls",
                (
                    r"An SSL exception occurred\. "
                    r"Check connection security type\.\n "
                    r".*?wrong version number"
                ),
            ),
        ]

        for client_encryption, server_encryption, error_pattern in matrix:
            with self.subTest(
                server_encryption=server_encryption,
                client_encryption=client_encryption,
            ):
                mail_server.smtp_encryption = client_encryption
                with self.start_smtpd(
                    server_encryption, ssl_context, auth_required=False
                ):
                    timeout = 0.1 if "timed out" in error_pattern else SMTP_TIMEOUT
                    with (
                        self.assertRaises(UserError) as capture,
                        patch.dict(config.options, {"smtp_timeout": timeout}),
                    ):
                        mail_server.test_smtp_connection()
                    self.assertRegex(capture.exception.args[0], error_pattern)

    @mute_logger("mail.log")
    def test_man_in_the_middle_matrix(self):
        mail_server = self.env["ir.mail_server"].create(
            {
                "name": "test smtpd",
                "from_filter": "localhost",
                "smtp_host": "localhost",
                "smtp_port": self.port,
                "smtp_authentication": "login",
                "smtp_user": self.user_demo.email,
                "smtp_pass": PASSWORD,
                "smtp_ssl_certificate": b64encode(self.ssl_client.cert.read_bytes()),
                "smtp_ssl_private_key": b64encode(self.ssl_client.key.read_bytes()),
            }
        )

        cert_good = self.ssl_server
        cert_bad = self.ssl_self_signed
        host_good = "localhost"
        host_bad = "notlocalhost"

        matrix = [
            (False, "login", cert_bad, host_good, None),
            (False, "login", cert_good, host_bad, None),
            (False, "certificate", cert_bad, host_good, None),
            (False, "certificate", cert_good, host_bad, None),
            (
                True,
                "login",
                cert_bad,
                host_good,
                (
                    r"^An SSL exception occurred\. Check connection security type\.\n "
                    r".*certificate verify failed"
                ),
            ),
            (
                True,
                "login",
                cert_good,
                host_bad,
                (
                    r"^An SSL exception occurred\. Check connection security type\.\n "
                    r".*Hostname mismatch, certificate is not valid for 'notlocalhost'"
                ),
            ),
            (
                True,
                "certificate",
                cert_bad,
                host_good,
                (
                    r"^An SSL exception occurred\. Check connection security type\.\n "
                    r".*certificate verify failed"
                ),
            ),
            (
                True,
                "certificate",
                cert_good,
                host_bad,
                (
                    r"^An SSL exception occurred\. Check connection security type\.\n "
                    r".*CertificateError: hostname 'notlocalhost' doesn't match 'localhost'"
                ),
            ),
        ]

        for encryption in ("starttls", "ssl"):
            for (
                strict,
                authentication,
                certificate,
                hostname,
                error_pattern,
            ) in matrix:
                mail_server.smtp_host = hostname
                mail_server.smtp_authentication = authentication
                mail_server.smtp_encryption = encryption + ("_strict" if strict else "")
                with self.subTest(
                    encryption=encryption + ("_strict" if strict else ""),
                    authentication=authentication,
                    cert_good=certificate == cert_good,
                    host_good=hostname == host_good,
                ):
                    mitm_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    mitm_context.load_cert_chain(certificate.cert, certificate.key)
                    auth_required = authentication == "login"
                    with self.start_smtpd(encryption, mitm_context, auth_required):
                        if error_pattern:
                            with self.assertRaises(UserError) as capture:
                                mail_server.test_smtp_connection()
                            self.assertRegex(capture.exception.args[0], error_pattern)
                        else:
                            mail_server.test_smtp_connection()
