"""``ThreadedServer`` signal wiring, handler behaviour and graceful shutdown.

``workers = 0`` is what every development config runs and what ``--test-enable``
runs under, yet ``start()``, ``signal_handler()`` and ``stop()`` were reachable
by no test at all.  The only references to them were ``inspect.getsource``
assertions, which keep passing while the code they describe is deleted.

Measured before this file existed, on this tree:

* removing the ``SIGTERM``/``SIGHUP`` registrations from ``start()`` left all
  750 tests green, while a real server booted from the same tree stopped
  answering ``SIGTERM`` — exit ``-15`` instead of ``0``, no shutdown log, and
  ``db.close_all()`` never reached;
* replacing the whole body of ``stop()`` with ``return`` also left all 750
  green.

Both are caught here.  The prefork and evented siblings were already covered
behaviourally (``TestPreforkServerProcessSignals``,
``TestEventServerGracefulStop``); this closes the same gap for the flavour that
actually runs in development.

Run with::

    python -m pytest tests/service/test_threaded_lifecycle.py -v
"""

import os
import signal
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from odoo.service import _threaded, lifecycle


@pytest.fixture
def server():
    """A ``ThreadedServer`` carrying exactly the fields ``__init__`` sets.

    ``__init__`` is bypassed because it reads config and builds a live
    ``psutil.Process``; every attribute it assigns is restated here, so a field
    added there without a matching line below fails loudly on first access
    rather than silently changing which branch a test takes.

    That promise is now CHECKED — ``TestTheFixtureMatchesTheConstructor`` below
    compares the two field sets.  It was false when the check was added:
    ``__init__`` sets twelve attributes and this fixture restated eleven, having
    missed ``pid``.  A docstring is not a gate.
    """
    s = object.__new__(_threaded.ThreadedServer)
    s.pid = os.getpid()
    s.main_thread_id = threading.current_thread().ident
    s.quit_signals_received = 0
    s.httpd = None
    s.limits_reached_threads = set()
    s.limit_reached_time = None
    s._stop_after_init = False
    s._process_handle = MagicMock()
    s.logger = MagicMock()
    s.interface, s.port = "127.0.0.1", 8069
    s.app = MagicMock()
    return s


# ---------------------------------------------------------------------------
# ThreadedServer.signal_handler()
# ---------------------------------------------------------------------------


class TestSignalHandlerBehaviour:
    """The handler itself — invoked, not read as source text."""

    @pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
    def test_first_quit_signal_unwinds_the_main_loop(self, server, sig):
        with pytest.raises(KeyboardInterrupt):
            server.signal_handler(sig, None)
        assert server.quit_signals_received == 1

    def test_second_quit_signal_forces_the_exit(self, server):
        """The documented "hit CTRL-C again" escape hatch: a second signal must
        bypass the graceful path entirely rather than unwinding again."""
        server.quit_signals_received = 1
        with patch.object(_threaded.os, "_exit", side_effect=SystemExit) as hard_exit:
            with pytest.raises(SystemExit):
                server.signal_handler(signal.SIGTERM, None)
        hard_exit.assert_called_once_with(0)

    def test_sighup_arms_phoenix_before_unwinding(self, server):
        """``--dev=reload`` and an operator's ``kill -HUP`` both land here.

        The flag has to be set before the unwind, because ``stop()`` reads it to
        decide whether it is reloading or shutting down; armed too late, a
        reload degrades into a plain exit.
        """
        with patch.object(lifecycle, "server_phoenix", False):
            with pytest.raises(KeyboardInterrupt):
                server.signal_handler(signal.SIGHUP, None)
            assert lifecycle.server_phoenix is True

    def test_sigxcpu_exits_immediately(self, server):
        """The CPU limit is already blown, so there is no budget for an unwind."""
        with patch.object(_threaded.os, "_exit", side_effect=SystemExit) as hard_exit:
            with pytest.raises(SystemExit):
                server.signal_handler(signal.SIGXCPU, None)
        hard_exit.assert_called_once_with(0)


class TestSignalHandlerOnAPlatformWithoutSighup:
    """Windows has no ``SIGHUP`` and no ``SIGXCPU``.

    The fork exposes a ``_SIGHUP_AVAILABLE`` sentinel rather than monkey-patching
    ``signal.SIGHUP = -1`` into the stdlib, and every call site has to short-circuit
    on it — an unguarded ``sig == signal.SIGHUP`` raises ``AttributeError`` from
    inside a signal handler, which is not a recoverable place to raise from.

    Replaces an AST walk that asserted ``_SIGHUP_AVAILABLE`` and ``SIGHUP``
    appeared together in some ``if`` test.  That is satisfied by any arrangement
    of the two names; this runs the handler against a signal module that really
    has no ``SIGHUP``, which is the condition the guard exists for.
    """

    @pytest.fixture
    def windows_signal(self):
        """A stand-in ``signal`` module shaped like Windows: no SIGHUP, no SIGXCPU."""
        return SimpleNamespace(SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM)

    def test_an_unrelated_signal_does_not_touch_signal_sighup(
        self, server, windows_signal
    ):
        with (
            patch.object(_threaded, "signal", windows_signal),
            patch.object(_threaded, "_SIGHUP_AVAILABLE", False),
        ):
            server.signal_handler(signal.SIGUSR1, None)

    def test_quit_signals_still_work_without_sighup(self, server, windows_signal):
        with (
            patch.object(_threaded, "signal", windows_signal),
            patch.object(_threaded, "_SIGHUP_AVAILABLE", False),
        ):
            with pytest.raises(KeyboardInterrupt):
                server.signal_handler(signal.SIGTERM, None)
        assert server.quit_signals_received == 1


# ---------------------------------------------------------------------------
# ThreadedServer.start() — the handlers are actually installed
# ---------------------------------------------------------------------------


class TestStartInstallsTheHandlers:
    """``start()`` must register every signal the server relies on.

    ``TestThreadedServerSignalSetup`` AST-checks that SIGCHLD is *absent*; it
    says nothing about the handlers that must be *present*, so deleting them
    passed the entire suite.
    """

    @pytest.fixture
    def wired(self, server):
        seen = {}
        cfg = {"http_enable": False, "test_enable": False}
        with (
            patch.object(_threaded, "config", cfg),
            patch.object(_threaded.signal, "signal", side_effect=seen.__setitem__),
            patch.object(_threaded.os, "name", "posix"),
        ):
            server.start()
        return seen, server

    @pytest.mark.parametrize(
        "sig", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGXCPU]
    )
    def test_quit_and_reload_signals_route_to_the_handler(self, wired, sig):
        seen, server = wired
        assert seen.get(sig) == server.signal_handler, (
            f"{sig!r} is not wired to signal_handler; the process would take the "
            f"OS default action for it — for SIGTERM that is immediate death "
            f"with no shutdown, measured as exit -15 against a real server"
        )

    def test_sigchld_is_not_installed(self, wired):
        """Kept from the AST-based guard it replaces: ThreadedServer forks no
        workers, and a no-op SIGCHLD handler only causes spurious wakeups."""
        seen, _ = wired
        assert signal.SIGCHLD not in seen

    def test_http_is_not_spawned_when_disabled(self, server):
        cfg = {"http_enable": False, "test_enable": False}
        with (
            patch.object(_threaded, "config", cfg),
            patch.object(_threaded.signal, "signal"),
            patch.object(server, "http_spawn") as spawn,
        ):
            server.start()
        spawn.assert_not_called()

    def test_http_is_spawned_under_test_enable_even_when_stopping(self, server):
        """``--test-enable --stop-after-init`` still needs a bound port: an
        HTTPCase issues real requests before the shutdown runs."""
        cfg = {"http_enable": True, "test_enable": True}
        with (
            patch.object(_threaded, "config", cfg),
            patch.object(_threaded.signal, "signal"),
            patch.object(server, "http_spawn") as spawn,
        ):
            server.start(stop=True)
        spawn.assert_called_once()


# ---------------------------------------------------------------------------
# ThreadedServer.stop() — the path a SIGTERM actually takes
# ---------------------------------------------------------------------------


class TestGracefulStop:
    """Each assertion below corresponds to a step that vanished silently when
    the body of ``stop()`` was replaced with ``return``."""

    @pytest.fixture
    def stopped(self, server):
        def _run(**attrs):
            server.__dict__.update(attrs)
            server.httpd = MagicMock()
            with (
                patch.object(_threaded.db, "close_all") as close_all,
                patch.object(_threaded, "logging") as log_mod,
                patch.object(_threaded.psutil, "Process") as proc,
            ):
                proc.return_value.children.return_value = []
                super_stop = MagicMock()
                with patch.object(_threaded.CommonServer, "stop", super_stop):
                    server.stop()
            return server, close_all, log_mod, super_stop

        return _run

    def test_wsgi_server_is_shut_down(self, stopped):
        server, _, _, _ = stopped()
        server.httpd.shutdown.assert_called_once_with()

    def test_database_connections_are_closed(self, stopped):
        """Skipping this leaks every pooled connection past the process's life,
        which a supervisor restart then compounds."""
        _, close_all, _, _ = stopped()
        close_all.assert_called_once_with()

    def test_registered_stop_hooks_run(self, stopped):
        _, _, _, super_stop = stopped()
        super_stop.assert_called_once()

    def test_logging_is_shut_down(self, stopped):
        _, _, log_mod, _ = stopped()
        log_mod.shutdown.assert_called_once_with()

    def test_reload_announces_a_reload_not_a_shutdown(self, stopped):
        with patch.object(lifecycle, "server_phoenix", True):
            server, _, _, _ = stopped()
        said = " ".join(str(c) for c in server.logger.info.call_args_list)
        assert "reload" in said.lower()
        assert "Initiating shutdown" not in said

    def test_stop_after_init_announces_initialization_done(self, stopped):
        server, _, _, _ = stopped(_stop_after_init=True)
        said = " ".join(str(c) for c in server.logger.info.call_args_list)
        assert "Initialization done" in said

    def test_plain_shutdown_tells_the_operator_how_to_force_it(self, stopped):
        server, _, _, _ = stopped()
        said = " ".join(str(c) for c in server.logger.info.call_args_list)
        assert "Initiating shutdown" in said
        assert "again" in said, (
            "the second-signal hint is the only place an operator learns the "
            "shutdown can be forced"
        )

    def test_a_hung_non_daemon_thread_cannot_stall_the_stop_forever(self, stopped):
        """The join loop is deliberately bounded (``join(0.05)`` in a one-second
        budget) rather than a single unbounded ``join()``, so a wedged
        application thread cannot hold the process open."""
        hung = MagicMock()
        hung.daemon = False
        hung.ident = -1
        hung.is_alive.return_value = True
        with patch.object(_threaded.threading, "enumerate", return_value=[hung]):
            t0 = time.monotonic()
            stopped()
        assert time.monotonic() - t0 < 5, "stop() did not bound its join loop"


class TestTheFixtureMatchesTheConstructor:
    """The ``server`` fixture claims to carry "exactly the fields ``__init__``
    sets".  This is what makes that true.

    Only fixtures that CLAIM parity are checked this way.  ``test_server.py``'s
    ``prefork_server`` deliberately populates "only the attributes consumed by
    the tested methods" and says so; asserting parity there would be asserting
    the opposite of its design.
    """

    def test_the_field_sets_agree(self, server):
        from unittest.mock import patch

        from odoo.service import _base_server
        from odoo.tools import config

        config.parse_config([], setup_logging=False)
        cfg = dict(config.options)
        cfg.update({"http_interface": "", "http_port": 8069, "limit_time_real": 120})
        with (
            patch.object(_threaded, "config", cfg),
            patch.object(_base_server, "config", cfg),
        ):
            real = _threaded.ThreadedServer(MagicMock())

        missing = sorted(set(vars(real)) - set(vars(server)))
        extra = sorted(set(vars(server)) - set(vars(real)))
        assert not missing and not extra, (
            "the `server` fixture has drifted from the constructor it stands in "
            f"for.\n  set by __init__ but absent from the fixture: {missing}\n"
            f"  in the fixture but never set by __init__:    {extra}\n"
            "Either restate the field, or drop the parity claim from the "
            "fixture's docstring and let it be a minimal stand-in like "
            "test_server.py's prefork_server."
        )
