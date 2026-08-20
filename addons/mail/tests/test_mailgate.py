import http.server
import socket
import subprocess
import sys
import tempfile
import threading
import xmlrpc.client
from pathlib import Path
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

from odoo.tests import BaseCase, tagged
from odoo.tools import file_path

EX_USAGE = 64
EX_NOUSER = 67
EX_NOHOST = 68
EX_UNAVAILABLE = 69
EX_SOFTWARE = 70
EX_TEMPFAIL = 75
EX_NOPERM = 77
EX_CONFIG = 78

FAULT_APPLICATION_ERROR = 1
FAULT_ACCESS_DENIED = 3


class _Handler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/xmlrpc/2/object",)

    def log_message(self, *args):
        pass


class FakeOdoo:
    def __init__(self, fault=None):
        self.fault = fault
        self.received = None
        self.credentials = None
        self._server = SimpleXMLRPCServer(
            ("127.0.0.1", 0),
            requestHandler=_Handler,
            allow_none=True,
            logRequests=False,
        )
        self._server.register_function(self._execute_kw, "execute_kw")

    def _execute_kw(self, database, uid, password, model, method, args, kwargs):
        self.credentials = (database, uid, password, model, method)
        self.received = args[1].data
        if self.fault is not None:
            raise self.fault
        return 1

    @property
    def port(self):
        return self._server.server_address[1]

    def __enter__(self):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=10)


class HttpStatusServer:
    def __init__(self, status):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.status = status
        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)

    @property
    def port(self):
        return self._server.server_address[1]

    def __enter__(self):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=10)


@tagged("post_install", "-at_install")
class TestMailgate(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = file_path("mail/static/scripts/odoo-mailgate.py")

    def _run(self, message, port=None, extra=(), timeout=60):
        command = [sys.executable, self.script, "-d", "db", "-u", "1", "-p", "pw"]
        if port is not None:
            command += ["--host", "127.0.0.1", "--port", str(port)]
        command += list(extra)
        return subprocess.run(
            command, input=message, capture_output=True, timeout=timeout, check=False
        )

    def _message(self, charset, body):
        return (
            b"From: sender@example.com\r\n"
            b"To: catchall@example.com\r\n"
            b"Subject: probe\r\n"
            b"Message-Id: <mailgate@example.com>\r\n"
            b"Content-Type: text/plain; charset=" + charset + b"\r\n"
            b"\r\n" + body + b"\r\n"
        )

    def test_the_message_reaches_odoo_byte_for_byte(self):
        for label, raw in [
            ("ascii", self._message(b"us-ascii", b"plain body")),
            ("utf-8", self._message(b"utf-8", "señor café".encode())),
            (
                "iso-8859-1",
                self._message(b"iso-8859-1", "señor café".encode("latin-1")),
            ),
            ("binary", self._message(b"application/octet-stream", bytes(range(256)))),
        ]:
            with self.subTest(charset=label), FakeOdoo() as odoo:
                result = self._run(raw, odoo.port)
                self.assertEqual(
                    result.returncode, 0, result.stderr.decode(errors="replace")
                )
                self.assertEqual(odoo.received, raw, "the bytes must not be touched")

    def test_crlf_survives(self):
        raw = self._message(b"us-ascii", b"one\r\ntwo\r\nthree")
        with FakeOdoo() as odoo:
            self._run(raw, odoo.port)
        self.assertEqual(odoo.received.count(b"\r\n"), raw.count(b"\r\n"))

    def test_it_is_addressed_to_the_renamed_mixin(self):
        with FakeOdoo() as odoo:
            self._run(self._message(b"us-ascii", b"x"), odoo.port)
        self.assertEqual(
            odoo.credentials[3:],
            ("mixin.mail.thread", "message_process"),
            "the fork renamed mail.thread; the script is a separate process and "
            "no import would have caught it",
        )

    def test_a_refused_password_is_reported_as_a_permission_failure(self):
        fault = xmlrpc.client.Fault(FAULT_ACCESS_DENIED, "Access Denied")
        with FakeOdoo(fault=fault) as odoo:
            result = self._run(self._message(b"us-ascii", b"x"), odoo.port)
        self.assertEqual(result.returncode, EX_NOPERM)

    def test_an_unroutable_alias_is_reported_as_an_unknown_user(self):
        fault = xmlrpc.client.Fault(
            FAULT_APPLICATION_ERROR, "Traceback...\nValueError: No possible route found"
        )
        with FakeOdoo(fault=fault) as odoo:
            result = self._run(self._message(b"us-ascii", b"x"), odoo.port)
        self.assertEqual(result.returncode, EX_NOUSER)

    def test_a_missing_database_is_reported_as_a_configuration_failure(self):
        fault = xmlrpc.client.Fault(
            FAULT_APPLICATION_ERROR, 'database "db" does not exist'
        )
        with FakeOdoo(fault=fault) as odoo:
            result = self._run(self._message(b"us-ascii", b"x"), odoo.port)
        self.assertEqual(result.returncode, EX_CONFIG)

    def test_a_restarting_server_is_queued_rather_than_bounced(self):
        for status in (502, 503):
            with self.subTest(status=status), HttpStatusServer(status) as proxy:
                asked = self._run(
                    self._message(b"us-ascii", b"x"), proxy.port, ["--retry-status"]
                )
                self.assertEqual(asked.returncode, EX_TEMPFAIL)
                default = self._run(self._message(b"us-ascii", b"x"), proxy.port)
                self.assertEqual(
                    default.returncode,
                    EX_UNAVAILABLE,
                    "without --retry-status it is still not a generic software error",
                )

    def test_a_permanent_http_error_is_not_queued(self):
        with HttpStatusServer(404) as proxy:
            result = self._run(
                self._message(b"us-ascii", b"x"), proxy.port, ["--retry-status"]
            )
        self.assertEqual(
            result.returncode,
            EX_UNAVAILABLE,
            "retrying a wrong URL forever helps nobody",
        )

    def test_an_unreachable_server_honours_retry_status(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        message = self._message(b"us-ascii", b"x")
        self.assertEqual(self._run(message, port).returncode, EX_NOHOST)
        self.assertEqual(
            self._run(message, port, ["--retry-status"]).returncode, EX_TEMPFAIL
        )

    def test_the_password_can_stay_out_of_the_process_table(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "mailgate.secret"
            secret.write_text("s3cret\n", encoding="utf-8")
            with FakeOdoo() as odoo:
                result = subprocess.run(
                    [
                        sys.executable,
                        self.script,
                        "-d",
                        "db",
                        "-u",
                        "1",
                        "--password-file",
                        str(secret),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(odoo.port),
                    ],
                    input=self._message(b"us-ascii", b"x"),
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(odoo.credentials[2], "s3cret", "the newline is not the secret")

    def test_a_malformed_command_line_is_a_usage_error(self):
        for extra in (["--proto", "gopher"], ["unexpected-argument"]):
            with self.subTest(extra=extra):
                result = self._run(b"", None, extra + ["--port", "1"])
                self.assertEqual(
                    result.returncode,
                    EX_USAGE,
                    "argparse would exit 2, which means nothing to an MTA",
                )
