"""Pure-pytest tests for ``odoo.service.server``.

Covers the process-local components of the service layer.  No live database,
no ``fork()``, and no Odoo module loading.

A few tests do bind a real loopback socket and run a real thread — the
``EventServer`` shutdown cases need werkzeug's own ``serve_forever`` to
reproduce the ``shutdown()``-before-``serve_forever`` deadlock, which only
exists between two real threads.  In-process and sub-second, so they are not
process-suite material.

NOT covered here (require live infra / fork):
  - PreforkServer.run() / worker_spawn() — fork-based, belong in integration tests
  - ThreadedServer.run() — requires a bound socket and real HTTP traffic
  - WorkerCron.start() / stop() — call real OS/psycopg setup

Siblings, so the subject of this file stays "the servers" rather than
"everything under ``odoo/service``".  It had drifted to 60 classes spanning 11
modules, which is how two admin-auth gates once ended up filed in a file about
the HTTP server:

  - ``test_threaded_lifecycle.py`` — ThreadedServer signal wiring + graceful stop
  - ``test_lifecycle.py``          — restart / _reexec / phoenix flags / startup checks
  - ``test_watcher.py``            — the ``--dev`` autoreloader
  - ``test_cron.py``               — cron scheduling order + served-database list
  - ``test_http_bind_failure.py``  — a failed bind must reach the logger
  - ``test_dump_scanner.py``       — the restore meta-command scanner

Run with::

    python -m pytest tests/service/ -v
"""

import contextlib
import errno
import fcntl
import http.server
import itertools
import logging
import os
import signal
import socket
import threading
import time
from collections import deque
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import psutil
import psycopg
import pytest
import werkzeug.serving

from odoo.service import _base_server, _helpers, _prefork, _threaded

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def srv():
    """Return the ``odoo.service.server`` façade module.

    Module-scoped for symmetry with the other suites, not for speed: the
    submodules are already imported at the top of this file, so the import
    chain is paid at collection either way.
    """
    import odoo.service.server as mod

    return mod


# ---------------------------------------------------------------------------
# Infrastructure fixtures
# ---------------------------------------------------------------------------


def stamp_rpc_model_method(monkeypatch, value=""):
    """Set ``rpc_model_method`` on the calling thread, with teardown OWNED.

    ``wsgi.log_request`` reads it off ``threading.current_thread()``, so the
    tests that exercise the log line have to set it — but under pytest that is
    the MainThread, which outlives them.

    This file used to carry an ``autouse`` fixture that restored the attribute
    for all 266 tests.  That silently disabled ``conftest``'s
    ``_no_global_state_leak`` guard across the whole file: conftest fixtures are
    outer, so the blanket restore tore down FIRST and the guard could never
    observe a leak here.  Verified by flipping it to ``autouse=False`` — the
    ``log_handler`` fixture below was leaking an empty ``rpc_model_method`` into
    every later test and nothing said so.

    ``monkeypatch`` is what the guard's own failure message asks for ("add the
    name to this test's own patch list, so ``patch`` owns the teardown"), and
    being opt-in it leaves the guard armed for every test that does NOT declare
    ownership.
    """
    monkeypatch.setattr(
        threading.current_thread(), "rpc_model_method", value, raising=False
    )


@pytest.fixture
def multi():
    """Minimal PreforkServer stub sufficient for Worker / WorkerCron construction.

    ``Worker.__init__`` calls ``multi.pipe_new()`` **twice** and immediately
    unpacks each result as ``(r, w)``, so we must provide real OS pipe pairs —
    a plain ``MagicMock()`` return value cannot be unpacked by position.
    """
    m = MagicMock()
    pipes = [os.pipe(), os.pipe()]
    m.pipe_new.side_effect = list(pipes)
    m.timeout = 60
    m.cron_timeout = None
    m.limit_request = 100
    m.socket = None
    m.beat = 4
    yield m
    for r, w in pipes:
        for fd in (r, w):
            with contextlib.suppress(OSError):
                os.close(fd)


@pytest.fixture
def worker_cron(srv, multi):
    """WorkerCron with ``pid`` and ``dbcursor`` pre-set, ready for unit testing.

    ``dbcursor.connection`` is aliased to ``dbcursor._cnx`` so tests can set
    side-effects on either handle: the real fork's ``Cursor.connection``
    property returns ``self._cnx``, so these two attributes point at the
    same object in production.
    """
    wc = srv.WorkerCron(multi)
    wc.pid = os.getpid()
    wc.dbcursor = MagicMock()
    shared_cnx = MagicMock()
    wc.dbcursor._cnx = shared_cnx
    wc.dbcursor.connection = shared_cnx
    return wc


@pytest.fixture
def prefork_server(srv):
    """PreforkServer instance that bypasses ``__init__`` (which reads config/sockets).

    Only the attributes consumed by the tested methods are populated.
    """
    obj = object.__new__(srv.PreforkServer)
    obj.queue = deque()
    obj.population = 4
    obj.logger = MagicMock()
    obj.workers = {}
    obj.long_polling_pid = None
    obj.long_polling_popen = None
    obj.long_polling_spawn_time = 0.0
    # Fork-storm respawn-throttle state (consumed by process_zombie ->
    # _note_worker_exit and process_spawn).
    obj._consecutive_fast_deaths = 0
    obj._respawn_not_before = 0.0
    # psutil handles kept across a drain so ``_sweep_stale_workers`` can tell a
    # surviving worker from a recycled pid.  Empty = "every pid already gone".
    obj._drain_procs = {}
    return obj


# ---------------------------------------------------------------------------
# empty_pipe()
# ---------------------------------------------------------------------------


class TestEmptyPipe:
    """``empty_pipe(fd)``: drains all bytes from a non-blocking readable fd."""

    def test_drains_all_data(self):
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            os.write(w, b"hello world")
            _helpers.empty_pipe(r)
            with pytest.raises(BlockingIOError):
                os.read(r, 1)  # pipe must be empty
        finally:
            os.close(r)
            os.close(w)

    def test_already_empty_does_not_raise(self):
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            _helpers.empty_pipe(r)  # no data written — must not block or raise
        finally:
            os.close(r)
            os.close(w)

    def test_drains_multiple_bytes(self):
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            os.write(w, b"a" * 512)
            _helpers.empty_pipe(r)
            with pytest.raises(BlockingIOError):
                os.read(r, 1)
        finally:
            os.close(r)
            os.close(w)


# ---------------------------------------------------------------------------
# FSWatcherBase.handle_file()
# ---------------------------------------------------------------------------


class TestEventServerWatchdogSurvivesErrors:
    """The evented watchdog thread is the ONLY enforcement of the memory soft
    limit and the parent-death check for that subprocess.

    ``process_limits`` touches psutil and ``os.kill``, both of which can fail
    transiently (process vanished, ``/proc`` read error, a signal racing).  The
    exception escaped the ``while True`` loop, so the thread died and both
    checks stopped being enforced for the rest of the process's life — silently.
    """

    def test_transient_failure_does_not_retire_the_watchdog(self, srv):
        server = srv.EventServer.__new__(srv.EventServer)
        server.logger = logging.getLogger("test.evented.watchdog")
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise psutil.NoSuchProcess(1234)

        class _StopLoop(Exception):
            pass

        def fake_sleep(_beat):
            if len(calls) >= 2:
                raise _StopLoop

        with (
            patch.object(server, "process_limits", flaky),
            patch.object(_threaded.time, "sleep", fake_sleep),
            patch.object(os, "getppid", return_value=1),
        ):
            with pytest.raises(_StopLoop):
                server.watchdog(beat=0)
        assert len(calls) == 2, "watchdog stopped checking after one failure"


class TestPreforkServerProcessSignals:
    """``process_signals()``: drains the signal queue and dispatches each signal."""

    def test_sigint_raises_keyboard_interrupt(self, prefork_server):
        prefork_server.queue.append(signal.SIGINT)
        with pytest.raises(KeyboardInterrupt):
            prefork_server.process_signals()

    def test_sigterm_raises_keyboard_interrupt(self, prefork_server):
        prefork_server.queue.append(signal.SIGTERM)
        with pytest.raises(KeyboardInterrupt):
            prefork_server.process_signals()

    def test_sighup_sets_phoenix_flag_and_raises(self, prefork_server):
        """SIGHUP must set ``server_phoenix`` before raising ``KeyboardInterrupt``.

        ``server_phoenix`` lives in ``lifecycle`` (single source of truth); the
        ``patch`` context restores it on exit so the test leaves no global
        residue — and there is no ``server.server_phoenix`` forwarder to shadow.
        """
        from odoo.service import lifecycle

        prefork_server.queue.append(signal.SIGHUP)
        with patch.object(lifecycle, "server_phoenix", False):
            with pytest.raises(KeyboardInterrupt):
                prefork_server.process_signals()
            assert lifecycle.server_phoenix is True

    def test_sigttin_increments_population(self, prefork_server):
        prefork_server.queue.append(signal.SIGTTIN)
        prefork_server.process_signals()
        assert prefork_server.population == 5

    def test_sigttou_decrements_population(self, prefork_server):
        prefork_server.queue.append(signal.SIGTTOU)
        prefork_server.process_signals()
        assert prefork_server.population == 3

    def test_multiple_signals_processed_in_order(self, prefork_server):
        """SIGTTIN followed by SIGTTOU must cancel out."""
        prefork_server.queue.append(signal.SIGTTIN)
        prefork_server.queue.append(signal.SIGTTOU)
        prefork_server.process_signals()
        assert prefork_server.population == 4

    def test_empty_queue_is_noop(self, prefork_server):
        prefork_server.process_signals()  # must not raise
        assert prefork_server.population == 4


# ---------------------------------------------------------------------------
# PreforkServer.fork_and_reload() — http_enable=False reload guard
# ---------------------------------------------------------------------------


class TestPreforkForkAndReloadNoSocket:
    """A prefork node with ``http_enable = False`` (dedicated cron/job worker)
    never creates ``self.socket``.  A SIGHUP reload must not dereference it: the
    parent branch of ``fork_and_reload`` used to call ``self.socket.fileno()``
    unconditionally, crashing the master AFTER the fork (SIGTERM-ing every worker
    mid-job) and stranding the child for the full reload timeout."""

    def test_reload_without_socket_reaches_reexec(self, prefork_server):
        prefork_server.socket = None  # http_enable=False leaves it None
        # Capture the environ inside _reexec (patch.dict reverts it on exit).
        seen = {}

        def fake_reexec(*a, **k):
            seen["env"] = dict(os.environ)
            raise SystemExit("reexec-sentinel")

        with (
            patch("odoo.service._prefork.os.fork", return_value=4242),
            patch("odoo.service._prefork._reexec", fake_reexec),
            patch.dict("odoo.service._prefork.os.environ", {}, clear=False),
        ):
            with pytest.raises(SystemExit, match="reexec-sentinel"):
                prefork_server.fork_and_reload()
        # Reached _reexec with no AttributeError: the socketless path is handled.
        assert "env" in seen
        # And no stale fd was advertised to the re-exec'd master.
        assert "ODOO_HTTP_SOCKET_FD" not in seen["env"]

    def test_reload_with_socket_hands_off_fd(self, prefork_server):
        """The normal (http_enable=True) path still exports the socket fd."""
        sock = MagicMock()
        sock.fileno.return_value = 7
        prefork_server.socket = sock
        seen = {}

        def fake_reexec(*a, **k):
            seen["env"] = dict(os.environ)
            raise SystemExit

        with (
            patch("odoo.service._prefork.os.fork", return_value=4242),
            patch("odoo.service._prefork._reexec", fake_reexec),
            patch("odoo.service._prefork.fcntl.fcntl", return_value=0),
            patch.dict("odoo.service._prefork.os.environ", {}, clear=False),
        ):
            with pytest.raises(SystemExit):
                prefork_server.fork_and_reload()
        assert seen["env"].get("ODOO_HTTP_SOCKET_FD") == "7"


# ---------------------------------------------------------------------------
# server_phoenix / server — single source of truth (lifecycle)
# ---------------------------------------------------------------------------


class TestWorkerCronConnectPostgres:
    """``_connect_postgres()``: opens a postgres connection and sets up LISTEN."""

    def _mock_db(self, *, in_recovery: bool):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (in_recovery,)
        conn.cursor.return_value = cursor
        return conn, cursor

    def _connect(self, worker_cron, in_recovery):
        """Helper: call ``_connect_postgres`` with mocked DB and selector."""
        conn, cursor = self._mock_db(in_recovery=in_recovery)
        with (
            patch(
                "odoo.service._worker.db.db_connect", return_value=conn
            ) as mock_connect,
            patch(
                "odoo.service._worker.selectors.DefaultSelector",
                return_value=MagicMock(),
            ),
        ):
            worker_cron._connect_postgres()
        return conn, cursor, mock_connect

    def test_executes_listen_when_not_in_recovery(self, worker_cron):
        _, cursor, _ = self._connect(worker_cron, in_recovery=False)
        executed = [c.args[0] for c in cursor.execute.call_args_list]
        assert "LISTEN cron_trigger" in executed

    def test_skips_listen_in_recovery_mode(self, worker_cron):
        _, cursor, _ = self._connect(worker_cron, in_recovery=True)
        executed = [c.args[0] for c in cursor.execute.call_args_list]
        assert "LISTEN cron_trigger" not in executed

    def test_commits_after_listen(self, worker_cron):
        """``COMMIT`` ensures the LISTEN takes effect within the transaction."""
        _, cursor, _ = self._connect(worker_cron, in_recovery=False)
        cursor.commit.assert_called_once()

    def test_sets_dbcursor_on_self(self, worker_cron):
        _, cursor, _ = self._connect(worker_cron, in_recovery=False)
        assert worker_cron.dbcursor is cursor

    def test_connects_to_postgres_database(self, worker_cron):
        """Must connect to the ``postgres`` maintenance database, not a tenant db."""
        _, _, mock_connect = self._connect(worker_cron, in_recovery=False)
        mock_connect.assert_called_once_with("postgres")


# ---------------------------------------------------------------------------
# WorkerCron.sleep() — idle select must not outlast the master watchdog
# ---------------------------------------------------------------------------


class TestWorkerCronSleepWatchdog:
    """``sleep()``: the idle select timeout is capped by ``watchdog_timeout``.

    ``_runloop`` pings the master watchdog once per cycle, before ``sleep()``.
    If the idle select blocks for ``SLEEP_INTERVAL`` (60-69s) while the cron
    watchdog (``limit_time_real_cron``) is shorter, the master SIGKILLs the
    idle worker and re-forks it in a loop.
    """

    def _select_timeout(self, worker_cron):
        """Run sleep() with an empty queue and capture the select() timeout."""
        worker_cron.db_queue.clear()
        worker_cron._pg_selector = MagicMock()
        with (
            patch("odoo.service._worker.time.sleep"),
            patch("odoo.service._worker.empty_pipe"),
        ):
            worker_cron.sleep()
        return worker_cron._pg_selector.select.call_args.kwargs["timeout"]

    def test_idle_sleep_capped_below_tight_watchdog(self, worker_cron):
        worker_cron.watchdog_timeout = 30  # e.g. limit_time_real_cron=30
        timeout = self._select_timeout(worker_cron)
        assert timeout <= 15, timeout  # half the watchdog, leaves ping headroom

    def test_idle_sleep_uncapped_when_watchdog_disabled(self, worker_cron):
        worker_cron.watchdog_timeout = None  # limit_time_real_cron=0
        timeout = self._select_timeout(worker_cron)
        # SLEEP_INTERVAL (60) + pid % 10 — full interval, no cap.
        assert timeout >= 60, timeout

    def test_default_watchdog_does_not_shorten_idle_sleep_below_interval(
        self, worker_cron
    ):
        worker_cron.watchdog_timeout = 120  # default (-1 -> limit_time_real)
        timeout = self._select_timeout(worker_cron)
        assert timeout >= 60, timeout  # 120/2 == 60 >= 60-69 floor


# ---------------------------------------------------------------------------
# WorkerCron.process_work() — reconnect logic (the bug we fixed)
# ---------------------------------------------------------------------------


class TestWorkerCronProcessWorkReconnect:
    """``process_work()``: recovers from SSL/connection drops without crashing."""

    def test_operational_error_triggers_reconnect(self, worker_cron):
        """An SSL drop during ``notifies()`` must call ``_connect_postgres()``."""
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError(
            "SSL connection has been closed unexpectedly"
        )
        with (
            patch("odoo.service._worker.cron_database_list", return_value=["testdb"]),
            patch.object(worker_cron, "_connect_postgres") as mock_reconnect,
        ):
            worker_cron.process_work()
        mock_reconnect.assert_called_once()

    def test_operational_error_returns_early(self, worker_cron):
        """After reconnecting, no database is queued or processed in this cycle."""
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError(
            "SSL"
        )
        with (
            patch("odoo.service._worker.cron_database_list", return_value=["db1"]),
            patch.object(worker_cron, "_connect_postgres"),
        ):
            worker_cron.process_work()
        assert len(worker_cron.db_queue) == 0
        assert worker_cron.db_count == 0

    def test_operational_error_closes_cnx_before_cursor(self, worker_cron):
        """Connection must be closed before the cursor — mirrors ``stop()`` order."""
        old_cnx = worker_cron.dbcursor.connection
        old_cursor = worker_cron.dbcursor
        call_order = []
        old_cnx.close.side_effect = lambda: call_order.append("cnx")
        old_cursor.close.side_effect = lambda: call_order.append("cursor")
        old_cnx.notifies.side_effect = psycopg.OperationalError("SSL")

        with (
            patch("odoo.service._worker.cron_database_list", return_value=[]),
            patch.object(worker_cron, "_connect_postgres"),
        ):
            worker_cron.process_work()

        assert call_order == ["cnx", "cursor"]

    def test_close_error_on_broken_connection_is_suppressed(self, worker_cron):
        """A broken connection that also raises on ``close()`` must not prevent reconnect."""
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError(
            "SSL"
        )
        worker_cron.dbcursor.connection.close.side_effect = Exception("already closed")
        worker_cron.dbcursor.close.side_effect = Exception("already closed")

        with (
            patch("odoo.service._worker.cron_database_list", return_value=["db1"]),
            patch.object(worker_cron, "_connect_postgres") as mock_reconnect,
        ):
            worker_cron.process_work()  # must not raise

        mock_reconnect.assert_called_once()

    def test_reconnect_failure_does_not_propagate(self, worker_cron):
        """If ``_connect_postgres()`` itself fails, the worker stays alive.

        Previously this raised the error to ``_runloop``, which killed the
        worker and forced master to fork a replacement.  Master forks at
        ~master.beat (4s) intervals, the new worker starts with attempts=0,
        sleeps 2s, and dies again — escalation never happens.

        The fix keeps the worker alive so the ``_reconnect_attempts``
        counter actually escalates within one process.  The next cycle
        sees the bumped counter and waits longer, up to the 60s cap.
        """
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError(
            "SSL"
        )
        with (
            patch("odoo.service._worker.cron_database_list", return_value=["db1"]),
            patch.object(
                worker_cron,
                "_connect_postgres",
                side_effect=psycopg.OperationalError("postgres still unreachable"),
            ),
            patch("odoo.service._worker.time.sleep"),
        ):
            # Must NOT raise — the worker survives so the next cycle can
            # retry with an elevated backoff counter.
            worker_cron.process_work()
        assert worker_cron._reconnect_attempts == 1

    def test_reconnect_attempts_escalate_across_cycles(self, worker_cron):
        """Within one worker, repeated reconnect failures grow the backoff.

        ``_sleep_with_watchdog`` chunks the wait into ``master.beat / 2``
        slices (default 2s) so the master watchdog sees fresh pipe pings
        every half-beat.  We assert the per-cycle SUM of sleeps matches
        the expected backoff, not the chunk count, so future tweaks to the
        chunk size don't break the test.
        """
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError(
            "SSL"
        )
        per_cycle_sleeps: list[list[float]] = []
        current_cycle_sleeps: list[float] = []
        with (
            patch("odoo.service._worker.cron_database_list", return_value=["db1"]),
            patch.object(
                worker_cron,
                "_connect_postgres",
                side_effect=Exception("PG down"),
            ),
            patch(
                "odoo.service._worker.time.sleep",
                side_effect=lambda s: current_cycle_sleeps.append(s),  # noqa: PLW0108
            ),
        ):
            for _ in range(7):
                current_cycle_sleeps = []
                worker_cron.process_work()
                per_cycle_sleeps.append(current_cycle_sleeps)
        cycle_totals = [sum(c) for c in per_cycle_sleeps]
        # 2, 4, 8, 16, 32, 60, 60 — capped at 60
        assert cycle_totals == [2, 4, 8, 16, 32, 60, 60]
        # Pings during sleep must keep watchdog fresh: every chunk is at
        # most master.beat / 2 (default 2s) so the master sees a ping
        # within every beat window.
        max_chunk = worker_cron.multi.beat / 2
        for cycle in per_cycle_sleeps:
            for chunk in cycle:
                assert chunk <= max_chunk + 1e-6, (
                    f"chunk {chunk} exceeds master.beat/2 = {max_chunk}"
                )


# ---------------------------------------------------------------------------
# WorkerCron.start() — boot-time PG-connect backoff must yield to a stop signal
# ---------------------------------------------------------------------------


class TestWorkerCronStartGracefulShutdown:
    """During a PG outage at worker boot, every connect attempt fails and the
    worker sleeps with an escalating backoff.  A graceful stop
    (``PreforkServer.stop_workers_gracefully`` sends SIGINT → ``signal_handler``
    sets ``alive = False``) must end the retry loop so ``start()`` returns and
    the worker exits cleanly via ``run()``'s already-dead ``_runloop``.

    Before the fix the loop was ``while True``: a cron worker stuck connecting
    during a PG outage ignored SIGINT and kept pinging its watchdog, so the
    master's ``while self.workers`` drain loop hung until a second, forced
    signal.
    """

    def test_start_stops_retrying_when_alive_cleared(self, worker_cron):
        worker_cron._selector = MagicMock()  # Worker.start is patched out below
        worker_cron.multi.socket = None
        sleep_calls = []

        def stop_after_first(secs):
            # Emulate the SIGINT handler firing mid-backoff.
            sleep_calls.append(secs)
            worker_cron.alive = False
            if len(sleep_calls) > 1:
                raise AssertionError(
                    "start() kept retrying PG after alive was cleared "
                    "(boot-time connect loop ignores graceful stop)"
                )

        with (
            patch.object(
                worker_cron,
                "_connect_postgres",
                side_effect=Exception("PG unreachable"),
            ),
            patch.object(
                worker_cron,
                "_sleep_with_watchdog",
                side_effect=stop_after_first,
            ),
            patch("odoo.service._worker.Worker.start"),
            patch("odoo.service._worker.os.nice"),
        ):
            worker_cron.start()  # must return promptly, not loop forever

        assert sleep_calls == [2]  # one failed attempt (2 ** 1), then loop yielded
        assert worker_cron.alive is False

    def test_sleep_with_watchdog_breaks_when_alive_cleared(self, worker_cron):
        """A multi-second backoff sleep must abort once the worker is no longer
        alive, so a 60s boot/reconnect backoff cannot delay graceful shutdown."""
        slept = []

        def fake_sleep(chunk):
            slept.append(chunk)
            worker_cron.alive = False  # stop signal lands during the first chunk

        with patch("odoo.service._worker.time.sleep", side_effect=fake_sleep):
            worker_cron._sleep_with_watchdog(60)

        # Only the first half-beat chunk elapsed; the remaining ~58s were skipped.
        assert slept == [worker_cron.multi.beat / 2]
        assert sum(slept) < 60


# ---------------------------------------------------------------------------
# WorkerCron.process_work() — scheduling logic
# ---------------------------------------------------------------------------


class TestWorkerCronProcessWorkScheduling:
    """``process_work()``: database queue building and processing order."""

    @pytest.fixture
    def mock_ir_cron(self):
        """Stub the deferred ``IrCron`` import inside ``process_work()``."""
        mock_module = MagicMock()
        with patch.dict(
            "sys.modules", {"odoo.addons.base.models.ir_cron": mock_module}
        ):
            yield mock_module.IrCron

    def test_no_databases_returns_immediately(self, worker_cron):
        worker_cron.dbcursor.connection.notifies.return_value = iter([])
        with patch("odoo.service._worker.cron_database_list", return_value=[]):
            worker_cron.process_work()
        assert len(worker_cron.db_queue) == 0
        assert worker_cron.db_count == 0

    def test_all_databases_queued_on_first_call(self, worker_cron, mock_ir_cron):
        """First call with an empty queue must enqueue all databases and process one."""
        worker_cron.dbcursor.connection.notifies.return_value = iter([])
        with (
            patch(
                "odoo.service._worker.cron_database_list",
                return_value=["db1", "db2", "db3"],
            ),
            patch("odoo.service._worker.db"),
        ):
            worker_cron.process_work()
        # db_count is set before popleft; one db already processed
        assert worker_cron.db_count == 3
        assert len(worker_cron.db_queue) == 2  # remaining after first pop

    def test_notified_database_placed_first_in_queue(self, worker_cron, mock_ir_cron):
        """Notified databases must be prioritised over non-notified ones."""
        notif = MagicMock()
        notif.channel = "cron_trigger"
        notif.payload = "urgent_db"
        worker_cron.dbcursor.connection.notifies.return_value = iter([notif])

        with (
            patch(
                "odoo.service._worker.cron_database_list",
                return_value=["slow_db", "urgent_db"],
            ),
            patch("odoo.service._worker.db"),
        ):
            worker_cron.process_work()

        # urgent_db was popped and processed first; slow_db remains
        assert "slow_db" in worker_cron.db_queue
        assert "urgent_db" not in worker_cron.db_queue

    def test_notified_db_not_in_db_list_is_ignored(self, worker_cron, mock_ir_cron):
        """A NOTIFY payload for an unknown database must be silently discarded."""
        notif = MagicMock()
        notif.channel = "cron_trigger"
        notif.payload = "unknown_db"
        worker_cron.dbcursor.connection.notifies.return_value = iter([notif])

        with (
            patch("odoo.service._worker.cron_database_list", return_value=["real_db"]),
            patch("odoo.service._worker.db"),
        ):
            worker_cron.process_work()

        all_dbs = list(worker_cron.db_queue) + [
            mock_ir_cron._process_jobs.call_args[0][0]
        ]
        assert "unknown_db" not in all_dbs

    def test_existing_queue_skips_notification_polling(self, worker_cron, mock_ir_cron):
        """When ``db_queue`` is non-empty, ``notifies()`` must not be called."""
        worker_cron.db_queue.append("pending_db")
        worker_cron.db_count = 1

        with patch("odoo.service._worker.db"):
            worker_cron.process_work()

        worker_cron.dbcursor.connection.notifies.assert_not_called()

    def test_request_count_incremented(self, worker_cron, mock_ir_cron):
        worker_cron.dbcursor.connection.notifies.return_value = iter([])
        with (
            patch("odoo.service._worker.cron_database_list", return_value=["db1"]),
            patch("odoo.service._worker.db"),
        ):
            worker_cron.process_work()
        assert worker_cron.request_count == 1


# ---------------------------------------------------------------------------
# Worker.stop() / WorkerCron.stop() — resource release
# ---------------------------------------------------------------------------


class TestWorkerStopReleasesResources:
    """A prefork worker exits by returning from ``run()``; ``stop()`` is the only
    place its selector, LISTEN connection and cursor are released.

    Each worker is replaced on exit — on a request cap, a memory soft limit, or
    a crash-respawn — so anything missed here is not leaked once but once per
    recycle, for the life of the master.
    """

    def test_selector_is_closed(self, bare_worker):
        bare_worker._selector = MagicMock()
        bare_worker.stop()
        bare_worker._selector.close.assert_called_once_with()

    def test_stop_before_start_does_not_raise(self, srv):
        """``stop()`` runs in ``run()``'s ``finally``, which is reachable when
        the worker dies during setup and never built its selector."""
        w = object.__new__(srv.Worker)
        w.stop()

    def test_cron_worker_closes_selector_connection_and_cursor(self, worker_cron):
        worker_cron._pg_selector = MagicMock()
        worker_cron.stop()
        worker_cron._pg_selector.close.assert_called_once_with()
        worker_cron.dbcursor.connection.close.assert_called_once_with()
        worker_cron.dbcursor.close.assert_called_once_with()

    def test_a_failing_connection_close_still_closes_the_cursor(self, worker_cron):
        """The two closes are suppressed *separately* on purpose.

        A dead LISTEN connection is the normal case here — the worker is often
        stopping precisely because Postgres went away — and that is exactly when
        ``connection.close()`` raises.  Under a single shared ``suppress`` the
        raise would skip ``dbcursor.close()``, so the failure mode that makes
        cleanup necessary is the one that skips it.
        """
        worker_cron._pg_selector = MagicMock()
        worker_cron.dbcursor.connection.close.side_effect = psycopg.OperationalError(
            "server closed the connection unexpectedly"
        )

        worker_cron.stop()

        worker_cron.dbcursor.close.assert_called_once_with()

    def test_a_failing_cursor_close_does_not_escape(self, worker_cron):
        """``stop()`` runs in a ``finally`` during shutdown; raising here would
        replace the real exit reason with a cleanup error."""
        worker_cron._pg_selector = MagicMock()
        worker_cron.dbcursor.close.side_effect = psycopg.OperationalError("gone")
        worker_cron.stop()


# ---------------------------------------------------------------------------
# WorkerCron.check_limits()
# ---------------------------------------------------------------------------


class TestWorkerCronCheckLimits:
    """``WorkerCron.check_limits()``: alive_time age guard."""

    def test_worker_stays_alive_within_limit(self, srv, worker_cron):
        worker_cron.alive_time = time.monotonic()
        with (
            patch("odoo.service._worker.config", {"limit_time_worker_cron": 3600}),
            patch.object(srv.Worker, "check_limits"),
        ):
            worker_cron.check_limits()
        assert worker_cron.alive is True

    def test_worker_dies_when_age_exceeded(self, srv, worker_cron):
        worker_cron.alive_time = time.monotonic() - 99_999  # far in the past
        with (
            patch("odoo.service._worker.config", {"limit_time_worker_cron": 60}),
            patch.object(srv.Worker, "check_limits"),
        ):
            worker_cron.check_limits()
        assert worker_cron.alive is False

    def test_zero_limit_never_expires(self, srv, worker_cron):
        """``limit_time_worker_cron = 0`` disables the age check entirely."""
        worker_cron.alive_time = time.monotonic() - 99_999
        with (
            patch("odoo.service._worker.config", {"limit_time_worker_cron": 0}),
            patch.object(srv.Worker, "check_limits"),
        ):
            worker_cron.check_limits()
        assert worker_cron.alive is True

    def test_negative_limit_never_expires(self, srv, worker_cron):
        """Negative values (sentinel for 'inherit from limit_time_real') disable the check."""
        worker_cron.alive_time = time.monotonic() - 99_999
        with (
            patch("odoo.service._worker.config", {"limit_time_worker_cron": -1}),
            patch.object(srv.Worker, "check_limits"),
        ):
            worker_cron.check_limits()
        assert worker_cron.alive is True


# ---------------------------------------------------------------------------
# Worker.check_limits() — base class
# ---------------------------------------------------------------------------

# Shared config / resource stubs used by every check_limits test.
_WORKER_CONFIG = {"limit_memory_soft": 0, "limit_time_cpu": 60}
_RESOURCE_ATTRS = {"ru_utime": 0.0, "ru_stime": 0.0}


def _resource_stub():
    """A ``resource`` module stand-in with the readings ``check_limits`` takes."""
    mock_resource = MagicMock()
    mock_resource.getrusage.return_value.ru_utime = 0.0
    mock_resource.getrusage.return_value.ru_stime = 0.0
    mock_resource.getrlimit.return_value = (0, 9999)
    mock_resource.RLIMIT_CPU = 0
    mock_resource.RUSAGE_SELF = 0
    return mock_resource


@contextlib.contextmanager
def worker_check_limits_env(memory_bytes=0, config_override=None):
    """Stub every syscall ``Worker.check_limits`` reaches for; yield the mocks.

    Yields a namespace with ``.resource`` and ``.memory_info`` so a test can
    both drive the readings and assert on whether they were consulted at all
    (``limit_memory_soft = 0`` must skip the ``/proc`` read entirely).

    A context manager, NOT a list of patches.  The list form was entered as
    ``with patches[0], patches[1], patches[2]:`` at nine call sites, so a fourth
    patch appended to the helper applied at NONE of them — silently, with every
    test still green and the new syscall left live.  Verified: appending an
    ``os.getppid`` patch that must set ``alive = False`` left all twelve tests
    passing, while the same test with ``patches[3]`` spelled out fails.  A
    context manager cannot be under-entered.

    ``Worker.check_limits`` lives in ``odoo.service._worker``, so its ``config``
    and ``resource`` references resolve against that namespace.  The RSS read
    goes through ``over_memory_soft_limit``, which looks up ``memory_info`` in
    its DEFINING module ``_helpers`` — so that is where the stub belongs, and
    patching it there lets the real soft-limit threshold logic run.
    """
    cfg = {**_WORKER_CONFIG, **(config_override or {})}
    mock_resource = _resource_stub()
    mock_memory_info = MagicMock(return_value=memory_bytes)
    with (
        patch("odoo.service._worker.config", cfg),
        patch("odoo.service._helpers.memory_info", mock_memory_info),
        patch("odoo.service._worker.resource", mock_resource),
    ):
        yield SimpleNamespace(resource=mock_resource, memory_info=mock_memory_info)


@pytest.fixture
def bare_worker(srv):
    """Worker (base class) with minimal state, bypassing start().

    In a real forked worker, ``ppid`` is set to ``os.getpid()`` *before*
    the fork, so it stores the *parent's* PID.  Inside the child process
    ``os.getppid()`` returns that same parent PID, so the check passes.
    We replicate that by setting ``ppid = os.getppid()`` in the test.
    """
    w = object.__new__(srv.Worker)
    w.ppid = os.getppid()  # mirrors child-process state: ppid == actual parent
    w.pid = os.getpid()
    w.alive = True
    w.request_count = 0
    w.request_max = 100
    w.logger = MagicMock()
    # ``_process_handle`` is normally set in ``Worker.start()`` (cached
    # ``psutil.Process(self.pid)``); bypassing start() in tests requires a
    # stub. ``memory_info`` is mocked anyway so the value is not consulted.
    w._process_handle = MagicMock()
    return w


class TestWorkerCheckLimits:
    """``Worker.check_limits()``: parent PID, request cap, memory soft limit, CPU rlimit."""

    def test_healthy_worker_stays_alive(self, bare_worker):
        with worker_check_limits_env():
            bare_worker.check_limits()
        assert bare_worker.alive is True

    def test_parent_changed_sets_alive_false(self, bare_worker):
        bare_worker.ppid = 99999  # deliberate mismatch with os.getppid()
        with worker_check_limits_env():
            bare_worker.check_limits()
        assert bare_worker.alive is False

    def test_request_max_reached_sets_alive_false(self, bare_worker):
        bare_worker.request_count = 100
        bare_worker.request_max = 100
        with worker_check_limits_env():
            bare_worker.check_limits()
        assert bare_worker.alive is False

    def test_request_max_zero_means_unlimited(self, bare_worker):
        """``limit_request=0`` (gunicorn's "unlimited") must NOT kill the worker.

        Without the guard, ``request_count(0) >= request_max(0)`` is True on the
        very first check, so the worker dies before serving anything and the
        master respawns it in a fork loop.
        """
        bare_worker.request_count = 0
        bare_worker.request_max = 0
        with worker_check_limits_env():
            bare_worker.check_limits()
        assert bare_worker.alive is True

    def test_memory_soft_exceeded_sets_alive_false(self, bare_worker):
        with worker_check_limits_env(
            memory_bytes=500,
            config_override={"limit_memory_soft": 100},
        ):
            bare_worker.check_limits()
        assert bare_worker.alive is False

    def test_cpu_rlimit_set_to_usage_plus_limit(self, bare_worker):
        """RLIMIT_CPU soft = current_cpu_time + limit_time_cpu."""
        with worker_check_limits_env(config_override={"limit_time_cpu": 30}) as env:
            env.resource.getrusage.return_value.ru_utime = 5.0
            env.resource.getrusage.return_value.ru_stime = 3.0  # total = 8s
            env.resource.getrlimit.return_value = (0, 9999)
            bare_worker.check_limits()
        # int(8.0 + 30) = 38
        env.resource.setrlimit.assert_called_once_with(0, (38, 9999))

    def test_cpu_rlimit_not_armed_when_disabled(self, bare_worker):
        """limit_time_cpu=0 must NOT arm RLIMIT_CPU.

        Arming it to ``int(cpu_already_consumed + 0)`` sets the soft limit at
        or below the CPU the worker has already used, so the kernel raises
        SIGXCPU immediately and the worker dies in a fork loop.  0 means
        "disabled", consistent with every other limit in this module.
        """
        with worker_check_limits_env(config_override={"limit_time_cpu": 0}) as env:
            env.resource.getrusage.return_value.ru_utime = 8.0
            env.resource.getrusage.return_value.ru_stime = 0.0
            bare_worker.check_limits()
        env.resource.setrlimit.assert_not_called()
        assert bare_worker.alive is True

    def test_rss_not_read_when_soft_limit_disabled(self, bare_worker):
        """The RSS ``/proc`` read is skipped entirely when ``limit_memory_soft``
        is 0 (disabled) — it was previously paid on every cycle for nothing."""
        with worker_check_limits_env(config_override={"limit_memory_soft": 0}) as env:
            bare_worker.check_limits()
        env.memory_info.assert_not_called()
        assert bare_worker.alive is True

    def test_rss_read_when_soft_limit_enabled(self, bare_worker):
        """With the soft limit set, RSS is read exactly once and a value under
        the limit keeps the worker alive."""
        with worker_check_limits_env(
            memory_bytes=50, config_override={"limit_memory_soft": 100}
        ) as env:
            bare_worker.check_limits()
        env.memory_info.assert_called_once()
        assert bare_worker.alive is True


# ---------------------------------------------------------------------------
# Worker.run() — fault propagation
# ---------------------------------------------------------------------------


class TestWorkerRunFaultExit:
    """``Worker.run()``: a fault in the daemon ``_runloop`` must surface as
    ``SystemExit(1)`` on the main thread so ``worker_spawn`` records a non-zero
    exit — not be mislabeled as a clean exit.

    Regression: ``raise SystemExit`` inside the daemon ``_runloop`` is inert
    (it is delivered to ``threading.excepthook``, whose default ignores
    SystemExit, and never reaches the joiner), so a crashed worker used to log
    "Exiting cleanly" and exit 0.
    """

    def _make_worker(self, srv):
        w = object.__new__(srv.Worker)
        w.alive = True
        w.pid = os.getpid()
        w.request_count = 0
        w.watchdog_pipe = (0, 0)
        w.multi = MagicMock()
        w.logger = MagicMock()
        w.start = MagicMock()
        w.stop = MagicMock()
        w.check_limits = MagicMock()
        w.sleep = MagicMock()
        return w

    def test_work_fault_propagates_as_systemexit_1(self, srv):
        w = self._make_worker(srv)
        w.process_work = MagicMock(side_effect=ValueError("boom"))
        with pytest.raises(SystemExit) as exc_info:
            w.run()
        assert exc_info.value.code == 1
        w.stop.assert_called_once()  # finally: cleanup still runs
        logged = " ".join(str(c) for c in w.logger.info.call_args_list)
        assert "Exiting cleanly" not in logged, "crash mislabeled as clean exit"

    def test_clean_exit_returns_none_and_logs(self, srv):
        w = self._make_worker(srv)

        def stop_loop():
            w.alive = False  # next ``while self.alive`` ends the loop cleanly

        w.process_work = MagicMock(side_effect=stop_loop)
        result = w.run()
        assert result is None
        logged = " ".join(str(c) for c in w.logger.info.call_args_list)
        assert "Exiting cleanly" in logged
        w.stop.assert_called_once()


# ---------------------------------------------------------------------------
# CommonServer.on_stop() / stop()
# ---------------------------------------------------------------------------


class TestCommonServerCallbacks:
    """``on_stop()`` registers cleanup callbacks; ``stop()`` calls them all.

    Callbacks live on the module-level ``_ON_STOP_FUNCS`` list. The previous
    ``CommonServer._on_stop_funcs`` class alias was removed — reassignment
    would silently desync it from the module list while ``on_stop`` kept
    appending to the original.
    """

    @pytest.fixture(autouse=True)
    def _restore_callbacks(self, srv):
        """Restore the module-level callback list after each test."""
        original = list(srv._ON_STOP_FUNCS)
        yield
        srv._ON_STOP_FUNCS[:] = original

    def test_on_stop_appends_callback(self, srv):
        cb = MagicMock()
        srv.CommonServer.on_stop(cb)
        assert cb in srv._ON_STOP_FUNCS

    def test_stop_calls_all_registered_callbacks(self, srv):
        server = object.__new__(srv.CommonServer)
        server.logger = MagicMock()
        cb1, cb2 = MagicMock(), MagicMock()
        srv._ON_STOP_FUNCS.extend([cb1, cb2])
        server.stop()
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_stop_continues_after_callback_exception(self, srv):
        """An exception in one callback must not prevent subsequent callbacks."""
        server = object.__new__(srv.CommonServer)
        server.logger = MagicMock()
        cb1 = MagicMock(side_effect=RuntimeError("boom"))
        cb1.__name__ = "cb1"  # stop() logs func.__name__; MagicMock needs it set
        cb2 = MagicMock()
        cb2.__name__ = "cb2"
        srv._ON_STOP_FUNCS.extend([cb1, cb2])
        server.stop()  # must not raise
        cb2.assert_called_once()

    def test_stop_survives_partial_hook_without_name(self, srv):
        """A raising ``functools.partial`` hook (no ``__name__``) must not crash stop().

        Hooks are arbitrary callables; ``functools.partial`` is a legal one and
        has no ``__name__``.  Before the fix, ``stop()``'s error handler did a
        bare ``func.__name__`` which raised ``AttributeError`` *inside* the
        ``except`` — masking the real cleanup failure and aborting every
        remaining hook.  The handler now falls back to ``repr(func)``.
        """
        import functools

        server = object.__new__(srv.CommonServer)
        server.logger = MagicMock()

        def _boom(_tag):
            raise RuntimeError("cleanup failed")

        raising_partial = functools.partial(_boom, "x")  # no __name__
        assert not hasattr(raising_partial, "__name__")
        later = MagicMock()
        later.__name__ = "later"
        srv._ON_STOP_FUNCS.extend([raising_partial, later])

        server.stop()  # must NOT raise AttributeError

        # The partial's failure was logged (not propagated) and the next hook ran.
        server.logger.warning.assert_called_once()
        later.assert_called_once()


# ---------------------------------------------------------------------------
# cron_database_list()
# ---------------------------------------------------------------------------


class TestPreforkProcessZombie:
    """``process_zombie()``: reaps dead workers; treats exit code 3 as critical."""

    def test_normal_exit_pops_worker(self, prefork_server):
        prefork_server.worker_pop = MagicMock()
        # First call returns a dead pid; second returns (0,0) to break the loop.
        with patch("os.waitpid", side_effect=[(1234, 0), (0, 0)]):
            prefork_server.process_zombie()
        prefork_server.worker_pop.assert_called_once_with(1234)

    def test_exit_code_3_does_not_raise(self, prefork_server):
        """Fork explicitly removed the historical exit-code-3 abort branch.

        The ``status >> 8 == 3`` check was an ad-hoc sentinel inherited
        from a 2014 commit; no path in the fork produces exit code 3, and
        the comparison was incorrect for signal-killed workers (``status
        >> 8`` is undefined when ``WIFSIGNALED``).  Confirm that
        ``process_zombie`` now treats exit code 3 like any other reaped
        worker — pops it from bookkeeping and continues.
        """
        prefork_server.worker_pop = MagicMock()
        # First call returns the dead pid with exit code 3; second returns
        # (0, 0) to break out of the loop (the function's own sentinel).
        with patch("os.waitpid", side_effect=[(5678, 3 << 8), (0, 0)]):
            prefork_server.process_zombie()
        prefork_server.worker_pop.assert_called_once_with(5678)

    def test_echild_breaks_loop_cleanly(self, prefork_server):
        prefork_server.worker_pop = MagicMock()
        with patch("os.waitpid", side_effect=OSError(errno.ECHILD, "no children")):
            prefork_server.process_zombie()  # must not raise
        prefork_server.worker_pop.assert_not_called()

    def test_other_oserror_propagates(self, prefork_server):
        with patch("os.waitpid", side_effect=OSError(errno.EINTR, "interrupted")):
            with pytest.raises(OSError):
                prefork_server.process_zombie()


# ---------------------------------------------------------------------------
# PreforkServer.long_polling_popen reconciliation
# ---------------------------------------------------------------------------


class TestLongPollingPopenReconciliation:
    """The master reaps the evented child via ``waitpid(-1)``/psutil, behind
    subprocess's back, so the ``Popen`` handle must be reconciled or its
    ``__del__`` warns "still running" and parks it on ``subprocess._active``."""

    def test_reconcile_sets_returncode_and_clears_ref(self, prefork_server):
        popen = MagicMock()
        popen.returncode = None
        prefork_server.long_polling_popen = popen
        prefork_server._reconcile_long_polling_popen(0)
        assert popen.returncode == 0
        assert prefork_server.long_polling_popen is None

    def test_reconcile_uses_sigkill_sentinel_when_code_unknown(self, prefork_server):
        popen = MagicMock()
        popen.returncode = None
        prefork_server.long_polling_popen = popen
        prefork_server._reconcile_long_polling_popen(None)
        assert popen.returncode == -signal.SIGKILL

    def test_reconcile_is_noop_without_a_handle(self, prefork_server):
        prefork_server.long_polling_popen = None
        prefork_server._reconcile_long_polling_popen(0)  # must not raise

    def test_note_worker_exit_reconciles_the_handle(self, prefork_server):
        popen = MagicMock()
        popen.returncode = None
        prefork_server.long_polling_pid = 9999
        prefork_server.long_polling_popen = popen
        prefork_server.long_polling_spawn_time = time.monotonic()
        prefork_server._note_worker_exit(9999, 0)  # clean recycle, exit 0
        assert popen.returncode == 0
        assert prefork_server.long_polling_popen is None

    def test_real_popen_no_resourcewarning_after_reconcile(self, prefork_server):
        """Behavioral: a real reaped Popen must not warn once reconciled.

        The warning must be RECORDED and asserted on, never turned into an
        exception with ``simplefilter("error")``.  ``ResourceWarning`` is emitted
        from ``Popen.__del__``, and CPython swallows anything raised inside a
        deallocator — it prints "Exception ignored in:" to stderr and carries on.
        Written that way the test passed even with ``_reconcile_long_polling_popen``
        stubbed out to do nothing at all, i.e. it asserted nothing.  This is the
        same shape ``test_db.py``'s ``TestDumpStreamingClosesItsPipes`` already uses.
        """
        import gc
        import subprocess
        import sys
        import warnings

        popen = subprocess.Popen([sys.executable, "-c", "pass"])
        _pid, status = os.waitpid(popen.pid, 0)  # reap behind subprocess's back
        prefork_server.long_polling_popen = popen
        prefork_server._reconcile_long_polling_popen(os.waitstatus_to_exitcode(status))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            del popen
            gc.collect()
        leaked = [w for w in caught if issubclass(w.category, ResourceWarning)]
        assert not leaked, (
            f"the reaped Popen still warns, so it was never reconciled: "
            f"{[str(w.message) for w in leaked]}"
        )


class TestPreforkRespawnBackoff:
    """``_note_worker_exit`` / ``process_spawn``: throttle respawns of workers
    that die young so a boot-crash loop can't fork-storm the master."""

    @staticmethod
    def _worker(prefork_server, pid, *, age_s):
        w = MagicMock()
        w.__class__.__name__ = "WorkerHTTP"
        w.spawn_time = time.monotonic() - age_s
        prefork_server.workers[pid] = w
        return w

    def test_young_crash_arms_exponential_backoff(self, prefork_server):
        self._worker(prefork_server, 1234, age_s=0.0)
        before = time.monotonic()
        prefork_server._note_worker_exit(1234, 1 << 8)  # exited, code 1
        assert prefork_server._consecutive_fast_deaths == 1
        assert prefork_server._respawn_not_before > before
        # a second consecutive young crash grows the backoff
        self._worker(prefork_server, 1235, age_s=0.0)
        prefork_server._note_worker_exit(1235, 1 << 8)
        assert prefork_server._consecutive_fast_deaths == 2

    def test_backoff_capped(self, prefork_server):
        prefork_server._consecutive_fast_deaths = 20  # 2**20 >> cap
        self._worker(prefork_server, 1, age_s=0.0)
        t = time.monotonic()
        prefork_server._note_worker_exit(1, 1 << 8)
        assert (
            prefork_server._respawn_not_before - t
            <= _prefork.WORKER_RESPAWN_BACKOFF_CAP_S + 0.5
        )

    def test_healthy_exit_clears_throttle(self, prefork_server):
        prefork_server._consecutive_fast_deaths = 3
        prefork_server._respawn_not_before = time.monotonic() + 100
        self._worker(
            prefork_server, 42, age_s=_prefork.WORKER_MIN_HEALTHY_LIFETIME_S + 5
        )
        prefork_server._note_worker_exit(42, 1 << 8)  # crashed, but lived long
        assert prefork_server._consecutive_fast_deaths == 0
        assert prefork_server._respawn_not_before == 0.0

    def test_clean_young_exit_neither_arms_nor_clears(self, prefork_server):
        prefork_server._consecutive_fast_deaths = 2
        prefork_server._respawn_not_before = 555.0
        self._worker(prefork_server, 7, age_s=1.0)
        prefork_server._note_worker_exit(7, 0)  # exit 0, recycle
        assert prefork_server._consecutive_fast_deaths == 2
        assert prefork_server._respawn_not_before == 555.0

    def test_external_sigkill_young_worker_arms_backoff(self, prefork_server):
        # A SIGKILL reaching _note_worker_exit with the worker STILL registered
        # is external — the cgroup OOM-killer and ``kill -9`` both use signal 9.
        # (The master's own watchdog SIGKILL worker_pop's the worker BEFORE it is
        # reaped, so it never gets here — covered by test_unknown_pid_ignored.)
        # An OOM crash-on-boot storm under a too-tight MemoryMax must arm the
        # throttle, exactly like a segfault.
        prefork_server._consecutive_fast_deaths = 0
        before = time.monotonic()
        self._worker(prefork_server, 8, age_s=1.0)
        prefork_server._note_worker_exit(8, signal.SIGKILL)
        assert prefork_server._consecutive_fast_deaths == 1
        assert prefork_server._respawn_not_before > before

    def test_sigterm_killed_young_worker_not_counted(self, prefork_server):
        # SIGTERM (final stop): master-initiated, excluded like SIGKILL.
        prefork_server._consecutive_fast_deaths = 0
        self._worker(prefork_server, 81, age_s=1.0)
        prefork_server._note_worker_exit(81, signal.SIGTERM)
        assert prefork_server._consecutive_fast_deaths == 0

    def test_segfault_young_worker_arms_backoff(self, prefork_server):
        # A native crash (SIGSEGV/SIGABRT/OOM-kill) is a boot crash, not a
        # master-initiated kill — it MUST arm the throttle, or a crash-on-boot
        # C-extension storm dying by signal would refill its slot undetected.
        prefork_server._consecutive_fast_deaths = 0
        before = time.monotonic()
        self._worker(prefork_server, 82, age_s=0.0)
        prefork_server._note_worker_exit(82, signal.SIGSEGV)
        assert prefork_server._consecutive_fast_deaths == 1
        assert prefork_server._respawn_not_before > before

    def test_unknown_pid_ignored(self, prefork_server):
        prefork_server._consecutive_fast_deaths = 1
        prefork_server._note_worker_exit(99999, 1 << 8)  # not in self.workers
        assert prefork_server._consecutive_fast_deaths == 1

    def test_long_polling_young_crash_arms_backoff(self, prefork_server):
        """The evented subprocess has no other respawn backoff: a young crash
        (e.g. gevent_port already bound -> exit 1) must arm the shared throttle
        so ``process_spawn`` stops exec-storming replacements."""
        prefork_server.long_polling_pid = 4321
        prefork_server.long_polling_spawn_time = time.monotonic() - 1.0
        before = time.monotonic()
        prefork_server._note_worker_exit(4321, 1 << 8)  # exited, code 1
        assert prefork_server._consecutive_fast_deaths == 1
        assert prefork_server._respawn_not_before > before

    def test_long_polling_clean_young_exit_neither_arms_nor_clears(
        self, prefork_server
    ):
        """A clean exit 0 (EventServer memory-limit self-recycle) is not a
        crash — but it must not reset a genuine worker crash streak either."""
        prefork_server._consecutive_fast_deaths = 2
        prefork_server.long_polling_pid = 4321
        prefork_server.long_polling_spawn_time = time.monotonic() - 1.0
        prefork_server._note_worker_exit(4321, 0)  # exit 0
        assert prefork_server._consecutive_fast_deaths == 2

    def test_long_polling_healthy_lifetime_clears_throttle(self, prefork_server):
        prefork_server._consecutive_fast_deaths = 3
        prefork_server._respawn_not_before = time.monotonic() + 100
        prefork_server.long_polling_pid = 4321
        prefork_server.long_polling_spawn_time = (
            time.monotonic() - _prefork.WORKER_MIN_HEALTHY_LIFETIME_S - 5
        )
        prefork_server._note_worker_exit(4321, 1 << 8)
        assert prefork_server._consecutive_fast_deaths == 0
        assert prefork_server._respawn_not_before == 0.0

    def test_process_spawn_skips_during_backoff(self, prefork_server):
        prefork_server._respawn_not_before = time.monotonic() + 100
        prefork_server.worker_spawn = MagicMock()
        prefork_server.long_polling_spawn = MagicMock()
        prefork_server.process_spawn()
        prefork_server.worker_spawn.assert_not_called()
        prefork_server.long_polling_spawn.assert_not_called()

    def test_fork_oserror_returns_none_and_releases_pipes(
        self, prefork_server, monkeypatch
    ):
        """A transient ``os.fork()`` failure (EAGAIN/ENOMEM) must not propagate
        to the master's main loop (which would stop the supervisor).  It returns
        None and releases the pipe fds the worker allocated."""
        prefork_server.generation = 0
        fake_worker = MagicMock()
        klass = MagicMock(return_value=fake_worker)
        monkeypatch.setattr(os, "fork", MagicMock(side_effect=OSError("EAGAIN")))
        before = time.monotonic()
        result = prefork_server.worker_spawn(klass, {})
        assert result is None
        fake_worker.close.assert_called_once()
        assert prefork_server.workers == {}
        # A pre-fork failure creates no child to reap, so it must arm the respawn
        # throttle itself — else process_spawn re-attempts (and re-logs) every
        # ~4s beat while the fd/memory pressure that caused it is still on.
        assert prefork_server._consecutive_fast_deaths == 1
        assert prefork_server._respawn_not_before > before

    def test_repeated_fork_failures_grow_the_backoff(self, prefork_server, monkeypatch):
        """Consecutive pre-fork failures widen the hold, same as young crashes."""
        prefork_server.generation = 0
        klass = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(os, "fork", MagicMock(side_effect=OSError("EMFILE")))
        prefork_server.worker_spawn(klass, {})
        first_hold = prefork_server._respawn_not_before - time.monotonic()
        prefork_server.worker_spawn(klass, {})
        second_hold = prefork_server._respawn_not_before - time.monotonic()
        assert prefork_server._consecutive_fast_deaths == 2
        assert second_hold > first_hold

    def test_fork_failure_hold_is_capped(self, prefork_server, monkeypatch):
        prefork_server.generation = 0
        prefork_server._consecutive_fast_deaths = 20  # 2**20 >> cap
        klass = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(os, "fork", MagicMock(side_effect=OSError("EMFILE")))
        t = time.monotonic()
        prefork_server.worker_spawn(klass, {})
        assert (
            prefork_server._respawn_not_before - t
            <= _prefork.WORKER_RESPAWN_BACKOFF_CAP_S + 0.5
        )

    def test_long_polling_spawn_oserror_does_not_propagate(
        self, prefork_server, monkeypatch
    ):
        """A transient ``subprocess.Popen`` failure in ``long_polling_spawn``
        must NOT propagate to the master loop (which would stop the supervisor).
        It swallows the OSError and leaves ``long_polling_pid`` unset so the next
        ``process_spawn`` cycle retries — mirroring the ``os.fork()`` guard in
        ``worker_spawn``."""
        prefork_server.long_polling_pid = None
        monkeypatch.setattr(
            _prefork.subprocess,
            "Popen",
            MagicMock(side_effect=OSError("EAGAIN")),
        )
        before = time.monotonic()
        # Must not raise.
        prefork_server.long_polling_spawn()
        assert prefork_server.long_polling_pid is None
        # Same throttle as ``worker_spawn``: without it the master exec-storms
        # the evented child every cycle under resource pressure.
        assert prefork_server._consecutive_fast_deaths == 1
        assert prefork_server._respawn_not_before > before


class TestPreforkGracefulStopEscalation:
    """``stop_workers_gracefully``: force-SIGKILL survivors past the deadline so a
    worker that ignores SIGINT with no watchdog can't hang shutdown/reload."""

    def test_escalates_to_sigkill_after_deadline(self, prefork_server, monkeypatch):
        prefork_server.pid = os.getpid()  # -> is_main_server, waitpid reaping path
        prefork_server.long_polling_pid = None
        wedged = MagicMock()
        wedged.watchdog_timeout = None  # no watchdog: process_timeout never fires
        prefork_server.workers = {321: wedged}
        prefork_server.worker_kill = MagicMock()  # swallow the initial SIGINT
        prefork_server.process_signals = MagicMock()
        prefork_server.process_timeout = MagicMock()
        prefork_server.sleep = MagicMock()

        killed: list[tuple[int, int]] = []

        def fake_zombie():
            # The real process_zombie reaps the SIGKILLed child and pops it;
            # simulate that so the loop can drain once escalation has fired.
            if killed:
                prefork_server.workers.pop(321, None)

        prefork_server.process_zombie = MagicMock(side_effect=fake_zombie)
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
        # deadline immediately in the past -> escalate on the first tick
        monkeypatch.setattr(_prefork, "GRACEFUL_STOP_TIMEOUT_S", 0.0)

        prefork_server.stop_workers_gracefully()

        assert (321, signal.SIGKILL) in killed
        assert not prefork_server.workers  # loop drained, no infinite spin

    def test_stop_timeout_env_override(self, monkeypatch):
        """``ODOO_GRACEFUL_STOP_TIMEOUT`` raises the SIGKILL deadline for
        deployments with long ``limit_time_real``; floored at 1s so "0" cannot
        disable the escalation and reintroduce the infinite drain loop."""
        logger = MagicMock()
        monkeypatch.setenv("ODOO_GRACEFUL_STOP_TIMEOUT", "300")
        assert _prefork._graceful_stop_timeout(logger) == 300.0
        monkeypatch.setenv("ODOO_GRACEFUL_STOP_TIMEOUT", "0")
        assert _prefork._graceful_stop_timeout(logger) == 1.0
        monkeypatch.setenv("ODOO_GRACEFUL_STOP_TIMEOUT", "garbage")
        assert (
            _prefork._graceful_stop_timeout(logger) == _prefork.GRACEFUL_STOP_TIMEOUT_S
        )
        monkeypatch.delenv("ODOO_GRACEFUL_STOP_TIMEOUT")
        assert (
            _prefork._graceful_stop_timeout(logger) == _prefork.GRACEFUL_STOP_TIMEOUT_S
        )


# ---------------------------------------------------------------------------
# PreforkServer.process_timeout()
# ---------------------------------------------------------------------------


class TestPreforkInitTimeout:
    """``__init__``: ``limit_time_real``/``limit_time_real_cron`` -> watchdog timeouts."""

    @staticmethod
    def _make(srv, **overrides):
        cfg = {
            "http_interface": "",
            "http_port": 8069,
            "workers": 2,
            "limit_time_real": 120,
            "limit_request": 100,
            "limit_time_real_cron": -1,
            **overrides,
        }
        # __init__ reads ``config`` in both _prefork (PreforkServer) and
        # _base_server (CommonServer); patch both. No socket is opened in
        # __init__ (that happens in start()), so this is safe.
        with (
            patch.object(_prefork, "config", cfg),
            patch.object(_base_server, "config", cfg),
        ):
            return srv.PreforkServer(MagicMock())

    def test_limit_time_real_zero_disables_http_watchdog(self, srv):
        """0 must become None so process_timeout never kills a fresh worker."""
        s = self._make(srv, limit_time_real=0)
        assert s.timeout is None
        # cron inherits via the -1 default -> also disabled, not 0
        assert s.cron_timeout is None

    def test_default_limit_time_real_kept(self, srv):
        s = self._make(srv, limit_time_real=120)
        assert s.timeout == 120
        assert s.cron_timeout == 120  # -1 inherits limit_time_real

    def test_any_negative_cron_limit_inherits_limit_time_real(self, srv):
        """A negative value other than -1 must NOT become a literal timeout.

        ``cron_timeout = -5`` would make ``process_timeout`` SIGKILL every cron
        worker on its first beat — and a master-watchdog kill pops the worker
        before the reap, bypassing the fast-death throttle (undamped fork loop).
        """
        s = self._make(srv, limit_time_real_cron=-5)
        assert s.cron_timeout == 120  # inherits, like the documented -1

    def test_negative_cron_limit_with_no_real_limit_disables_watchdog(self, srv):
        s = self._make(srv, limit_time_real=0, limit_time_real_cron=-5)
        assert s.cron_timeout is None

    def test_positive_cron_limit_kept(self, srv):
        s = self._make(srv, limit_time_real_cron=30)
        assert s.cron_timeout == 30


# ---------------------------------------------------------------------------
# PreforkServer._stop_long_polling()
# ---------------------------------------------------------------------------


class TestStopLongPolling:
    """``_stop_long_polling()``: SIGTERM first, bounded wait, SIGKILL fallback."""

    def test_no_pid_is_noop(self, prefork_server):
        with patch.object(_prefork.os, "kill") as kill:
            prefork_server._stop_long_polling()
        kill.assert_not_called()

    def test_graceful_sigterm_no_escalation(self, prefork_server):
        prefork_server.long_polling_pid = 4321
        proc = MagicMock()
        with (
            patch.object(_prefork.psutil, "Process", return_value=proc),
            patch.object(_prefork.os, "kill") as kill,
        ):
            prefork_server._stop_long_polling()
        kill.assert_called_once_with(4321, signal.SIGTERM)
        proc.wait.assert_called_once()
        assert prefork_server.long_polling_pid is None

    def test_escalates_to_sigkill_on_timeout(self, prefork_server):
        prefork_server.long_polling_pid = 4321
        proc = MagicMock()
        # First wait (post-SIGTERM) times out; second (post-SIGKILL) reaps.
        proc.wait.side_effect = [psutil.TimeoutExpired(5), None]
        with (
            patch.object(_prefork.psutil, "Process", return_value=proc),
            patch.object(_prefork.os, "kill") as kill,
        ):
            prefork_server._stop_long_polling()
        assert [c.args for c in kill.call_args_list] == [
            (4321, signal.SIGTERM),
            (4321, signal.SIGKILL),
        ]
        assert prefork_server.long_polling_pid is None

    def test_already_dead_child(self, prefork_server):
        prefork_server.long_polling_pid = 4321
        with (
            patch.object(
                _prefork.psutil, "Process", side_effect=psutil.NoSuchProcess(4321)
            ),
            patch.object(_prefork.os, "kill") as kill,
        ):
            prefork_server._stop_long_polling()
        kill.assert_not_called()
        assert prefork_server.long_polling_pid is None

    def test_esrch_on_sigterm_still_waits_for_reap(self, prefork_server):
        """A racing exit between Process() and kill() must not raise."""
        prefork_server.long_polling_pid = 4321
        proc = MagicMock()
        with (
            patch.object(_prefork.psutil, "Process", return_value=proc),
            patch.object(_prefork.os, "kill", side_effect=ProcessLookupError),
        ):
            prefork_server._stop_long_polling()
        proc.wait.assert_called_once()


# ---------------------------------------------------------------------------
# PreforkServer.process_timeout()
# ---------------------------------------------------------------------------


class TestPreforkProcessTimeout:
    """``process_timeout()``: SIGKILL workers that exceed their watchdog timeout."""

    def test_kills_timed_out_worker(self, prefork_server):
        stale = MagicMock()
        stale.watchdog_timeout = 30
        stale.watchdog_time = time.monotonic() - 60  # well past deadline
        prefork_server.workers = {9999: stale}
        prefork_server.worker_kill = MagicMock()
        prefork_server.process_timeout()
        prefork_server.worker_kill.assert_called_once_with(9999, signal.SIGKILL)

    def test_leaves_healthy_worker_alone(self, prefork_server):
        healthy = MagicMock()
        healthy.watchdog_timeout = 30
        healthy.watchdog_time = time.monotonic()  # just pinged
        prefork_server.workers = {1111: healthy}
        prefork_server.worker_kill = MagicMock()
        prefork_server.process_timeout()
        prefork_server.worker_kill.assert_not_called()

    def test_none_watchdog_timeout_never_kills(self, prefork_server):
        """``watchdog_timeout=None`` disables the watchdog for that worker."""
        w = MagicMock()
        w.watchdog_timeout = None
        w.watchdog_time = time.monotonic() - 99999
        prefork_server.workers = {2222: w}
        prefork_server.worker_kill = MagicMock()
        prefork_server.process_timeout()
        prefork_server.worker_kill.assert_not_called()


# ---------------------------------------------------------------------------
# PreforkServer.worker_kill()
# ---------------------------------------------------------------------------


class TestPreforkWorkerKill:
    """``worker_kill()``: sends signals; handles ESRCH (process already gone)."""

    def test_sends_signal(self, prefork_server):
        prefork_server.worker_pop = MagicMock()
        with patch("os.kill") as mock_kill:
            prefork_server.worker_kill(1234, signal.SIGTERM)
        mock_kill.assert_called_once_with(1234, signal.SIGTERM)

    def test_sigkill_also_pops_worker(self, prefork_server):
        """SIGKILL is terminal — pop the worker immediately after sending it."""
        prefork_server.worker_pop = MagicMock()
        with patch("os.kill"):
            prefork_server.worker_kill(1234, signal.SIGKILL)
        prefork_server.worker_pop.assert_called_once_with(1234)

    def test_sigterm_does_not_pop_worker(self, prefork_server):
        prefork_server.worker_pop = MagicMock()
        with patch("os.kill"):
            prefork_server.worker_kill(1234, signal.SIGTERM)
        prefork_server.worker_pop.assert_not_called()

    def test_esrch_cleans_up_stale_entry(self, prefork_server):
        """Process already gone (ESRCH) must not raise — clean up the registry."""
        prefork_server.worker_pop = MagicMock()
        with patch("os.kill", side_effect=OSError(errno.ESRCH, "no such process")):
            prefork_server.worker_kill(1234, signal.SIGTERM)
        prefork_server.worker_pop.assert_called_once_with(1234)


# ---------------------------------------------------------------------------
# CommonRequestHandler.log_error() / log_request()
# ---------------------------------------------------------------------------


@pytest.fixture
def log_handler(srv, monkeypatch):
    """Minimal CommonRequestHandler for log_request / log_error tests."""
    h = object.__new__(srv.CommonRequestHandler)
    h.path = "/web/test"
    h.command = "GET"
    h.request_version = "HTTP/1.1"
    h.requestline = "GET /web/test HTTP/1.1"
    h.log = MagicMock()
    stamp_rpc_model_method(monkeypatch)
    return h


class TestCommonRequestHandlerLogError:
    """``log_error()``: timeout errors are downgraded; others delegate to super."""

    def test_timeout_logs_at_debug(self, log_handler):
        with patch("odoo.service.wsgi._logger") as mock_logger:
            log_handler.log_error("Request timed out: %r", "socket")
        mock_logger.debug.assert_called_once()

    def test_other_error_calls_super(self, log_handler):
        with (
            patch("odoo.service.wsgi._logger"),
            patch.object(
                werkzeug.serving.WSGIRequestHandler, "log_error"
            ) as mock_super,
        ):
            log_handler.log_error("Some other error: %s", "detail")
        mock_super.assert_called_once()


class TestCommonRequestHandlerSendHeader:
    """``send_header()``: dedup Date/Server, never crash on a malformed value."""

    @pytest.fixture
    def handler(self, srv):
        h = object.__new__(srv.CommonRequestHandler)
        h._sent_date_header = None
        h._sent_server_header = None
        return h

    def _send(self, handler, pairs):
        sent: list[tuple[str, str]] = []
        with patch.object(
            werkzeug.serving.WSGIRequestHandler,
            "send_header",
            lambda self, k, v: sent.append((k, v)),
        ):
            for k, v in pairs:
                handler.send_header(k, v)
        return sent

    def test_identical_date_sent_once(self, handler):
        d = "Thu, 01 Jan 2026 00:00:00 GMT"
        sent = self._send(handler, [("Date", d), ("Date", d)])
        assert sent == [("Date", d)]

    def test_same_instant_different_format_sent_once(self, handler):
        # GMT (aware) vs -0000 (parses NAIVE) — the historical TypeError trigger.
        sent = self._send(
            handler,
            [
                ("Date", "Thu, 01 Jan 2026 00:00:00 GMT"),
                ("Date", "Thu, 01 Jan 2026 00:00:00 -0000"),
            ],
        )
        assert sent == [("Date", "Thu, 01 Jan 2026 00:00:00 GMT")]

    def test_naive_date_five_seconds_apart_does_not_crash(self, handler):
        with patch("odoo.service.wsgi._logger") as log:
            sent = self._send(
                handler,
                [
                    ("Date", "Thu, 01 Jan 2026 00:00:00 GMT"),
                    ("Date", "Thu, 01 Jan 2026 00:00:05 -0000"),
                ],
            )
        # Genuinely different instants -> both sent, one warning, no exception.
        assert len(sent) == 2
        log.warning.assert_called_once()

    def test_malformed_second_date_does_not_crash(self, handler):
        with patch("odoo.service.wsgi._logger") as log:
            sent = self._send(
                handler,
                [
                    ("Date", "Thu, 01 Jan 2026 00:00:00 GMT"),
                    ("Date", "not-a-real-date"),
                ],
            )
        # Can't prove equality -> send both rather than drop one; warn, no 500.
        assert len(sent) == 2
        log.warning.assert_called_once()

    def test_malformed_first_date_does_not_crash(self, handler):
        with patch("odoo.service.wsgi._logger"):
            sent = self._send(
                handler,
                [("Date", "garbage"), ("Date", "Thu, 01 Jan 2026 00:00:00 GMT")],
            )
        assert len(sent) == 2

    def test_duplicate_server_header_sent_once(self, handler):
        sent = self._send(handler, [("Server", "odoo"), ("Server", "odoo")])
        assert sent == [("Server", "odoo")]

    def test_case_insensitive_date_keyword(self, handler):
        d = "Thu, 01 Jan 2026 00:00:00 GMT"
        sent = self._send(handler, [("date", d), ("DATE", d)])
        assert len(sent) == 1


class TestParseHttpDate:
    """``_parse_http_date()``: aware datetime or None, never raises."""

    def test_gmt_is_aware(self):
        from odoo.service.wsgi import _parse_http_date

        dt = _parse_http_date("Thu, 01 Jan 2026 00:00:00 GMT")
        assert dt is not None and dt.tzinfo is not None

    def test_minus_zero_zero_zero_zero_normalised_to_aware(self):
        from odoo.service.wsgi import _parse_http_date

        dt = _parse_http_date("Thu, 01 Jan 2026 00:00:00 -0000")
        assert dt is not None and dt.tzinfo is not None  # naive -> pinned UTC

    def test_garbage_returns_none(self):
        from odoo.service.wsgi import _parse_http_date

        assert _parse_http_date("definitely not a date") is None

    def test_two_forms_of_same_instant_are_equal(self):
        from odoo.service.wsgi import _parse_http_date

        a = _parse_http_date("Thu, 01 Jan 2026 00:00:00 GMT")
        b = _parse_http_date("Thu, 01 Jan 2026 00:00:00 -0000")
        assert a == b  # the subtraction the override does can't TypeError


class TestCommonRequestHandlerLogRequest:
    """``log_request()``: ANSI colour dispatch per HTTP status code.

    All tests force ``_ANSI_ENABLED=True`` because pytest captures stderr to
    a non-TTY pipe, which (correctly) gates the colour codes off in the
    runtime — that gating is exercised separately in
    ``TestCommonRequestHandlerLogRequestNoTTY``.
    """

    def _captured_styles(self, log_handler, code):
        """Return the style args passed to ``_ansi_style`` for the given code."""
        captured = []
        with (
            patch("odoo.service.wsgi._ANSI_ENABLED", True),
            patch.object(
                werkzeug.serving,
                "_ansi_style",
                side_effect=lambda msg, *styles: captured.append(styles) or msg,
            ),
        ):
            log_handler.log_request(code, 0)
        return captured

    def test_200_no_ansi_styling(self, log_handler):
        with (
            patch("odoo.service.wsgi._ANSI_ENABLED", True),
            patch.object(werkzeug.serving, "_ansi_style") as mock_ansi,
        ):
            log_handler.log_request(200, 0)
        mock_ansi.assert_not_called()

    def test_304_styled_cyan_not_green(self, log_handler):
        """304 must match the explicit ``cyan`` branch before the generic 3xx ``green``."""
        styles = self._captured_styles(log_handler, 304)
        assert ("cyan",) in styles
        assert ("green",) not in styles

    def test_301_styled_green(self, log_handler):
        styles = self._captured_styles(log_handler, 301)
        assert ("green",) in styles

    def test_404_styled_yellow(self, log_handler):
        styles = self._captured_styles(log_handler, 404)
        assert ("yellow",) in styles

    def test_500_styled_bold_magenta(self, log_handler):
        styles = self._captured_styles(log_handler, 500)
        assert ("bold", "magenta") in styles


class TestCommonRequestHandlerLogRequestNoTTY:
    """``log_request()``: when stderr is not a TTY (logfile / systemd /
    captured-output mode), the status-code branches MUST NOT call
    ``_ansi_style`` — otherwise raw ESC sequences land in the log file."""

    def test_no_ansi_calls_when_disabled(self, log_handler):
        with (
            patch("odoo.service.wsgi._ANSI_ENABLED", False),
            patch.object(werkzeug.serving, "_ansi_style") as mock_ansi,
        ):
            for code in (101, 200, 301, 304, 404, 500):
                log_handler.log_request(code, 0)
        mock_ansi.assert_not_called()

    def test_bad_requestline_falls_back_to_requestline(self, srv, monkeypatch):
        """AttributeError on ``self.path`` (malformed request) must not raise."""
        h = object.__new__(srv.CommonRequestHandler)
        # Intentionally do NOT set h.path → AttributeError in the try block
        h.requestline = "GARBAGE_LINE"
        h.log = MagicMock()
        stamp_rpc_model_method(monkeypatch)
        h.log_request(200, 0)
        logged_msg = str(h.log.call_args)
        assert "GARBAGE_LINE" in logged_msg


class TestCommonRequestHandlerLogRequestControlChars:
    """``log_request()`` MUST neutralize control characters before logging.

    Both the decoded request path and the ``rpc_model_method`` fragment (set
    from the raw RPC ``method`` param, before validation) are attacker-controlled;
    an unescaped ESC/CSI byte would render as a live terminal sequence in an
    operator's log.  werkzeug's own ``log_request`` applies this translation and
    the fork's override must not drop it.
    """

    ESC = "\x1b"

    def _logged_msg(self, handler):
        # self.log("info", '"%s" %s %s', msg, code, size) -> msg is args[2].
        return handler.log.call_args.args[2]

    def test_control_chars_in_path_are_escaped(self, log_handler):
        log_handler.path = f"/web/login{self.ESC}[2Jspoof"
        log_handler.requestline = "GET /web/login HTTP/1.1"
        with patch("odoo.service.wsgi._ANSI_ENABLED", False):
            log_handler.log_request(404, 0)
        assert self.ESC not in self._logged_msg(log_handler)
        assert "\\x1b" in self._logged_msg(log_handler)

    def test_control_chars_in_rpc_fragment_are_escaped(self, log_handler, monkeypatch):
        stamp_rpc_model_method(monkeypatch, f"res.users.read{self.ESC}[31mINJECT")
        with patch("odoo.service.wsgi._ANSI_ENABLED", False):
            log_handler.log_request(200, 0)
        msg = self._logged_msg(log_handler)
        assert self.ESC not in msg
        assert "INJECT" in msg  # payload text kept, only the ESC byte escaped

    def test_control_chars_escaped_in_bad_requestline_fallback(self, srv, monkeypatch):
        h = object.__new__(srv.CommonRequestHandler)
        h.requestline = f"GARBAGE{self.ESC}[2K"
        h.log = MagicMock()
        stamp_rpc_model_method(monkeypatch)
        with patch("odoo.service.wsgi._ANSI_ENABLED", False):
            h.log_request(200, 0)
        assert self.ESC not in h.log.call_args.args[1]


# ---------------------------------------------------------------------------
# RequestHandler.send_header() / end_headers() — WebSocket guards
# ---------------------------------------------------------------------------


@pytest.fixture
def request_handler(srv):
    """Minimal RequestHandler for WebSocket header tests."""
    h = object.__new__(srv.RequestHandler)
    h.headers = MagicMock()
    h.close_connection = False
    h.rfile = MagicMock()
    h.wfile = MagicMock()
    return h


class TestRequestHandlerWebSocket:
    """``send_header()`` / ``end_headers()``: WebSocket upgrade handling."""

    def test_websocket_connection_close_is_suppressed(self, request_handler):
        request_handler.headers.get.return_value = "websocket"
        with patch.object(
            http.server.BaseHTTPRequestHandler, "send_header"
        ) as mock_send:
            request_handler.send_header("Connection", "close")
        mock_send.assert_not_called()
        assert request_handler.close_connection is True

    def test_non_websocket_connection_close_forwarded(self, request_handler):
        request_handler.headers.get.return_value = None
        with patch.object(
            http.server.BaseHTTPRequestHandler, "send_header"
        ) as mock_send:
            request_handler.send_header("Connection", "close")
        mock_send.assert_called_once_with("Connection", "close")
        assert request_handler.close_connection is False

    def test_end_headers_websocket_replaces_streams(self, request_handler):
        request_handler.headers.get.return_value = "websocket"
        with patch.object(http.server.BaseHTTPRequestHandler, "end_headers"):
            request_handler.end_headers()
        assert isinstance(request_handler.rfile, BytesIO)
        assert isinstance(request_handler.wfile, BytesIO)

    def test_end_headers_non_websocket_leaves_streams_unchanged(self, request_handler):
        request_handler.headers.get.return_value = None
        original_rfile = request_handler.rfile
        original_wfile = request_handler.wfile
        with patch.object(http.server.BaseHTTPRequestHandler, "end_headers"):
            request_handler.end_headers()
        assert request_handler.rfile is original_rfile
        assert request_handler.wfile is original_wfile


class TestRequestHandlerBeforeHeadersParsed:
    """The WebSocket guards must tolerate ``self.headers`` not existing yet.

    ``BaseHTTPRequestHandler`` assigns ``self.headers`` only after it has parsed
    the request line.  A MALFORMED request line makes it call ``send_error(400)``
    — hence ``send_header`` and ``end_headers`` — while the attribute is still
    unset, and werkzeug's ``WSGIRequestHandler.__getattr__`` forwards the lookup
    to ``super()``, which has no ``headers`` either.

    Reading it unguarded raised ``AttributeError`` from inside the error path, so
    the 400 died half-written and the client received NOTHING while the server
    logged an ERROR traceback — reachable unauthenticated by anyone who can open
    a socket (a browser sent to ``https://host:8069``, a TLS probe, a port
    scanner) on both servers using this handler.  Verified end-to-end against a
    live server: three malformed request shapes each returned b'' before the fix
    and a proper 400 body after it.
    """

    @pytest.fixture
    def unparsed_handler(self, srv):
        """A handler in the exact state ``send_error`` sees on a bad request line.

        ``_sent_date_header`` / ``_sent_server_header`` ARE set, because
        ``CommonRequestHandler.__init__`` assigns them before delegating to
        ``socketserver.BaseRequestHandler.__init__``, which is what runs
        ``setup()``/``handle()`` — so they always exist by the time any request
        byte is parsed.  ``headers`` is NOT set, because only ``parse_request``
        assigns it and it has just failed.
        """
        h = object.__new__(srv.RequestHandler)
        h._sent_date_header = None
        h._sent_server_header = None
        h.close_connection = False
        h.rfile = MagicMock()
        h.wfile = MagicMock()
        assert not hasattr(h, "headers"), "fixture must reproduce the unset state"
        return h

    def test_send_header_does_not_raise_and_forwards(self, unparsed_handler):
        with patch.object(
            http.server.BaseHTTPRequestHandler, "send_header"
        ) as mock_send:
            unparsed_handler.send_header("Server", "Werkzeug")
            unparsed_handler.send_header("Connection", "close")
        assert mock_send.call_args_list == [
            call("Server", "Werkzeug"),
            call("Connection", "close"),
        ]
        # No upgrade was requested, so the connection must not be flagged closed
        # by the WebSocket branch.
        assert unparsed_handler.close_connection is False

    def test_end_headers_does_not_raise_and_keeps_streams(self, unparsed_handler):
        original_rfile = unparsed_handler.rfile
        original_wfile = unparsed_handler.wfile
        with patch.object(http.server.BaseHTTPRequestHandler, "end_headers"):
            unparsed_handler.end_headers()
        assert unparsed_handler.rfile is original_rfile
        assert unparsed_handler.wfile is original_wfile

    def test_helper_reports_no_upgrade_when_headers_missing(self, unparsed_handler):
        assert unparsed_handler._is_websocket_upgrade() is False


class TestRequestHandlerSocketTimeout:
    """An idle half-open connection must not park a bounded-thread slot forever.

    A handler blocks in ``rfile.readline()`` until the request line arrives, so
    without a socket timeout a client that connects and sends a few bytes with no
    CRLF holds one of the ``max_http_threads`` slots indefinitely.  Measured
    against a live threaded server: six such connections (nine bytes each) took
    the pool to 0/4 and every subsequent request timed out; with the timeout
    armed, 7 of 8 requests were served while TWELVE attackers held connections,
    and the pool returned to 4/4 once they left.

    Prefork was never exposed — ``WorkerHTTP`` has always set this on each
    accepted socket — so both paths now resolve it from the same helper.
    """

    @pytest.fixture
    def wsgi_mod(self):
        """``server.py`` re-exports names via ``from .wsgi import ...``, so it
        binds no ``wsgi`` attribute; reach the module itself."""
        import odoo.service.wsgi as mod

        return mod

    def _handler(self, srv):
        h = object.__new__(srv.RequestHandler)
        h.timeout = None
        return h

    def _setup_with(self, wsgi_mod, handler, test_enable):
        """Drive the real ``RequestHandler.setup()``, restoring the thread name.

        ``setup()`` renames the calling thread to
        ``odoo.service.http.request.<ident>`` — correct in a served request,
        but here the caller is pytest's MainThread, so the rename outlived the
        test and every later log record and thread-name assertion saw it.
        """
        cfg = {"test_enable": test_enable, "dev_mode": []}
        me = threading.current_thread()
        original_name = me.name
        try:
            with (
                patch.object(wsgi_mod, "config", cfg),
                patch.object(werkzeug.serving.WSGIRequestHandler, "setup"),
            ):
                handler.setup()
        finally:
            me.name = original_name

    def test_timeout_is_armed_outside_test_mode(self, srv, wsgi_mod):
        """The regression itself: this used to be armed ONLY under
        ``--test-enable``, leaving every real deployment of the threaded and
        evented servers open to trivial thread exhaustion."""
        h = self._handler(srv)
        self._setup_with(wsgi_mod, h, test_enable=False)
        assert h.timeout == wsgi_mod.http_socket_timeout()
        assert h.timeout > 0

    def test_test_mode_keeps_the_longer_preconnect_grace(self, srv, wsgi_mod):
        h = self._handler(srv)
        self._setup_with(wsgi_mod, h, test_enable=True)
        assert h.timeout >= 5

    def test_prefork_and_threaded_share_one_knob(
        self, srv, wsgi_mod, multi, monkeypatch
    ):
        """Two independent defaults would let deployments drift into different
        DoS postures, which is exactly how the threaded gap survived."""
        monkeypatch.setenv("ODOO_HTTP_SOCKET_TIMEOUT", "7.5")
        worker = srv.WorkerHTTP(multi)
        try:
            assert worker.sock_timeout == wsgi_mod.http_socket_timeout() == 7.5
        finally:
            worker.close()

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("0", 0.1), ("-3", 0.1), ("not-a-number", 2.0), ("30", 30.0)],
    )
    def test_env_override_is_clamped_and_degrades_safely(
        self, wsgi_mod, monkeypatch, raw, expected
    ):
        """``0`` would put the socket in non-blocking mode and break every
        request, so it clamps to the floor rather than disabling the bound."""
        monkeypatch.setenv("ODOO_HTTP_SOCKET_TIMEOUT", raw)
        assert wsgi_mod.http_socket_timeout() == expected

    def test_upgrade_clears_the_deadline_for_the_websocket_loop(self, srv):
        """A websocket is legitimately idle for minutes; ``bus/websocket.py``
        drives the socket through its own selector, so the request-phase
        deadline must be lifted once the 101 is committed."""
        h = object.__new__(srv.RequestHandler)
        h.connection = MagicMock()
        h.request = MagicMock()
        h.server = MagicMock(spec=[])  # no release_upgraded_request_slot
        with patch.object(http.server.BaseHTTPRequestHandler, "send_response"):
            h.send_response(101)
        h.connection.settimeout.assert_called_once_with(None)

    def test_non_upgrade_response_keeps_the_deadline(self, srv):
        h = object.__new__(srv.RequestHandler)
        h.connection = MagicMock()
        h.request = MagicMock()
        h.server = MagicMock(spec=[])
        with patch.object(http.server.BaseHTTPRequestHandler, "send_response"):
            h.send_response(200)
        h.connection.settimeout.assert_not_called()


# ---------------------------------------------------------------------------
# ThreadedWSGIServerReloadable — semaphore throttle
# ---------------------------------------------------------------------------


@pytest.fixture
def threaded_server(srv):
    """Minimal ThreadedWSGIServerReloadable bypassing socket/bind init."""
    import weakref

    s = object.__new__(srv.ThreadedWSGIServerReloadable)
    s.max_http_threads = 4
    s.http_threads_sem = MagicMock()
    # Set in real ``__init__`` next to the semaphore; required by
    # ``shutdown_request`` to dedupe double-release on the inline +
    # SystemExit path.  Mirror it here for the unit tests that bypass
    # ``__init__``.
    s._sem_released_requests = weakref.WeakSet()
    return s


class TestThreadedWSGIServerAutoLimit:
    """``__init__``: the default thread bound reserves cron AND job cursors."""

    def test_auto_limit_subtracts_cron_and_job_threads(self, srv, monkeypatch):
        monkeypatch.delenv("ODOO_MAX_HTTP_THREADS", raising=False)
        from odoo.service import wsgi as wsgi_mod

        cfg = {"db_maxconn": 20, "max_cron_threads": 2, "job_workers": 4}
        with (
            patch.object(wsgi_mod, "config", cfg),
            patch.object(
                werkzeug.serving.ThreadedWSGIServer, "__init__", return_value=None
            ),
        ):
            s = srv.ThreadedWSGIServerReloadable("127.0.0.1", 0, MagicMock())
        assert s.max_http_threads == (20 - 2 - 4) // 2

    def test_auto_limit_floors_at_one(self, srv, monkeypatch):
        monkeypatch.delenv("ODOO_MAX_HTTP_THREADS", raising=False)
        from odoo.service import wsgi as wsgi_mod

        cfg = {"db_maxconn": 5, "max_cron_threads": 2, "job_workers": 4}
        with (
            patch.object(wsgi_mod, "config", cfg),
            patch.object(
                werkzeug.serving.ThreadedWSGIServer, "__init__", return_value=None
            ),
        ):
            s = srv.ThreadedWSGIServerReloadable("127.0.0.1", 0, MagicMock())
        assert s.max_http_threads == 1


class TestThreadedWSGIServerSemaphore:
    """Concurrent connection throttle via ``max_http_threads`` semaphore."""

    def test_semaphore_full_skips_processing(self, threaded_server):
        threaded_server.http_threads_sem.acquire.return_value = False
        with patch.object(
            werkzeug.serving.ThreadedWSGIServer, "_handle_request_noblock"
        ) as mock_super:
            threaded_server._handle_request_noblock()
        mock_super.assert_not_called()

    def test_semaphore_acquired_calls_super(self, threaded_server):
        threaded_server.http_threads_sem.acquire.return_value = True
        with patch.object(
            werkzeug.serving.ThreadedWSGIServer, "_handle_request_noblock"
        ) as mock_super:
            threaded_server._handle_request_noblock()
        mock_super.assert_called_once()

    def test_no_semaphore_calls_super_directly(self, threaded_server):
        threaded_server.max_http_threads = None
        with patch.object(
            werkzeug.serving.ThreadedWSGIServer, "_handle_request_noblock"
        ) as mock_super:
            threaded_server._handle_request_noblock()
        mock_super.assert_called_once()

    def test_shutdown_releases_semaphore(self, threaded_server):
        with patch.object(werkzeug.serving.ThreadedWSGIServer, "shutdown_request"):
            threaded_server.shutdown_request(MagicMock())
        threaded_server.http_threads_sem.release.assert_called_once()

    def test_shutdown_no_semaphore_skips_release(self, threaded_server):
        threaded_server.max_http_threads = None
        with patch.object(werkzeug.serving.ThreadedWSGIServer, "shutdown_request"):
            threaded_server.shutdown_request(MagicMock())
        threaded_server.http_threads_sem.release.assert_not_called()

    def test_shutdown_idempotent_for_same_request(self, threaded_server):
        """Two ``shutdown_request`` calls for the same socket release once.

        Regression: an inline-fail + ``SystemExit`` propagation path inside
        ``process_request`` reaches ``shutdown_request`` twice (once from
        ``process_request_thread``'s ``finally``, once from
        ``socketserver.BaseServer._handle_request_noblock``'s outer bare
        ``except:`` handler).  Without dedup, every such request would
        leak one Semaphore unit, slowly inflating the configured
        ``max_http_threads`` cap.
        """
        request = MagicMock()
        with patch.object(werkzeug.serving.ThreadedWSGIServer, "shutdown_request"):
            threaded_server.shutdown_request(request)
            threaded_server.shutdown_request(request)
        threaded_server.http_threads_sem.release.assert_called_once()

    def test_shutdown_distinct_requests_release_independently(self, threaded_server):
        """Different request sockets each get exactly one release.

        The dedup key is the request object identity, not a global "we
        released once" flag — concurrent requests must each balance their
        own acquire/release.
        """
        with patch.object(werkzeug.serving.ThreadedWSGIServer, "shutdown_request"):
            threaded_server.shutdown_request(MagicMock())
            threaded_server.shutdown_request(MagicMock())
            threaded_server.shutdown_request(MagicMock())
        assert threaded_server.http_threads_sem.release.call_count == 3


# ---------------------------------------------------------------------------
# ThreadedServer.process_limit()
# ---------------------------------------------------------------------------


@pytest.fixture
def tserver(srv):
    """Minimal ThreadedServer bypassing socket/config init for process_limit() tests."""
    s = object.__new__(srv.ThreadedServer)
    s.limits_reached_threads = set()
    s.limit_reached_time = None
    s.logger = MagicMock()
    # ``_process_handle`` is set in ``__init__`` (psutil.Process(os.getpid()))
    # so that ``check_limits`` can reuse it across ticks instead of paying the
    # /proc/<pid>/stat read on every call.  Bypassing __init__ in tests means
    # we have to stub it; the patched ``memory_info`` ignores the argument
    # anyway.
    s._process_handle = MagicMock()
    return s


class TestThreadedServerProcessLimit:
    """``process_limit()``: memory soft limit, per-thread real-time limit, and cleanup."""

    @staticmethod
    @contextlib.contextmanager
    def _env(memory=0, config_override=None, threads=()):
        """Stub everything ``process_limit`` reads: RSS, config, psutil, threads.

        A context manager for the same reason as :func:`worker_check_limits_env`
        — the list-of-patches form it replaces was entered by index
        (``patches[0], patches[1], patches[2]``) at eight call sites, so a fourth
        patch would have applied at none of them.  ``threads`` is folded in
        because every one of those sites paired the helper with its own
        ``threading.enumerate`` patch anyway.
        """
        cfg = {
            "limit_memory_soft": 0,
            "limit_time_real": 60,
            "limit_time_real_cron": 0,
            **(config_override or {}),
        }
        with (
            patch("odoo.service._helpers.memory_info", return_value=memory),
            patch("odoo.service._threaded.config", cfg),
            patch("odoo.service._threaded.psutil"),
            patch("threading.enumerate", return_value=list(threads)),
        ):
            yield

    def test_memory_soft_exceeded_sets_limit_reached_time(self, tserver):
        # Memory breach is a PROCESS condition, tracked per-tick — it sets
        # ``limit_reached_time`` (driving the reload gate) WITHOUT polluting the
        # per-thread ``limits_reached_threads`` set with the never-pruned main
        # thread (which used to latch a recovered server into reload).
        import threading

        with self._env(
            memory=2000, config_override={"limit_memory_soft": 1000}, threads=[]
        ):
            tserver.process_limit()
        assert tserver.limit_reached_time is not None
        assert threading.current_thread() not in tserver.limits_reached_threads

    def test_transient_memory_spike_does_not_latch_reload(self, tserver):
        # A spike over the soft limit followed by recovery must NOT leave the
        # server pinned in reload state.  Regression for the latch where the
        # main thread was added to ``limits_reached_threads`` and, being always
        # alive, was never pruned — keeping ``limit_reached_time`` set forever.
        cfg = {"limit_memory_soft": 1000}

        def tick(mem):
            with (
                patch("odoo.service._helpers.memory_info", return_value=mem),
                patch("odoo.service._threaded.config", cfg),
                patch("odoo.service._threaded.psutil"),
                patch("threading.enumerate", return_value=[]),
            ):
                tserver.process_limit()

        tick(2000)  # over the soft limit
        assert tserver.limit_reached_time is not None
        tick(100)  # recovered, well under
        assert tserver.limit_reached_time is None
        assert not tserver.limits_reached_threads

    def test_thread_real_time_exceeded_adds_thread(self, tserver):
        mock_thread = MagicMock()
        mock_thread.daemon = False
        mock_thread.type = "http"
        mock_thread.start_time = time.monotonic() - 9999
        mock_thread.is_alive.return_value = True

        with self._env(config_override={"limit_time_real": 60}, threads=[mock_thread]):
            tserver.process_limit()
        assert mock_thread in tserver.limits_reached_threads

    def test_cron_thread_uses_cron_time_limit(self, tserver):
        """Cron threads use ``limit_time_real_cron`` instead of ``limit_time_real``."""
        mock_thread = MagicMock()
        mock_thread.daemon = False
        mock_thread.type = "cron"
        # 120s elapsed — over cron limit (60) but under http limit (3600)
        mock_thread.start_time = time.monotonic() - 120
        mock_thread.is_alive.return_value = True

        with self._env(
            config_override={"limit_time_real": 3600, "limit_time_real_cron": 60},
            threads=[mock_thread],
        ):
            tserver.process_limit()
        assert mock_thread in tserver.limits_reached_threads

    def test_dead_thread_pruned_from_limits_reached(self, tserver):
        dead = MagicMock()
        dead.is_alive.return_value = False
        tserver.limits_reached_threads.add(dead)

        with self._env(threads=[]):
            tserver.process_limit()
        assert dead not in tserver.limits_reached_threads

    def test_limit_reached_time_set_and_cleared(self, tserver):
        """``limit_reached_time`` is set when threads exceed limits, cleared when all clear."""
        mock_thread = MagicMock()
        mock_thread.daemon = False
        mock_thread.type = "http"
        mock_thread.start_time = time.monotonic() - 9999
        mock_thread.is_alive.return_value = True

        with self._env(config_override={"limit_time_real": 60}, threads=[mock_thread]):
            tserver.process_limit()
        assert tserver.limit_reached_time is not None

        # remove the offending thread and run again — time should clear
        tserver.limits_reached_threads.clear()
        mock_thread.start_time = None  # no longer over limit
        with self._env(config_override={"limit_time_real": 60}, threads=[mock_thread]):
            tserver.process_limit()
        assert tserver.limit_reached_time is None

    def test_websocket_thread_not_counted(self, tserver):
        """WebSocket threads are never subject to real-time limits."""
        mock_thread = MagicMock()
        mock_thread.daemon = False
        mock_thread.type = "websocket"
        mock_thread.start_time = time.monotonic() - 9999  # way over any limit
        mock_thread.is_alive.return_value = True

        with self._env(config_override={"limit_time_real": 1}, threads=[mock_thread]):
            tserver.process_limit()
        assert mock_thread not in tserver.limits_reached_threads

    def test_single_monotonic_call_per_invocation(self, tserver):
        """process_limit() captures time.monotonic() once before the thread loop.

        Calling time.monotonic() per-thread (as process_timeout() does NOT) would
        introduce jitter: later threads appear to have run longer than earlier ones
        within the same check cycle, leading to non-deterministic kill ordering.
        This test verifies the fix: a single snapshot is used for all comparisons.
        """
        threads = []
        for _ in range(5):
            t = MagicMock()
            t.daemon = False
            t.type = "http"
            # All threads have the same start_time — with a single snapshot all
            # get the same elapsed time; with per-thread calls they'd diverge.
            t.start_time = time.monotonic() - 9999
            t.is_alive.return_value = True
            threads.append(t)

        original_monotonic = time.monotonic

        with (
            self._env(config_override={"limit_time_real": 1}, threads=threads),
            patch("odoo.service._threaded.time") as mock_time,
        ):
            mock_time.monotonic.side_effect = original_monotonic
            tserver.process_limit()

        # One call for the loop snapshot + one call for limit_reached_time = 2 max.
        # Before the fix this would be len(threads) + 1 = 6.
        assert mock_time.monotonic.call_count <= 2


# ---------------------------------------------------------------------------
# Socket activation: IPv6 family detection
# ---------------------------------------------------------------------------


@pytest.fixture
def inherited_listener(request):
    """A real, bound, listening socket of the requested family.

    Stands in for the fd a re-exec'd master inherits (``ODOO_HTTP_SOCKET_FD``)
    or systemd passes (``LISTEN_FDS``).  Closed by the fixture; the code under
    test only ever wraps the descriptor, so the test detaches its own wrapper.
    """
    family, addr = request.param
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.bind(addr)
    sock.listen(1)
    try:
        yield sock
    finally:
        sock.close()


def _adopt_inherited_fd(fd, *, via_env, interface):
    """Drive ``PreforkServer.start()``'s fd-adoption branch; return its socket.

    ``start()`` is entered for real — including ``_set_socket_cloexec`` — so the
    assertion is about the socket the SERVER ends up with, not about a
    hand-copied expression.  Only the pieces that would touch the process
    (signal disposition, the self-pipe) are stubbed.
    """
    server = object.__new__(_prefork.PreforkServer)
    server.logger = MagicMock()
    server.interface, server.port, server.population = interface, 0, 2
    server.pipe_new = MagicMock(return_value=(0, 0))
    cfg = MagicMock()
    cfg.__getitem__.side_effect = {"http_enable": True}.__getitem__
    cfg.http_socket_activation = not via_env
    env = {"ODOO_HTTP_SOCKET_FD": str(fd)} if via_env else {}
    with (
        patch.object(_prefork, "config", cfg),
        patch.object(signal, "signal"),
        patch.dict(os.environ, env, clear=False),
    ):
        if not via_env:
            os.environ.pop("ODOO_HTTP_SOCKET_FD", None)
        server.start()
    return server.socket


V6 = pytest.param((socket.AF_INET6, ("::1", 0)), id="ipv6")
V4 = pytest.param((socket.AF_INET, ("127.0.0.1", 0)), id="ipv4")


class TestInheritedListenSocketKeepsItsFamily:
    """A listen socket adopted from another process must keep its address family.

    Regression: ``socket.fromfd(fd, AF_INET, SOCK_STREAM)`` asserts a family
    rather than reading one.  ``socket.socket(fileno=fd)`` auto-detects the
    kernel-assigned family via ``SO_DOMAIN``, so an IPv6 listener stays
    ``AF_INET6`` across the wrap.

    With the bug, ``getsockname()`` and ``accept()`` unpack ``sockaddr_in6``
    memory as ``sockaddr_in``: measured on this tree, an ``::1`` listener came
    back as ``('::ffff:ffff:ffff:ffff', 40741, 0, 4104433920)`` — a garbage
    address and a random scope id, corrupting every access-log line from an
    IPv6 client.

    These tests DRIVE ``PreforkServer.start()``.  The version they replace
    asserted ``socket.socket(fileno=...)`` behaviour directly, referencing no
    Odoo code at all: verified by mutation, reverting all three adoption sites
    (``_prefork.py`` twice, ``wsgi.py`` once) to the buggy ``fromfd`` form left
    the entire 837-test suite green — including ``tests/process``, which
    performs a real SIGHUP re-exec but binds ``127.0.0.1``, where the two forms
    are indistinguishable.  So the fix shipped with no coverage whatsoever.
    """

    @pytest.mark.parametrize("inherited_listener", [V6, V4], indirect=True)
    def test_reload_handoff_preserves_the_family(self, inherited_listener):
        """``ODOO_HTTP_SOCKET_FD``: the fd a re-exec'd master inherits."""
        expected = inherited_listener.getsockname()
        adopted = _adopt_inherited_fd(
            inherited_listener.fileno(),
            via_env=True,
            interface=expected[0],
        )
        try:
            assert adopted.family == inherited_listener.family
            assert adopted.getsockname() == expected
        finally:
            adopted.detach()

    @pytest.mark.parametrize("inherited_listener", [V6, V4], indirect=True)
    def test_socket_activation_preserves_the_family(self, inherited_listener):
        """``LISTEN_FDS``: the fd systemd passes as ``SD_LISTEN_FDS_START`` (3).

        ``SD_LISTEN_FDS_START`` is a local in ``start()`` and cannot be patched,
        so the listener really is placed on fd 3 — which pytest's capture also
        uses.  Its occupant is saved and restored around the call; without that
        the run dies with ``OSError: Bad file descriptor`` in capture teardown,
        long after this test reported success.
        """
        expected = inherited_listener.getsockname()
        saved_fd3 = os.dup(3)
        try:
            os.dup2(inherited_listener.fileno(), 3, inheritable=True)
            adopted = _adopt_inherited_fd(3, via_env=False, interface=expected[0])
            try:
                assert adopted.family == inherited_listener.family
                assert adopted.getsockname() == expected
            finally:
                adopted.detach()
        finally:
            os.dup2(saved_fd3, 3)
            os.close(saved_fd3)

    @pytest.mark.parametrize("inherited_listener", [V6], indirect=True)
    def test_the_adopted_socket_is_cloexec(self, inherited_listener):
        """An inherited listener arrives without ``FD_CLOEXEC``; ``start()`` must
        set it, or every ``pg_dump``/``psql`` subprocess keeps the port open and
        a restart fails with EADDRINUSE until they exit."""
        adopted = _adopt_inherited_fd(
            inherited_listener.fileno(), via_env=True, interface="::1"
        )
        try:
            flags = fcntl.fcntl(adopted.fileno(), fcntl.F_GETFD)
            assert flags & fcntl.FD_CLOEXEC
        finally:
            adopted.detach()


# ---------------------------------------------------------------------------
# PreforkServer.fork_and_reload — reload-timeout contract
# ---------------------------------------------------------------------------


class TestForkAndReloadTimeout:
    """``fork_and_reload()`` must signal readiness via its return value.

    Regression: without the return value, ``stop()`` unconditionally called
    ``stop_workers_gracefully()`` even when ``phoenix_hatched`` was False —
    leaving the listening port unbound after the 60-second timeout.
    """

    def test_fork_and_reload_returns_true_on_sighup(self, srv):
        """When SIGHUP fires while waiting, fork_and_reload() returns True."""
        ps = object.__new__(srv.PreforkServer)
        ps.logger = MagicMock()
        ps.socket = MagicMock()
        ps.socket.fileno.return_value = 99

        with (
            patch.object(os, "fork", return_value=0),  # child branch
            patch.object(_prefork.fcntl, "fcntl", return_value=0),
            patch.object(signal, "signal") as mock_sig,
            # An UNBOUNDED clock, deliberately.  A fixed list means any future
            # extra ``monotonic()`` call in ``fork_and_reload`` raises
            # ``StopIteration`` from inside the mock — a failure naming neither
            # the behaviour nor the change that caused it.  Verified: adding one
            # clock read to the function turned the sibling test below into a
            # bare ``StopIteration``.  ``count`` keeps the determinism (0.0,
            # 0.1, 0.2, …) with no cliff.
            patch.object(time, "monotonic", side_effect=itertools.count(0.0, 0.1)),
            patch.object(time, "sleep"),
        ):
            # Capture the handler so we can fire SIGHUP manually before timeout.
            handlers = {}

            def capture_handler(sig, handler):
                handlers[sig] = handler

            mock_sig.side_effect = capture_handler

            # Pre-fire the handler so phoenix_hatched is True on loop entry.
            def fire_handler_on_install(sig, handler):
                handlers[sig] = handler
                if sig == signal.SIGHUP:
                    handler(sig, None)

            mock_sig.side_effect = fire_handler_on_install

            result = ps.fork_and_reload()

        assert result is True

    def test_fork_and_reload_returns_false_on_timeout(self, srv):
        """When SIGHUP never arrives, fork_and_reload() returns False."""
        ps = object.__new__(srv.PreforkServer)
        ps.logger = MagicMock()
        ps.socket = MagicMock()
        ps.socket.fileno.return_value = 99

        # Drive the monotonic clock past the 60-second budget immediately: the
        # first read arms the deadline at t+timeout, every later one is already
        # far beyond it, so the while loop exits on its first check.
        # Unbounded (see the sibling test above) — the fixed 5-element list this
        # replaces died with a bare ``StopIteration`` the moment the function
        # read the clock once more.
        times = itertools.chain([0.0], itertools.count(70.0, 0.1))

        with (
            patch.object(os, "fork", return_value=0),
            patch.object(_prefork.fcntl, "fcntl", return_value=0),
            patch.object(signal, "signal"),
            patch.object(time, "monotonic", side_effect=lambda: next(times)),
            patch.object(time, "sleep"),
        ):
            result = ps.fork_and_reload()

        assert result is False
        ps.logger.error.assert_called()

    def test_stop_preserves_old_workers_when_reload_fails(self, srv):
        """stop() must NOT call stop_workers_gracefully() on reload timeout.

        ``PreforkServer.stop`` reads ``lifecycle.server_phoenix`` (the single
        source of truth), so the patch must target ``lifecycle`` directly.
        """
        from odoo.service import lifecycle

        ps = object.__new__(srv.PreforkServer)
        ps.logger = MagicMock()
        ps.socket = MagicMock()
        ps.workers = {}

        with (
            patch.object(ps, "fork_and_reload", return_value=False) as mock_fr,
            patch.object(ps, "stop_workers_gracefully") as mock_swg,
            patch.object(lifecycle, "server_phoenix", True),
        ):
            ps.stop()

        mock_fr.assert_called_once()
        mock_swg.assert_not_called()  # <-- the whole point of the fix
        ps.logger.error.assert_called()

    def test_stop_shuts_down_workers_when_reload_succeeds(self, srv):
        """Happy path: new server came up, old workers are shut down."""
        from odoo.service import lifecycle

        ps = object.__new__(srv.PreforkServer)
        ps.logger = MagicMock()
        ps.socket = MagicMock()
        ps.workers = {}

        with (
            patch.object(ps, "fork_and_reload", return_value=True),
            patch.object(ps, "stop_workers_gracefully") as mock_swg,
            patch.object(lifecycle, "server_phoenix", True),
        ):
            ps.stop()

        mock_swg.assert_called_once()


# ---------------------------------------------------------------------------
# lifecycle.start() — watcher cleanup on the error path
# ---------------------------------------------------------------------------


class TestOnStopFuncsModuleLevel:
    """``_ON_STOP_FUNCS`` is the single, module-level store for stop hooks.

    The previous ``CommonServer._on_stop_funcs`` class-level alias was
    intentionally removed: reassigning it (``CommonServer._on_stop_funcs = [...]``)
    would desync from ``_ON_STOP_FUNCS`` silently, while ``on_stop`` kept
    appending to the original module list. Removing the alias collapses
    the state surface to one canonical location.
    """

    @pytest.fixture(autouse=True)
    def _restore(self, srv):
        original_module = list(srv._ON_STOP_FUNCS)
        yield
        srv._ON_STOP_FUNCS[:] = original_module

    def test_module_level_list_exists(self, srv):
        assert hasattr(srv, "_ON_STOP_FUNCS")
        assert isinstance(srv._ON_STOP_FUNCS, list)

    def test_class_attr_intentionally_absent(self, srv):
        """``CommonServer._on_stop_funcs`` must NOT exist — desync hazard."""
        assert not hasattr(srv.CommonServer, "_on_stop_funcs")

    def test_on_stop_appends_to_module_list(self, srv):
        cb = MagicMock()
        srv.CommonServer.on_stop(cb)
        assert cb in srv._ON_STOP_FUNCS

    def test_on_stop_is_idempotent(self, srv):
        """Registering the same callable twice records (and fires) it once.

        Without dedup, a server stopped and restarted in-process (tests, embedded
        use) — or a module imported twice — accumulates duplicate hooks in the
        append-only ``_ON_STOP_FUNCS`` and ``stop()`` fires each one N times.
        """
        cb = MagicMock()
        before = len(srv._ON_STOP_FUNCS)
        srv.CommonServer.on_stop(cb)
        srv.CommonServer.on_stop(cb)
        assert len(srv._ON_STOP_FUNCS) == before + 1

        instance = object.__new__(srv.CommonServer)
        instance.logger = MagicMock()
        instance.stop()
        cb.assert_called_once()


# ---------------------------------------------------------------------------
# SIGHUP — local sentinel, no signal-module monkey-patch
# ---------------------------------------------------------------------------


class TestStopWorkersGracefullyDictRace:
    """``stop_workers_gracefully`` iterates ``self.workers`` while
    ``worker_kill`` may pop entries (on ESRCH for an already-dead worker).
    The fix snapshots the keys with ``list(...)`` to avoid
    ``RuntimeError: dictionary changed size during iteration``.

    Regression: this race only fires under load (an HTTP worker dying right
    when graceful shutdown begins), so the pure-pytest test exercises the
    pattern in isolation rather than relying on a live prefork server.

    A companion test used to assert ``"for pid in list(self.workers)"`` appeared
    in the source.  It was removed: the function contains three such loops, so
    the substring stayed present — and the test stayed green — when the kill
    loop itself was reverted to ``for pid in self.workers``.  It also failed on
    an equivalent ``tuple(...)`` snapshot.  The behavioural test below catches
    the real regression; the source pin caught only refactors.
    """

    def test_pop_during_iteration_does_not_raise(self, prefork_server):
        """A worker_kill that ESRCH-pops mid-iteration must not crash."""
        # Stand up a multi-worker dict
        prefork_server.workers = {1: MagicMock(), 2: MagicMock(), 3: MagicMock()}
        prefork_server.workers_http = {}
        prefork_server.workers_cron = {}
        prefork_server.long_polling_pid = None
        prefork_server.beat = 0.1
        prefork_server.pid = os.getpid()

        # Make worker_kill pop pid=2 (simulating ESRCH on a dead worker)
        original_workers = prefork_server.workers

        def fake_kill(pid, sig):
            # Pop pid=2 mid-iteration to provoke the race
            if pid == 2:
                original_workers.pop(2, None)

        prefork_server.worker_kill = fake_kill

        # Patch the rest of stop_workers_gracefully's loop dependencies so we
        # exit after the kill loop without entering the watchdog while-loop.
        with (
            patch.object(
                prefork_server, "process_signals", side_effect=KeyboardInterrupt
            ),
            patch.object(prefork_server, "process_zombie"),
            patch.object(prefork_server, "sleep"),
            patch.object(prefork_server, "process_timeout"),
        ):
            # Must NOT raise "dictionary changed size during iteration"
            prefork_server.stop_workers_gracefully()

        # Confirm the popped entry is actually gone
        assert 2 not in prefork_server.workers


# ---------------------------------------------------------------------------
# memory_info log strings — RSS not VMS
# ---------------------------------------------------------------------------


class TestMemoryLogStrings:
    """``memory_info`` returns RSS (resident memory).  The messages operators
    actually read must say so — someone chasing a 'virtual memory' problem will
    look at the wrong metric otherwise.

    These assert on the emitted record rather than on ``inspect.getsource``.
    The source-text version was satisfied by the word "RSS" appearing anywhere
    in the function — a comment, a variable name — so relabelling the message to
    "VMS soft-limit reached", the exact mistake the class exists to prevent,
    kept it green.  Driving the call also proves the branch is reachable, which
    reading the source cannot.
    """

    @staticmethod
    def _only_message(logger_mock):
        """The single message emitted, with its %-args still unformatted."""
        calls = logger_mock.info.call_args_list + logger_mock.warning.call_args_list
        memory_calls = [c for c in calls if "soft-limit" in str(c.args[0])]
        assert len(memory_calls) == 1, f"expected one soft-limit log, got {calls!r}"
        return memory_calls[0].args[0]

    def test_worker_check_limits_reports_RSS(self, bare_worker):
        with worker_check_limits_env(
            memory_bytes=500, config_override={"limit_memory_soft": 100}
        ):
            bare_worker.check_limits()

        message = self._only_message(bare_worker.logger)
        assert "RSS" in message
        assert "irtual" not in message and "VMS" not in message

    def test_event_server_process_limits_reports_RSS(self, event_server):
        event_server.ppid = os.getppid()
        event_server._process_handle = MagicMock()
        cfg = {"limit_memory_soft_gevent": 100, "limit_memory_soft": 0}
        with (
            patch.object(_threaded, "config", cfg),
            patch("odoo.service._helpers.memory_info", return_value=500),
            patch.object(_threaded.os, "kill"),
        ):
            event_server.process_limits()

        message = self._only_message(event_server.logger)
        assert "RSS" in message
        assert "irtual" not in message and "VMS" not in message

    def test_memory_info_returns_rss(self):
        """Belt-and-suspenders: confirm the helper returns RSS, not VMS.

        A mocked process (rather than a live ``psutil.Process``) so the two
        reads are identical: a live process's RSS can change between the
        reference read and the helper's read, which made this assertion flaky.
        """
        proc = MagicMock()
        proc.memory_info.return_value = MagicMock(rss=111, vms=999)
        assert _helpers.memory_info(proc) == 111  # rss
        assert _helpers.memory_info(proc) != 999  # not vms


# ---------------------------------------------------------------------------
# EventServer — SIGTERM graceful shutdown (on_stop hooks must run)
# ---------------------------------------------------------------------------


@pytest.fixture
def event_server(srv):
    """EventServer that bypasses ``__init__`` (which reads config + psutil).

    Only the attributes consumed by ``start``/``stop``/``run`` are populated.
    """
    obj = object.__new__(srv.EventServer)
    obj.interface = "127.0.0.1"
    obj.port = 0
    obj.app = MagicMock()
    obj.logger = MagicMock()
    obj.httpd = None
    obj.pid = os.getpid()
    return obj


class TestEventServerGracefulStop:
    """Regression: ``EventServer`` must handle SIGINT/SIGTERM so ``stop()`` —
    and therefore the ``on_stop`` cleanup hooks (bus ``_kick_all``,
    ``_close_notify_conn``, the sass compiler) — runs.

    Before the fix ``start()`` installed only SIGQUIT/USR1/USR2, so SIGTERM
    (the signal systemd/docker/k8s send, and the one this server's own
    ``watchdog`` sends via ``os.kill`` to recycle) hit the default
    disposition and hard-killed the process, skipping every ``on_stop`` hook.
    """

    @pytest.fixture(autouse=True)
    def _restore_callbacks(self, srv):
        original = list(srv._ON_STOP_FUNCS)
        yield
        srv._ON_STOP_FUNCS[:] = original

    @pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
    def test_quit_handler_raises_keyboard_interrupt(self, event_server, sig):
        # The whole mechanism: werkzeug's serve_forever() catches
        # KeyboardInterrupt and returns, so start() returns and run() reaches
        # stop().  Calling httpd.shutdown() from the handler would deadlock
        # (same thread as serve_forever), so it MUST raise instead.
        with pytest.raises(KeyboardInterrupt):
            event_server._quit_signal_handler(sig, None)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX signal handlers")
    def test_start_installs_sigint_and_sigterm(self, event_server):
        with (
            patch.object(signal, "signal") as mock_signal,
            patch.object(werkzeug.serving, "make_server", return_value=MagicMock()),
            patch.object(threading, "Thread"),
        ):
            event_server.start()  # mock httpd.serve_forever() returns at once

        wired = {
            c.args[0]: c.args[1]
            for c in mock_signal.call_args_list
            if c.args[0] in (signal.SIGINT, signal.SIGTERM)
        }
        assert signal.SIGINT in wired, "SIGINT handler not installed"
        assert signal.SIGTERM in wired, "SIGTERM handler not installed"
        assert wired[signal.SIGINT] == event_server._quit_signal_handler
        assert wired[signal.SIGTERM] == event_server._quit_signal_handler

    def test_stop_tolerates_unstarted_httpd_and_runs_hooks(self, srv, event_server):
        sentinel = MagicMock()
        sentinel.__name__ = "sentinel"
        srv.CommonServer.on_stop(sentinel)
        event_server.httpd = None  # start() never ran
        event_server.stop()  # must not AttributeError
        sentinel.assert_called_once()

    def test_run_runs_stop_even_when_start_raises(self, srv, event_server):
        # The try/finally in run() guarantees on_stop cleanup on the error
        # path too, not only the lucky one where serve_forever() returns.
        sentinel = MagicMock()
        sentinel.__name__ = "sentinel"
        srv.CommonServer.on_stop(sentinel)
        event_server.httpd = MagicMock()
        with patch.object(event_server, "start", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                event_server.run()
        sentinel.assert_called_once()
        # ``server_close`` (never ``shutdown``): serve_forever runs on the SAME
        # thread as stop(), so shutdown() would deadlock when the loop never
        # started — see ``test_stop_completes_if_serve_forever_never_started``.
        event_server.httpd.server_close.assert_called_once()
        event_server.httpd.shutdown.assert_not_called()

    def test_stop_completes_if_serve_forever_never_started(self, event_server):
        """Regression: ``stop()`` used ``shutdown()``, which waits forever on an
        event only ``serve_forever`` sets.  A signal in the window between
        ``make_server`` and ``serve_forever`` reached ``run``'s ``finally`` with
        the loop never started — and shutdown hung until kill -9.
        """
        event_server.httpd = werkzeug.serving.make_server(
            "127.0.0.1", 0, lambda e, s: [], threaded=True
        )
        try:
            done = threading.Event()
            threading.Thread(
                target=lambda: (event_server.stop(), done.set()), daemon=True
            ).start()
            assert done.wait(5), (
                "stop() hung on a never-started serve loop (shutdown deadlock)"
            )
        finally:
            event_server.httpd.server_close()  # idempotent; belt and suspenders

    def test_stop_after_completed_serve_loop_double_close_ok(self, event_server):
        """After a normal run werkzeug's ``serve_forever`` already closed the
        socket in its ``finally``; ``stop()``'s ``server_close`` must be a
        harmless no-op, not an error.
        """
        event_server.httpd = werkzeug.serving.make_server(
            "127.0.0.1", 0, lambda e, s: [], threaded=True
        )
        t = threading.Thread(target=event_server.httpd.serve_forever, daemon=True)
        t.start()
        event_server.httpd.shutdown()  # valid here: loop runs on ANOTHER thread
        t.join(5)
        assert not t.is_alive()
        event_server.stop()  # second close after werkzeug's — must not raise


# ---------------------------------------------------------------------------
# ThreadedServer.process_limit — real-time-limit log formatting
# ---------------------------------------------------------------------------


class TestProcessLimitRealTimeLog:
    """Regression: the overrun warning logged ``%d`` of a float duration,
    flooring it (a 12.7s overrun printed as ``12``), and mislabeled wall time
    as 'virtual real time'.  Pin ``%.1f`` and the corrected wording.
    """

    def test_overrun_logs_fractional_seconds(self, srv):
        ts = object.__new__(srv.ThreadedServer)
        ts.logger = MagicMock()
        ts.limits_reached_threads = set()
        ts.limit_reached_time = None
        ts._process_handle = MagicMock()

        fake_thread = MagicMock()
        fake_thread.type = "http"
        fake_thread.start_time = time.monotonic() - 12.7  # overran the 1s limit
        fake_thread.is_alive.return_value = True

        cfg = {
            "limit_memory_soft": 0,
            "limit_time_real": 1,
            "limit_time_real_cron": 0,
        }
        with (
            patch.object(_threaded, "config", cfg),
            patch.object(_helpers, "memory_info", return_value=0),
            patch.object(threading, "enumerate", return_value=[fake_thread]),
        ):
            ts.process_limit()

        ts.logger.warning.assert_called_once()
        fmt = ts.logger.warning.call_args.args[0]
        assert "%.1f" in fmt, "elapsed time must use %.1f (not %d, which floors)"
        assert "virtual" not in fmt, "wall time must not be mislabeled 'virtual'"
        rendered = fmt % ts.logger.warning.call_args.args[1:]
        assert "12.7" in rendered, f"fractional seconds must survive; got {rendered!r}"


# ---------------------------------------------------------------------------
# ThreadedWSGIServerReloadable — websocket upgrade releases the bounded slot
# ---------------------------------------------------------------------------


class _FakeConnection:
    """Weakref-able stand-in for a request socket (sockets support weakref)."""

    def shutdown(self, how):
        pass

    def close(self):
        pass


@pytest.fixture
def bounded_server(srv):
    """ThreadedWSGIServerReloadable with a 1-slot bound, no socket machinery.

    Bypasses ``__init__`` (which binds a listen socket) and populates only the
    semaphore-accounting state, mirroring the ``prefork_server`` fixture.
    """
    import weakref

    obj = object.__new__(srv.ThreadedWSGIServerReloadable)
    obj.max_http_threads = 1
    obj.http_threads_sem = threading.Semaphore(1)
    obj._sem_released_requests = weakref.WeakSet()
    return obj


class TestHttpSlotReleaseOnWebsocketUpgrade:
    """Regression: a websocket connection parks its handler thread for the
    connection's lifetime while keeping its ``max_http_threads`` slot, so once
    every slot was held by an idle websocket the accept loop starved and no
    further request was ever accepted (one browser tab was enough to wedge the
    dev/test server when the bound computed to 1, e.g. ``--db_maxconn 5``).
    The upgrade handshake (101) must return the slot early, and the eventual
    ``shutdown_request`` for the same connection must not double-release.
    """

    def test_upgrade_releases_slot_early(self, bounded_server):
        conn = _FakeConnection()
        assert bounded_server.http_threads_sem.acquire(blocking=False)  # accept
        bounded_server.release_upgraded_request_slot(conn)
        assert bounded_server.http_threads_sem.acquire(blocking=False), (
            "the upgraded connection's slot must be free for the next request"
        )

    def test_shutdown_after_upgrade_does_not_double_release(self, bounded_server):
        conn = _FakeConnection()
        assert bounded_server.http_threads_sem.acquire(blocking=False)  # accept
        bounded_server.release_upgraded_request_slot(conn)
        bounded_server.shutdown_request(conn)  # websocket eventually closes
        assert bounded_server.http_threads_sem.acquire(blocking=False)
        assert not bounded_server.http_threads_sem.acquire(blocking=False), (
            "a double release would inflate the bound beyond max_http_threads"
        )

    def test_release_is_noop_without_bound(self, srv):
        # ``max_http_threads = 0`` opts out of the semaphore entirely — the
        # server then has no ``http_threads_sem`` and the release must not
        # AttributeError.
        obj = object.__new__(srv.ThreadedWSGIServerReloadable)
        obj.max_http_threads = 0
        obj.release_upgraded_request_slot(_FakeConnection())

    def test_send_response_101_triggers_release(self, srv):
        handler = object.__new__(srv.RequestHandler)
        handler.server = MagicMock()
        handler.request = _FakeConnection()
        with patch.object(http.server.BaseHTTPRequestHandler, "send_response"):
            handler.send_response(101)
        handler.server.release_upgraded_request_slot.assert_called_once_with(
            handler.request
        )

    def test_send_response_200_does_not_release(self, srv):
        handler = object.__new__(srv.RequestHandler)
        handler.server = MagicMock()
        handler.request = _FakeConnection()
        with patch.object(http.server.BaseHTTPRequestHandler, "send_response"):
            handler.send_response(200)
        handler.server.release_upgraded_request_slot.assert_not_called()

    def test_send_response_101_survives_server_without_semaphore(self, srv):
        # ``RequestHandler`` is only wired to ``ThreadedWSGIServerReloadable``,
        # but the handler must stay safe if reused on a server lacking the
        # release hook (guarded getattr).
        handler = object.__new__(srv.RequestHandler)
        handler.server = object()
        handler.request = _FakeConnection()
        with patch.object(http.server.BaseHTTPRequestHandler, "send_response"):
            handler.send_response(101)  # must not raise


# ---------------------------------------------------------------------------
# _cron.order_notified_first — cron/job scheduling order + de-duplication
# ---------------------------------------------------------------------------


class _StopHarness(BaseException):
    """Escape hatch to unwind ``_listen_thread``'s ``while True`` from a test."""


@pytest.fixture
def listen_server(srv, monkeypatch):
    """ThreadedServer stub sufficient to drive ``_listen_thread`` inline.

    ``_listen_thread`` stamps ``start_time`` on whichever thread runs it — the
    MainThread here — and ``ThreadedServer.process_limit`` reads that attribute
    to decide a thread has overrun its limit, so a leak makes every later reader
    see a permanently over-limit thread.  Three of the four classes driving this
    fixture cleared it in a ``teardown_method``; the fourth
    (``TestListenThreadUsesAMonotonicClock``) did not, and the leak was invisible
    because ``conftest``'s guard did not watch the name.  Owning it here covers
    every user by construction and replaces all three teardowns.
    """
    monkeypatch.setattr(threading.current_thread(), "start_time", None, raising=False)
    s = object.__new__(srv.ThreadedServer)
    s.logger = MagicMock()
    return s


def _drive_listen_thread(listen_server, process_jobs, *, sleeps_before_stop=2):
    """Run ``_listen_thread`` on THIS thread until it is unwound.

    Every blocking/IO edge is stubbed: the ``postgres`` connect, the LISTEN arm,
    the NOTIFY drain, the served-database list and the selector.  ``time.sleep``
    is counted and raises ``_StopHarness`` once ``sleeps_before_stop`` calls have
    been made, which unwinds the driver's otherwise-infinite outer loop.
    """
    calls = {"sleep": 0}

    def fake_sleep(_seconds):
        calls["sleep"] += 1
        if calls["sleep"] >= sleeps_before_stop:
            raise _StopHarness

    cfg = {"limit_time_worker_cron": 0, "db_name": ["db1"]}
    with (
        patch("odoo.service._threaded.db.db_connect"),
        patch("odoo.service._threaded.arm_cron_listen", return_value=True),
        patch("odoo.service._threaded.drain_cron_notifies", return_value=set()),
        patch(
            "odoo.service._threaded.cron_database_list", return_value=["db1"]
        ) as db_list,
        patch("odoo.service._threaded.selectors.DefaultSelector"),
        patch("odoo.service._threaded.config", cfg),
        patch("odoo.service._threaded.time.sleep", fake_sleep),
    ):
        with pytest.raises(_StopHarness):
            listen_server._listen_thread(
                0, channel="cron_trigger", process_jobs=process_jobs, label="cron"
            )
        # Recorded inside the ``with``: the mock is detached on exit.
        calls["full_scans"] = db_list.call_count
    return calls


class TestListenThreadUsesAMonotonicClock:
    """``_listen_thread`` must not schedule the full re-scan off the wall clock.

    Regression: ``check_all_time`` was compared against ``time.time()``.  An NTP
    correction or a manual clock change then re-triggers the scan — the branch
    that queries every served database — on every poll.

    Driven rather than read as source text.  The previous version asserted the
    exact expression ``"time.monotonic() - SLEEP_INTERVAL > check_all_time"``
    appeared in the source, so it failed on a behaviour-preserving reorder of
    the comparison and said nothing about what the loop does when the wall clock
    actually moves.
    """

    def test_a_wall_clock_jump_does_not_retrigger_the_full_scan(
        self, listen_server, monkeypatch
    ):
        """``time.time()`` leaps forward by ~11 days per call; monotonic
        advances by milliseconds.  Only the first pass may scan."""
        wall = iter(range(0, 10**9, 10**6))
        monkeypatch.setattr(time, "time", lambda: float(next(wall)))

        calls = _drive_listen_thread(
            listen_server, process_jobs=MagicMock(), sleeps_before_stop=4
        )

        assert calls["full_scans"] == 1, (
            f"the full scan ran {calls['full_scans']} times across "
            f"{calls['sleep']} polls; a wall-clock jump must not reschedule it "
            f"(SLEEP_INTERVAL is {_helpers.SLEEP_INTERVAL}s and monotonic "
            f"advanced by milliseconds)"
        )


class TestListenThreadStartTimeBookkeeping:
    """``_listen_thread`` must always clear ``thread.start_time`` after a unit of work.

    ``ThreadedServer.process_limit`` reads ``start_time`` on every ``cron``/``job``
    thread and flags any whose elapsed time exceeds ``limit_time_real_cron``.  A
    cron thread is long-lived and survives a failed pass (the driver backs off and
    retries), so a ``start_time`` left set by a failed unit of work is never
    cleared again: from the next ``process_limit`` tick onwards the thread looks
    permanently over-limit, which drives ``run()`` into a full server reload.
    """

    def test_start_time_cleared_after_successful_unit_of_work(self, listen_server):
        _drive_listen_thread(listen_server, MagicMock())
        assert getattr(threading.current_thread(), "start_time", None) is None

    def test_start_time_cleared_after_exception_in_unit_of_work(self, listen_server):
        def boom(_db):
            raise ValueError("cron job blew up")

        _drive_listen_thread(listen_server, boom)
        assert getattr(threading.current_thread(), "start_time", None) is None

    def test_start_time_cleared_when_base_exception_unwinds_the_thread(
        self, listen_server
    ):
        """A ``BaseException`` unwinds the driver — and still clears the stamp.

        The stamp is cleared by the ``finally`` around the unit of work, not by
        the outer handler catching everything: the driver deliberately catches
        ``Exception``, so a ``BaseException`` propagates and ends the thread
        (see :class:`TestListenThreadDoesNotSwallowUnwinds`).  The invariant
        still has to hold on that path, because ``process_limit`` keeps reading
        the stamp until the thread is actually gone.
        """

        class Fatal(BaseException):
            pass

        def boom(_db):
            raise Fatal("not an Exception subclass")

        with pytest.raises(Fatal):
            _drive_listen_thread(listen_server, boom, sleeps_before_stop=3)
        assert getattr(threading.current_thread(), "start_time", None) is None


class TestListenThreadDoesNotSwallowUnwinds:
    """The outer retry loop must not swallow exceptions raised to unwind it.

    The loop is ``while True`` with a backoff-and-retry handler, so whatever it
    catches it retries *forever*.  Catching ``BaseException`` there therefore
    turned every unwind signal into an infinite spin: ``KeyboardInterrupt`` was
    logged as an "uncaught error in cron main loop" and retried instead of
    stopping a threaded dev server, and a test's stop sentinel raised from
    inside the loop body could never unwind it — the loop span, logging a
    CRITICAL with a traceback every pass, until the process was OOM-killed.

    So the handler catches ``Exception``: a fault in a cron pass is retried, a
    ``BaseException`` means "stop this thread" and is honoured.
    """

    @pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
    def test_control_flow_exception_is_not_retried(self, listen_server, exc):
        def boom(_db):
            raise exc

        # If the loop swallowed it, ``fake_sleep`` would unwind with
        # ``_StopHarness`` on the 3rd retry instead — a failure, not a hang.
        with pytest.raises(exc):
            _drive_listen_thread(listen_server, boom, sleeps_before_stop=3)

    def test_ordinary_exception_is_still_retried(self, listen_server):
        """The flip side: a real fault must NOT kill a long-lived cron thread."""

        def boom(_db):
            raise ValueError("cron pass blew up")

        # ``_drive_listen_thread`` asserts the ``_StopHarness`` unwind itself,
        # i.e. the loop stayed alive and got as far as the sleep counter.
        _drive_listen_thread(listen_server, boom, sleeps_before_stop=3)


# ---------------------------------------------------------------------------
# PreforkServer.stop() — the reload (phoenix) branch must not strand workers
# ---------------------------------------------------------------------------


class TestPreforkPhoenixStopTerminatesSurvivors:
    """A reload whose drain is cut short must still terminate surviving workers.

    ``stop_workers_gracefully`` breaks out early on "Forced shutdown." (a second
    INT/TERM arriving mid-drain).  The plain-shutdown branch of ``stop()`` covers
    that with a trailing SIGTERM sweep, but the phoenix branch returned straight
    after the drain.

    A survivor is NOT orphaned: this code runs in the ``fork_and_reload`` child,
    which is only a sibling of the workers — their parent is the original master
    pid, which ``_reexec``'d in place and is now the new master.  The survivor is
    therefore silently adopted by a new master that has no record of it, and goes
    on accepting from the shared inherited listen socket while running the OLD
    code, on top of the full fresh population the new master spawns.  (Verified
    against a live reload: master 3104723 re-exec'd in place, drain ran in child
    3105277, and both old and new workers had ppid 3104723.)
    """

    @pytest.fixture
    def phoenix_server(self, prefork_server):
        prefork_server.socket = None
        # A worker the (stubbed) drain fails to reap, as after a forced break.
        prefork_server.workers = {4242: MagicMock()}
        # Still alive at sweep time (not a recycled pid), so it must be signalled.
        prefork_server._drain_procs = {4242: MagicMock(is_running=lambda: True)}
        return prefork_server

    def test_survivor_is_sigtermed_after_cut_short_reload_drain(
        self, srv, phoenix_server, monkeypatch
    ):
        from odoo.service import lifecycle

        monkeypatch.setattr(lifecycle, "server_phoenix", True)
        monkeypatch.setattr(srv.PreforkServer, "fork_and_reload", lambda self: True)
        # Simulate the "Forced shutdown." break: returns with workers still there.
        monkeypatch.setattr(
            srv.PreforkServer, "stop_workers_gracefully", lambda self: None
        )
        killed = []
        monkeypatch.setattr(
            srv.PreforkServer,
            "worker_kill",
            lambda self, pid, sig: killed.append((pid, sig)),
        )

        phoenix_server.stop()

        assert killed == [(4242, signal.SIGTERM)], (
            "worker 4242 was left running after a cut-short reload drain"
        )

    def test_fully_drained_reload_kills_nothing(self, srv, phoenix_server, monkeypatch):
        """The sweep is a no-op on the normal path, where the drain reaped everyone."""
        from odoo.service import lifecycle

        monkeypatch.setattr(lifecycle, "server_phoenix", True)
        monkeypatch.setattr(srv.PreforkServer, "fork_and_reload", lambda self: True)

        def drained(self):
            self.workers.clear()

        monkeypatch.setattr(srv.PreforkServer, "stop_workers_gracefully", drained)
        killed = []
        monkeypatch.setattr(
            srv.PreforkServer,
            "worker_kill",
            lambda self, pid, sig: killed.append((pid, sig)),
        )

        phoenix_server.stop()

        assert killed == []


class TestPreforkPhoenixStopRunsOnStopHooks:
    """A reload must still run ``CommonServer.on_stop`` hooks.

    ``PreforkServer.stop()``'s phoenix branch returned on both of its exit paths
    *before* reaching ``super().stop()``, which is the only thing that runs
    ``_ON_STOP_FUNCS``. So under ``--workers>0`` a SIGHUP reload skipped every
    registered shutdown hook, while a threaded server (``ThreadedServer.stop``)
    ran them unconditionally — a silent, mode-dependent divergence.

    What the hooks actually do makes this a resource leak rather than a
    cosmetic gap: every registered one closes a **process-local** resource --
    ``close_sass_compiler`` and ``close_lexer_worker`` terminate spawned
    subprocesses, and ``bus`` stops its dispatcher thread and closes its
    PostgreSQL notify connection. The outgoing master is exiting either way; not
    running them orphans whatever it had spawned, once per reload.

    Both exit paths are covered, because the failed-reload path also ends with
    "this (old) master is exiting".
    """

    @pytest.fixture
    def hooked(self, srv, monkeypatch):
        """Register a sentinel hook, isolated from the process-wide list."""
        from odoo.service import _base_server

        calls = []
        monkeypatch.setattr(_base_server, "_ON_STOP_FUNCS", [lambda: calls.append(1)])
        return calls

    def _phoenix(self, prefork_server):
        prefork_server.socket = None
        prefork_server.workers = {}
        prefork_server._drain_procs = {}
        return prefork_server

    def test_successful_reload_runs_the_hooks(
        self, srv, prefork_server, hooked, monkeypatch
    ):
        from odoo.service import lifecycle

        monkeypatch.setattr(lifecycle, "server_phoenix", True)
        monkeypatch.setattr(srv.PreforkServer, "fork_and_reload", lambda self: True)
        monkeypatch.setattr(
            srv.PreforkServer, "stop_workers_gracefully", lambda self: None
        )

        self._phoenix(prefork_server).stop()

        assert hooked == [1], (
            "on_stop hooks did not run on a prefork reload; the outgoing master "
            "exits leaving its subprocesses and bus connection behind"
        )

    def test_failed_reload_also_runs_the_hooks(
        self, srv, prefork_server, hooked, monkeypatch
    ):
        """The old master says it is exiting on this path too."""
        from odoo.service import lifecycle

        monkeypatch.setattr(lifecycle, "server_phoenix", True)
        monkeypatch.setattr(srv.PreforkServer, "fork_and_reload", lambda self: False)

        self._phoenix(prefork_server).stop()

        assert hooked == [1]

    def test_plain_shutdown_still_runs_them_once(
        self, srv, prefork_server, hooked, monkeypatch
    ):
        """The non-phoenix path already worked; it must not now run them twice."""
        from odoo.service import lifecycle

        monkeypatch.setattr(lifecycle, "server_phoenix", False)
        monkeypatch.setattr(
            srv.PreforkServer, "stop_workers_gracefully", lambda self: None
        )
        prefork_server.socket = None

        prefork_server.stop()

        assert hooked == [1]


class TestListenThreadFirstPassIsImmediate:
    """The first cron pass must not wait out a full ``SLEEP_INTERVAL``.

    ``_listen_thread`` blocks on ``select()`` before it ever looks at the
    database.  With a 60 s timeout and nothing to select on at boot (no NOTIFY
    yet), a threaded server did no cron work at all for its first minute, even
    with jobs already overdue — measured at exactly 60 s on a live server.
    ``PreforkServer`` never had this: it caps its wait at half the cron watchdog.
    """

    def _select_timeouts(self, listen_server, iterations):
        seen = []

        class _Sel:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def register(self, *a, **kw):
                pass

            def select(self, timeout=None):
                seen.append(timeout)
                if len(seen) >= iterations:
                    raise _StopHarness
                return []

        cfg = {"limit_time_worker_cron": 0, "db_name": ["db1"]}
        with (
            patch("odoo.service._threaded.db.db_connect"),
            patch("odoo.service._threaded.arm_cron_listen", return_value=True),
            patch("odoo.service._threaded.drain_cron_notifies", return_value=set()),
            patch("odoo.service._threaded.cron_database_list", return_value=["db1"]),
            patch("odoo.service._threaded.selectors.DefaultSelector", _Sel),
            patch("odoo.service._threaded.config", cfg),
            patch("odoo.service._threaded.time.sleep", lambda _s: None),
        ):
            with pytest.raises(_StopHarness):
                listen_server._listen_thread(
                    0, channel="cron_trigger", process_jobs=MagicMock(), label="cron"
                )
        return seen

    def test_first_select_does_not_block(self, listen_server):
        assert self._select_timeouts(listen_server, 1)[0] == 0

    def test_subsequent_selects_use_the_steady_state_interval(self, listen_server):
        timeouts = self._select_timeouts(listen_server, 3)
        assert timeouts[0] == 0, "first pass must poll immediately"
        assert all(t == _threaded.SLEEP_INTERVAL + 0 for t in timeouts[1:]), (
            f"steady state must return to SLEEP_INTERVAL, got {timeouts}"
        )

    def test_first_pass_actually_processes_databases(self, listen_server):
        """Polling immediately is only useful if the pass does the work."""
        process_jobs = MagicMock()
        cfg = {"limit_time_worker_cron": 0, "db_name": ["db1"]}
        calls = {"n": 0}

        class _Sel:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def register(self, *a, **kw):
                pass

            def select(self, timeout=None):
                calls["n"] += 1
                if calls["n"] > 1:
                    raise _StopHarness
                return []

        with (
            patch("odoo.service._threaded.db.db_connect"),
            patch("odoo.service._threaded.arm_cron_listen", return_value=True),
            patch("odoo.service._threaded.drain_cron_notifies", return_value=set()),
            patch("odoo.service._threaded.cron_database_list", return_value=["db1"]),
            patch("odoo.service._threaded.selectors.DefaultSelector", _Sel),
            patch("odoo.service._threaded.config", cfg),
            patch("odoo.service._threaded.time.sleep", lambda _s: None),
        ):
            with pytest.raises(_StopHarness):
                listen_server._listen_thread(
                    0, channel="cron_trigger", process_jobs=process_jobs, label="cron"
                )
        process_jobs.assert_called_once_with("db1")


class TestPreforkForcefulStopStopsLongPolling:
    """``stop(graceful=False)`` must stop the evented subprocess too.

    It is not in ``self.workers`` (it is a ``Popen`` subprocess, not a forked
    worker), so the trailing SIGTERM sweep never reached it.  It did eventually
    die — its own watchdog kills it ~4 s after ``os.getppid()`` changes — but
    that is another component's polling covering for this path, and it leaves
    ``gevent_port`` bound meanwhile, long enough to fail a supervisor's
    immediate restart with EADDRINUSE.
    """

    def test_forceful_stop_stops_the_evented_child(
        self, srv, prefork_server, monkeypatch
    ):
        from odoo.service import lifecycle

        monkeypatch.setattr(lifecycle, "server_phoenix", False)
        prefork_server.socket = None
        prefork_server.workers = {}
        called = []
        monkeypatch.setattr(
            srv.PreforkServer, "_stop_long_polling", lambda self: called.append(True)
        )

        prefork_server.stop(graceful=False)

        assert called == [True], "evented subprocess left running after forceful stop"

    def test_graceful_stop_still_stops_it_exactly_once(
        self, srv, prefork_server, monkeypatch
    ):
        """The graceful path reaches it via ``stop_workers_gracefully``; adding
        the forceful call must not make it fire twice there."""
        from odoo.service import lifecycle

        monkeypatch.setattr(lifecycle, "server_phoenix", False)
        prefork_server.socket = None
        prefork_server.workers = {}
        called = []
        monkeypatch.setattr(
            srv.PreforkServer, "_stop_long_polling", lambda self: called.append(True)
        )
        monkeypatch.setattr(
            srv.PreforkServer,
            "stop_workers_gracefully",
            lambda self: self._stop_long_polling(),
        )
        monkeypatch.setattr(srv.CommonServer, "stop", lambda self: None)

        prefork_server.stop(graceful=True)

        assert called == [True]


class TestWorkerCpuLimitHandoff:
    """A SIGXCPU recycle unwinds ``run()``'s join, not the work thread.

    That daemon thread may still be inside ``select()`` on the selector — or,
    for ``WorkerCron``, mid-query on ``dbcursor`` — that ``stop()`` then closes.
    ``run()`` must ask it to wind down and give it a bounded moment first.
    """

    def test_grace_is_bounded_and_short(self, srv):
        assert 0 < srv.Worker._CPU_LIMIT_JOIN_GRACE_S <= 5.0

    def test_cpu_limit_clears_alive_and_joins_before_stop(self, srv, multi):
        w = srv.Worker(multi)
        w.pid = os.getpid()
        w.logger = MagicMock()
        order = []

        real_stop = srv.Worker.stop

        def traced_stop(self):
            order.append(("stop", self.alive))
            return real_stop(self)

        joined = []

        class _T:
            def start(self):
                pass

            def join(self, timeout=None):
                joined.append(timeout)
                if len(joined) == 1:
                    raise srv.CpuTimeLimitExceeded("cpu")
                order.append(("join", timeout))

            def is_alive(self):
                return False

        with (
            patch.object(srv.Worker, "start", lambda self: None),
            patch.object(srv.Worker, "stop", traced_stop),
            patch("odoo.service._worker.threading.Thread", lambda **kw: _T()),
            patch("odoo.service._worker.config", {"limit_time_cpu": 1}),
        ):
            w.run()

        assert ("join", srv.Worker._CPU_LIMIT_JOIN_GRACE_S) in order, (
            "work thread was not given a chance to wind down"
        )
        assert order.index(("join", srv.Worker._CPU_LIMIT_JOIN_GRACE_S)) < [
            o[0] for o in order
        ].index("stop"), "joined after stop() closed resources"
        assert ("stop", False) in order, "self.alive was not cleared before stop()"


# ---------------------------------------------------------------------------
# FSWatcherInotify: watches nested directories inside a subtree moved in
# ---------------------------------------------------------------------------
