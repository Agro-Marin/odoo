"""Pure-pytest tests for ``odoo.service.lifecycle``.

Startup checks (the connection budget, the test-spec narrowing rule,
``preload_registries``' exit code) plus the process-lifetime surface:
``restart``, ``_reexec``, the watcher cleanup on ``start``'s error path, and
the ``server`` / ``server_phoenix`` single-source-of-truth invariants.

That second half was filed in ``test_server.py`` — which had reached 60
classes spanning 11 modules — even though this file already existed and is
where anyone would look for it.

Run with::

    python -m pytest tests/service/test_lifecycle.py -v
"""

import errno
import os
import signal
import threading
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def mod():
    """Return ``odoo.service.lifecycle``, imported once per session."""
    import odoo.service.lifecycle as m

    return m


@pytest.fixture(scope="module")
def srv():
    """The ``odoo.service.server`` façade.

    The classes moved here from ``test_server.py`` were written against it.
    ``restart`` and the phoenix flags are re-exported from ``lifecycle``, so the
    façade is what pins that they are reachable under both names — which is
    exactly what ``TestServerPhoenixSingleSourceOfTruth`` asserts.
    """
    import odoo.service.server as m

    return m


def make_config(**overrides):
    base = {
        "db_maxconn": 64,
        "db_maxconn_gevent": None,
        "db_port": 5432,
        "workers": 0,
        "max_cron_threads": 2,
        "job_workers": 2,
        "http_enable": True,
    }
    base.update(overrides)
    return base


def limits_cursor(max_connections=100, reserved=3, server_port=5432):
    """Answer the three reads ``_warn_on_connection_budget`` makes, in order.

    ``server_port`` is what ``inet_server_port()`` reports: equal to
    ``db_port`` for a direct connection, different behind a pooler, and None
    over a Unix-domain socket, which is what PostgreSQL returns there.
    """
    cr = MagicMock()
    cr.fetchone.side_effect = [
        (str(max_connections),),
        (str(reserved),),
        (server_port,),
    ]
    return cr


class TestConnectionBudgetDemand:
    """``db_maxconn`` is per-process; prefork multiplies it by every child."""

    def test_threaded_is_a_single_process(self, mod):
        with patch.object(mod, "config", make_config(workers=0)):
            assert mod._connection_budget_demand() == (1, 64)

    def test_prefork_counts_http_cron_job_and_the_evented_child(self, mod):
        with patch.object(
            mod, "config", make_config(workers=4, max_cron_threads=2, job_workers=2)
        ):
            processes, demand = mod._connection_budget_demand()
        assert processes == 9
        assert demand == 9 * 64

    def test_evented_child_uses_its_own_ceiling_when_set(self, mod):
        with patch.object(
            mod,
            "config",
            make_config(
                workers=1, max_cron_threads=0, job_workers=0, db_maxconn_gevent=8
            ),
        ):
            processes, demand = mod._connection_budget_demand()
        assert processes == 2
        assert demand == 64 + 8

    def test_no_evented_child_when_http_is_disabled(self, mod):
        with patch.object(
            mod,
            "config",
            make_config(
                workers=2, max_cron_threads=0, job_workers=0, http_enable=False
            ),
        ):
            processes, demand = mod._connection_budget_demand()
        assert processes == 2
        assert demand == 2 * 64

    def test_master_process_is_excluded(self, mod):
        """The prefork master calls ``db.close_all()`` before supervising."""
        with patch.object(
            mod, "config", make_config(workers=1, max_cron_threads=0, job_workers=0)
        ):
            processes, _ = mod._connection_budget_demand()
        assert processes == 2


class TestWarnOnConnectionBudget:
    """Advisory: warn and continue, never block a boot."""

    def _run(self, mod, config, cursor=None, connect_error=None):
        conn = MagicMock()
        conn.cursor.return_value = cursor if cursor is not None else limits_cursor()
        db_mock = MagicMock()
        if connect_error is not None:
            db_mock.db_connect.side_effect = connect_error
        else:
            db_mock.db_connect.return_value = conn
        logger = MagicMock()
        with (
            patch.object(mod, "config", config),
            patch.object(mod, "db", db_mock),
            patch.object(mod, "_logger", logger),
        ):
            mod._warn_on_connection_budget()
        return logger

    def test_warns_when_demand_exceeds_the_server(self, mod):
        logger = self._run(
            mod, make_config(workers=4, max_cron_threads=2, job_workers=2)
        )
        logger.warning.assert_called_once()
        args = logger.warning.call_args[0]
        assert args[1:] == (9, 576, 97, 100, 3, 10)

    def test_silent_when_the_budget_fits(self, mod):
        logger = self._run(
            mod,
            make_config(workers=4, max_cron_threads=2, job_workers=2, db_maxconn=10),
        )
        logger.warning.assert_not_called()

    def test_silent_on_the_threaded_default(self, mod):
        logger = self._run(mod, make_config(workers=0))
        logger.warning.assert_not_called()

    def test_silent_when_postgres_cannot_be_asked(self, mod):
        """A boot against an unreachable PG must not gain a spurious warning."""
        logger = self._run(
            mod,
            make_config(workers=8),
            connect_error=RuntimeError("no route to host"),
        )
        logger.warning.assert_not_called()

    def test_suggested_ceiling_is_never_zero(self, mod):
        """The advice has to be actionable even on an absurd worker count."""
        logger = self._run(
            mod, make_config(workers=200, max_cron_threads=0, job_workers=0)
        )
        assert logger.warning.call_args[0][-1] >= 1

    def test_no_advice_behind_a_pooler(self, mod):
        """A proxied connection reports the backend's port, not the dialled one.

        The comparison is meaningless there -- the workers contend for the
        pooler's client slots, not for ``max_connections`` -- and its advice is
        actively wrong, so it must be replaced by an INFO saying so.
        """
        logger = self._run(
            mod,
            make_config(workers=4, max_cron_threads=2, job_workers=2),
            cursor=limits_cursor(server_port=5433),
        )
        logger.warning.assert_not_called()
        logger.info.assert_called_once()

    def test_a_unix_socket_does_not_read_as_a_pooler(self, mod):
        """``inet_server_port()`` is NULL over a Unix-domain socket.

        Treating that as a port mismatch would silently disable the check on
        every socket-connected deployment, which is the common local one.
        """
        logger = self._run(
            mod,
            make_config(workers=4, max_cron_threads=2, job_workers=2),
            cursor=limits_cursor(server_port=None),
        )
        logger.warning.assert_called_once()

    def test_an_incomplete_config_cannot_break_the_boot(self, mod):
        """The guard must cover the config read, not only the SHOW queries.

        ``_warn_on_connection_budget`` runs on the boot path, so a check that
        exists only to print advice must never be the reason a server fails to
        start.  Regression: the config read sat outside the ``try``, and a
        mapping without ``db_maxconn`` raised ``KeyError`` out of ``start()``.
        """
        logger = self._run(mod, {"workers": 0})
        logger.warning.assert_not_called()

    def test_a_hostile_config_mapping_cannot_break_the_boot(self, mod):
        exploding = MagicMock()
        exploding.__getitem__.side_effect = RuntimeError("config is gone")
        logger = self._run(mod, exploding)
        logger.warning.assert_not_called()

    def test_skipped_in_the_evented_child(self, mod):
        """The master already warned; the subprocess would only duplicate it."""
        import odoo

        db_mock = MagicMock()
        logger = MagicMock()
        with (
            patch.object(odoo, "evented", True),
            patch.object(mod, "db", db_mock),
            patch.object(mod, "_logger", logger),
        ):
            mod._warn_on_connection_budget()
        db_mock.db_connect.assert_not_called()
        logger.warning.assert_not_called()


class TestNarrowingTestSpec:
    """``_narrowing_test_spec()``: does the run fail when a spec matches nothing?

    A ``--test-tags`` spec that selects no test used to collect zero tests and
    exit ``0``, so a near-miss read as a clean run. The three near-misses
    measured on this fork -- ``:WebSuite.test_core.@web/core/domain`` for
    ``:WebSuite.test_core[@web/core/domain]``, an unknown method, an unknown
    class -- all did exactly that.
    """

    @pytest.fixture
    def spec(self, mod):
        return mod._narrowing_test_spec

    def _with_tags(self, tags):
        import odoo.tools

        return odoo.tools.config.patch(test_tags=tags)

    @pytest.mark.parametrize("tags", ["", None, "+standard"])
    def test_implicit_selection_is_not_narrowing(self, spec, tags):
        """``--test-enable`` alone resolves to ``+standard``; a module that
        ships no tests legitimately runs zero under it."""
        with self._with_tags(tags):
            assert spec() == ""

    @pytest.mark.parametrize(
        "tags",
        [
            "/web:WebSuite.test_core[@web/core/domain]",
            "/base,-:TestReportsRendering",
            "post_install",
        ],
    )
    def test_explicit_selection_is_narrowing(self, spec, tags):
        with self._with_tags(tags):
            assert spec() == tags

    def test_surrounding_whitespace_is_ignored(self, spec):
        with self._with_tags("  +standard  "):
            assert spec() == ""


def preload_config(**overrides):
    base = {
        "limit_memory_soft": 0,
        "init": None,
        "update": None,
        "reinit": None,
        "test_enable": False,
    }
    base.update(overrides)
    return base


def make_report(*, successful=True, tests_run=1):
    report = MagicMock()
    report.wasSuccessful.return_value = successful
    report.testsRun = tests_run
    return report


class TestPreloadRegistriesReturnCode:
    """``preload_registries()`` is what ``odoo-bin`` returns to the shell.

    Nothing exercised it: the whole function was uncovered, and deleting the
    "matched no test at all" branch below flipped a real
    ``--test-tags /no_such_module --test-enable`` run from exit ``1`` to exit
    ``0`` — a vacuous run reporting success — while all 742 tests stayed green.
    Measured against a live database on this fork.

    ``Registry`` and the post-install runner are stubbed; the arithmetic that
    decides the exit code is the subject.
    """

    @pytest.fixture
    def preload(self, mod):
        def _run(dbnames, *, report=None, config_overrides=None, spec="", new=None):
            registry = MagicMock()
            registry._assertion_report = report
            registry_cls = MagicMock()
            registry_cls.new = new or MagicMock(return_value=registry)
            registry_cls.registries.count = 1
            logger = MagicMock()
            with (
                patch.object(mod, "Registry", registry_cls),
                patch.object(mod, "config", preload_config(**(config_overrides or {}))),
                patch.object(mod, "_run_post_install_tests") as post_install,
                patch.object(mod, "_narrowing_test_spec", return_value=spec),
                patch.object(mod, "_logger", logger),
            ):
                rc = mod.preload_registries(dbnames)
            return rc, logger, registry_cls, post_install

        return _run

    def test_clean_preload_returns_zero(self, preload):
        rc, _, _, _ = preload(["db1"], report=make_report())
        assert rc == 0

    def test_no_databases_is_not_a_failure(self, preload):
        assert preload([])[0] == 0
        assert preload(None)[0] == 0

    def test_failed_assertions_raise_the_return_code(self, preload):
        rc, _, _, _ = preload(
            ["db1"],
            report=make_report(successful=False),
            config_overrides={"test_enable": True},
        )
        assert rc == 1

    def test_every_failing_database_counts(self, preload):
        """``rc`` accumulates, so a caller can tell one bad database from four."""
        rc, _, _, _ = preload(
            ["a", "b", "c"],
            report=make_report(successful=False),
            config_overrides={"test_enable": True},
        )
        assert rc == 3

    def test_a_narrowed_spec_that_ran_nothing_fails_the_run(self, preload):
        """The guard proper: zero tests run under an explicit ``--test-tags``
        is a typo in the spec, not a pass."""
        rc, logger, _, _ = preload(
            ["db1"],
            report=make_report(tests_run=0),
            config_overrides={"test_enable": True},
            spec="/web:WebSuite.test_core.@web/core/domain",
        )
        assert rc == 1
        logged = " ".join(str(c) for c in logger.error.call_args_list)
        assert "matched no test" in logged
        assert "/web:WebSuite.test_core.@web/core/domain" in logged, (
            "the operator has to see which spec matched nothing"
        )

    def test_zero_tests_without_an_explicit_spec_is_fine(self, preload):
        """``--test-enable`` alone resolves to ``+standard``; a module that
        ships no tests must not fail the build."""
        rc, logger, _, _ = preload(
            ["db1"],
            report=make_report(tests_run=0),
            config_overrides={"test_enable": True},
            spec="",
        )
        assert rc == 0
        logger.error.assert_not_called()

    def test_a_successful_run_is_never_second_guessed(self, preload):
        """``wasSuccessful`` wins: tests ran and passed under a narrowing spec."""
        rc, _, _, _ = preload(
            ["db1"],
            report=make_report(tests_run=5),
            config_overrides={"test_enable": True},
            spec="/base",
        )
        assert rc == 0

    def test_post_install_tests_are_skipped_without_test_enable(self, preload):
        _, _, _, post_install = preload(["db1"], report=make_report())
        post_install.assert_not_called()

    def test_a_broken_database_aborts_the_whole_preload(self, preload):
        """``-1`` and an immediate return: the remaining databases are not
        attempted, and the caller must not read the failure as ``0``."""
        boom = MagicMock(side_effect=RuntimeError("registry is toast"))
        rc, logger, registry_cls, _ = preload(["db1", "db2"], new=boom)
        assert rc == -1
        assert registry_cls.new.call_count == 1, "db2 should never be attempted"
        logger.critical.assert_called_once()
        assert "db1" in str(logger.critical.call_args)

    def test_the_registry_cache_grows_to_hold_every_database(self, preload):
        """Fewer slots than databases means the last preload evicts the first,
        and the server re-builds every registry on its first request."""
        _, _, registry_cls, _ = preload(
            [f"db{i}" for i in range(40)], report=make_report()
        )
        assert registry_cls.registries.count >= 40


class TestReexecNtServiceRestart:
    """``_reexec`` must not start a SECOND server after the SCM restarted one.

    On Windows the SCM branch runs ``net stop && net start`` and then fell
    through to ``os.execve``.  When the SCM restart succeeds a fresh instance is
    already coming up, so the re-exec would put two servers on the same port and
    database.  When it FAILS, falling through is the right fallback — otherwise
    the operator gets a reload that silently did nothing.
    """

    def _run(self, scm_returncode):
        from odoo.service import lifecycle

        with (
            patch.object(
                lifecycle.osutil, "is_running_as_nt_service", return_value=True
            ),
            patch.object(
                lifecycle.subprocess, "call", return_value=scm_returncode
            ) as mock_call,
            patch.object(lifecycle.os, "execve") as mock_execve,
        ):
            lifecycle._reexec()
        return mock_call, mock_execve

    def test_successful_scm_restart_does_not_also_reexec(self):
        mock_call, mock_execve = self._run(0)
        mock_call.assert_called_once()
        mock_execve.assert_not_called()

    def test_failed_scm_restart_falls_back_to_reexec(self):
        mock_call, mock_execve = self._run(2)
        mock_call.assert_called_once()
        mock_execve.assert_called_once()


class TestServerPhoenixSingleSourceOfTruth:
    """``server`` and ``server_phoenix`` live only in ``lifecycle``.

    Regression: ``server.py`` used to expose them via a module ``__getattr__``
    forwarding to ``lifecycle``.  Because module ``__getattr__`` only fires for
    *absent* names, a single ``server.server_phoenix = X`` assignment created a
    real attribute that shadowed the forwarder permanently, silently desyncing
    later reads from ``lifecycle``.  The shim was removed; these tests pin that.
    """

    def test_lifecycle_is_the_canonical_holder(self):
        from odoo.service import lifecycle

        assert hasattr(lifecycle, "server")
        assert hasattr(lifecycle, "server_phoenix")

    def test_server_module_does_not_forward_phoenix(self, srv):
        # No forwarding ``__getattr__`` -> the name is simply absent here, so a
        # stray ``server.server_phoenix = X`` can never masquerade as canonical.
        with pytest.raises(AttributeError):
            _ = srv.server_phoenix

    def test_server_module_does_not_forward_server(self, srv):
        with pytest.raises(AttributeError):
            _ = srv.server


# ---------------------------------------------------------------------------
# lifecycle.start() — watcher cleanup on the error path
# ---------------------------------------------------------------------------


class TestLifecycleStartWatcherCleanup:
    """``lifecycle.start`` must stop the autoreload watcher even when the
    server's ``run()`` raises (e.g. a port-bind ``OSError`` surfacing from
    ``http_spawn``).

    Without a ``try/finally`` around ``server.run`` the watcher thread and its
    inotify kernel watches leak, and ``FSWatcherInotify.stop``'s
    ``del self.watcher`` — documented as freeing the watches before a reexec —
    never runs.
    """

    def test_watcher_stopped_when_server_run_raises(self):
        import odoo
        from odoo.service import lifecycle

        mock_server = MagicMock()
        mock_server.run.side_effect = OSError(errno.EADDRINUSE, "address in use")
        mock_watcher = MagicMock()
        fake_config = {"workers": 0, "dev_mode": ["reload"], "server_wide_modules": []}

        with (
            patch.object(lifecycle, "load_server_wide_modules"),
            patch.object(lifecycle, "config", fake_config),
            patch.object(odoo, "evented", False),
            patch("odoo.service.server.ThreadedServer", return_value=mock_server),
            patch.object(lifecycle, "inotify", True),
            patch.object(lifecycle, "FSWatcherInotify", return_value=mock_watcher),
            patch.object(lifecycle, "server_phoenix", False),
            # ``start()`` assigns the module global ``lifecycle.server`` itself
            # (``global server; server = ThreadedServer(...)``), so unlike every
            # other name patched here it is written by the code under test and
            # would survive this test.  ``test_metrics`` reads that global
            # through ``service_metrics()``; leaving a MagicMock behind made its
            # exposition unparseable, which only stayed hidden because
            # alphabetical collection puts test_metrics before test_server.
            # Patching it makes `patch` responsible for restoring it.
            patch.object(lifecycle, "server", None),
            pytest.raises(OSError),
        ):
            lifecycle.start()

        mock_watcher.start.assert_called_once()
        mock_watcher.stop.assert_called_once()


# ---------------------------------------------------------------------------
# restart() — guard against pre-start invocation
# ---------------------------------------------------------------------------


class TestRestartGuard:
    """``restart()`` must no-op when ``server`` has not been assigned yet.

    Regression: previously raised ``AttributeError: 'NoneType' has no
    attribute 'pid'`` if an addon triggered ``restart()`` during
    ``load_server_wide_modules()`` before ``start()`` set the module global.
    """

    def test_restart_with_none_server_is_noop(self, srv, caplog):
        """If ``server`` is None, restart() must log a warning and return."""
        with (
            # restart() reads ``server`` from lifecycle, not from the
            # server-module re-export — see test_restart_with_real_server.
            patch("odoo.service.lifecycle.server", None),
            patch.object(os, "kill") as mock_kill,
            patch.object(threading, "Thread") as mock_thread,
            caplog.at_level("WARNING", logger="odoo.service.server"),
        ):
            srv.restart()

        mock_kill.assert_not_called()
        mock_thread.assert_not_called()
        assert any("restart() called before" in m for m in caplog.messages)

    def test_restart_with_real_server_posix_sends_sighup(self, srv):
        """Baseline: when server exists, POSIX path sends SIGHUP to its pid."""
        fake_server = MagicMock()
        fake_server.pid = 12345

        # ``restart()`` reads ``server`` from ``odoo.service.lifecycle`` directly
        # (server.py forwards via ``__getattr__``).  Patching the server-module
        # re-export sets a shadowing attribute that the lifecycle-side
        # function never reads.
        with (
            patch("odoo.service.lifecycle.server", fake_server),
            patch.object(os, "name", "posix"),
            patch.object(os, "kill") as mock_kill,
        ):
            srv.restart()

        mock_kill.assert_called_once_with(12345, signal.SIGHUP)

    def test_threaded_server_reload_delegates_to_lifecycle(self, srv):
        """``ThreadedServer.reload`` must route through ``lifecycle.restart``.

        Regression: previously called ``os.kill(self.pid, signal.SIGHUP)``
        directly, which raises ``AttributeError`` on Windows (no
        ``signal.SIGHUP``).  ``lifecycle.restart`` already handles both
        branches: SIGHUP on POSIX, a background ``_reexec`` thread on
        Windows.
        """
        ts = object.__new__(srv.ThreadedServer)
        ts.pid = 12345
        with patch("odoo.service.lifecycle.restart") as mock_restart:
            ts.reload()
        mock_restart.assert_called_once_with()

    def test_threaded_server_reload_is_windows_safe(self, srv):
        """Simulating Windows (no signal.SIGHUP), ``reload`` must not crash.

        Goes through ``lifecycle.restart``'s ``os.name == 'nt'`` branch,
        which spawns a background ``_reexec`` thread.  ``reload`` itself
        must reference no Windows-incompatible signal constants.
        """
        ts = object.__new__(srv.ThreadedServer)
        ts.pid = 12345
        # Force the NT branch inside lifecycle.restart and stub _reexec so
        # nothing actually re-execs in the test process.
        from odoo.service import lifecycle

        with (
            patch("odoo.service.lifecycle.server", ts),
            patch.object(lifecycle.os, "name", "nt"),
            patch.object(lifecycle, "_reexec") as mock_reexec,
            patch.object(lifecycle.threading, "Thread") as mock_thread,
        ):
            ts.reload()
        # The Windows branch must spawn a Thread on _reexec specifically.
        # Accept it passed either way round, but never accept "some thread was
        # started": the earlier `... or mock_thread.call_args.args` fallback
        # made any positional callable pass, so pointing the branch at an
        # unrelated function went unnoticed.
        mock_thread.assert_called_once()
        args, kwargs = mock_thread.call_args
        target = kwargs.get("target", args[0] if args else None)
        assert target is mock_reexec, (
            f"the Windows restart branch spawned a thread on {target!r}, not "
            f"_reexec; the process would never re-exec"
        )
        mock_thread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# SIGHUP — local sentinel, no signal-module monkey-patch
# ---------------------------------------------------------------------------


# ``ThreadedServer.start()`` must not install SIGCHLD -- a handler with no
# SIGCHLD branch caused spurious main-loop wakeups every time a subprocess
# (pg_dump, psql) exited.  Covered by driving ``start()`` and reading back the
# signals it registered: ``TestStartInstallsTheHandlers`` in
# ``test_threaded_lifecycle.py`` asserts SIGCHLD is absent from that set, and
# the same fixture asserts the handlers that must be present -- which the AST
# walk formerly here could not, since it only rejected one call shape.


# ---------------------------------------------------------------------------
# _ON_STOP_FUNCS module-level + backward-compatible class alias
# ---------------------------------------------------------------------------


class TestSigHupSentinel:
    """server.py must not install ``signal.SIGHUP = -1`` on Windows — that
    monkey-patches a stdlib module globally. The fix exposes a local
    ``_SIGHUP_AVAILABLE`` boolean instead and guards call sites with it.
    """

    def test_local_sentinel_exported(self, srv):
        assert hasattr(srv, "_SIGHUP_AVAILABLE")
        assert isinstance(srv._SIGHUP_AVAILABLE, bool)

    def test_on_posix_sentinel_is_true(self, srv):
        """On Linux (the project's target OS) the sentinel must be True."""
        import os

        if os.name == "posix":
            assert srv._SIGHUP_AVAILABLE is True

    # ``ThreadedServer.signal_handler``'s use of the sentinel is covered
    # behaviourally, by running it against a signal module with no SIGHUP —
    # see ``TestSignalHandlerOnAPlatformWithoutSighup`` in
    # ``test_threaded_lifecycle.py``.  The AST walk that used to live here only
    # proved the name appeared in an ``if`` test.
