"""A failed HTTP bind must reach the logger, not only stderr.

``ThreadedWSGIServerReloadable`` inherits werkzeug's constructor, which reports
a bind failure (EADDRINUSE, EACCES, an interface that does not resolve) by
``print``-ing to ``sys.stderr`` and calling ``sys.exit(1)`` -- see
``werkzeug.serving.BaseWSGIServer.__init__``.  Nothing of that reaches a logger.

Under ``--logfile`` (every non-interactive deployment, and every CI invocation)
that print goes to the terminal or to ``/dev/null`` while the log itself ends
with an ordinary "Initialization done, shutting down".  A server that never
bound its port is then indistinguishable from a clean run, with only the exit
status to tell them apart -- a failure mode that cost three diagnostic runs
during the audit that added this test.

``http_spawn`` must therefore restate the failure at CRITICAL and let the
``SystemExit`` propagate unchanged, so the process still exits non-zero.

Run with::

    python -m pytest tests/service/test_http_bind_failure.py -v
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from odoo.service import _threaded


def failing_bind():
    """``ThreadedWSGIServerReloadable`` raising ``SystemExit(1)``, as werkzeug does.

    werkzeug's ``BaseWSGIServer.__init__`` reports a bind failure by ``print``-ing
    to stderr and calling ``sys.exit(1)``; this is the only way to reach
    ``http_spawn``'s handler.  Spelled out five times before, once per test.
    """
    return patch.object(
        _threaded, "ThreadedWSGIServerReloadable", side_effect=SystemExit(1)
    )


@pytest.fixture
def server():
    """A ``ThreadedServer`` with the interface/port fields ``http_spawn`` reads."""
    srv = _threaded.ThreadedServer.__new__(_threaded.ThreadedServer)
    srv.logger = logging.getLogger("odoo.service.server.ThreadedServer")
    srv.interface = "0.0.0.0"
    srv.port = 8069
    srv.app = MagicMock()
    srv.httpd = None
    return srv


class TestBindFailureIsLogged:
    def test_systemexit_is_reported_at_critical(self, server, caplog):
        with (
            failing_bind(),
            caplog.at_level(logging.CRITICAL, logger="odoo.service.server"),
            pytest.raises(SystemExit),
        ):
            server.http_spawn()

        critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert critical, "a failed bind must produce a CRITICAL log record"
        assert "Failed to bind" in critical[0].getMessage()

    def test_the_message_names_the_address(self, server, caplog):
        """An operator reading only the log must learn *which* address failed."""
        server.interface, server.port = "127.0.0.1", 8899
        with (
            failing_bind(),
            caplog.at_level(logging.CRITICAL, logger="odoo.service.server"),
            pytest.raises(SystemExit),
        ):
            server.http_spawn()

        critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert critical, "a failed bind must produce a CRITICAL log record"
        message = critical[0].getMessage()
        assert "127.0.0.1" in message
        assert "8899" in message

    def test_the_exit_still_propagates(self, server):
        """Logging must not swallow the failure: the process still exits 1."""
        with failing_bind():
            with pytest.raises(SystemExit) as excinfo:
                server.http_spawn()
        assert excinfo.value.code == 1

    def test_no_serving_thread_is_started_on_failure(self, server):
        with (
            failing_bind(),
            patch.object(_threaded.threading, "Thread") as thread,
            pytest.raises(SystemExit),
        ):
            server.http_spawn()
        thread.assert_not_called()


class TestSuccessfulSpawnIsUnchanged:
    def test_httpd_is_stored_and_served(self, server, caplog):
        httpd = MagicMock()
        with (
            patch.object(_threaded, "ThreadedWSGIServerReloadable", return_value=httpd),
            patch.object(_threaded.threading, "Thread") as thread,
            caplog.at_level(logging.CRITICAL, logger="odoo.service.server"),
        ):
            server.http_spawn()

        assert server.httpd is httpd
        thread.assert_called_once()
        assert thread.call_args.kwargs["target"] == httpd.serve_forever
        assert thread.call_args.kwargs["daemon"] is True
        assert not caplog.records, "a successful bind must log nothing here"
