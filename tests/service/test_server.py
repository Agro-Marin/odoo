"""Pure-pytest tests for ``odoo.service.server``.

Covers the mockable, process-local components of the service layer.
No live database, no process forking, and no Odoo module loading required.

NOT covered here (require live infra / fork):
  - PreforkServer.run() / worker_spawn() — fork-based, belong in integration tests
  - ThreadedServer.run() — requires a bound socket and real HTTP traffic
  - WorkerCron.start() / stop() — call real OS/psycopg setup

Run with::

    python -m pytest tests/service/ -v
"""

import errno
import http.server
import os
import signal
import threading
import time
from collections import deque
from io import BytesIO
from unittest.mock import MagicMock, patch

import psycopg
import pytest
import werkzeug.serving

from odoo.service import _base_server, _helpers, _prefork, _threaded

# ---------------------------------------------------------------------------
# Module-scope import (heavy import chain — paid once per session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def srv():
    """Return the ``odoo.service.server`` module, imported once per session."""
    import odoo.service.server as mod  # noqa: PLC0415

    return mod


# ---------------------------------------------------------------------------
# Infrastructure fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
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
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.fixture()
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


@pytest.fixture()
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
    obj.long_polling_spawn_time = 0.0
    # Fork-storm respawn-throttle state (consumed by process_zombie ->
    # _note_worker_exit and process_spawn).
    obj._consecutive_fast_deaths = 0
    obj._respawn_not_before = 0.0
    return obj


# ---------------------------------------------------------------------------
# empty_pipe()
# ---------------------------------------------------------------------------


class TestEmptyPipe:
    """``empty_pipe(fd)``: drains all bytes from a non-blocking readable fd."""

    def test_drains_all_data(self, srv):
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

    def test_already_empty_does_not_raise(self, srv):
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            _helpers.empty_pipe(r)  # no data written — must not block or raise
        finally:
            os.close(r)
            os.close(w)

    def test_drains_multiple_bytes(self, srv):
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


class TestFSWatcherBase:
    """``FSWatcherBase.handle_file(path)``: validates Python syntax, triggers reload."""

    @pytest.fixture()
    def watcher(self, srv):
        return srv.FSWatcherBase()

    def test_valid_py_triggers_restart(self, srv, watcher, tmp_path):
        py = tmp_path / "good.py"
        py.write_text("x = 1 + 1\n")
        # ``handle_file`` and ``_trigger_restart`` lazy-import
        # ``server_phoenix`` and ``restart`` from ``odoo.service.lifecycle``
        # (the single source of truth), so the patch must target that module.
        with (
            patch("odoo.service.lifecycle.server_phoenix", False),
            patch("odoo.service.lifecycle.restart") as mock_restart,
        ):
            result = watcher.handle_file(str(py))
        mock_restart.assert_called_once()
        assert result is True

    def test_syntax_error_suppresses_restart(self, srv, watcher, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def (\n")
        with patch.object(srv, "restart") as mock_restart:
            result = watcher.handle_file(str(bad))
        mock_restart.assert_not_called()
        assert result is None

    def test_missing_file_suppresses_restart(self, srv, watcher, tmp_path):
        """OSError (e.g. file deleted between discovery and read) must not crash."""
        with patch.object(srv, "restart") as mock_restart:
            result = watcher.handle_file(str(tmp_path / "ghost.py"))
        mock_restart.assert_not_called()
        assert result is None

    def test_non_py_file_is_ignored(self, srv, watcher, tmp_path):
        txt = tmp_path / "config.yaml"
        txt.write_text("key: value")
        with patch.object(srv, "restart") as mock_restart:
            result = watcher.handle_file(str(txt))
        mock_restart.assert_not_called()
        assert result is None

    def test_hidden_tilde_py_file_is_ignored(self, srv, watcher, tmp_path):
        """Files whose names start with ``.~`` are editor swap files; skip them."""
        hidden = tmp_path / ".~mymodule.py"
        hidden.write_text("pass\n")
        with patch.object(srv, "restart") as mock_restart:
            result = watcher.handle_file(str(hidden))
        mock_restart.assert_not_called()
        assert result is None

    def test_server_phoenix_skips_restart(self, srv, watcher, tmp_path):
        """When a reload is already in progress, do not trigger a second restart."""
        py = tmp_path / "ok.py"
        py.write_text("pass\n")
        with (
            patch("odoo.service.lifecycle.server_phoenix", True),
            patch("odoo.service.lifecycle.restart") as mock_restart,
        ):
            result = watcher.handle_file(str(py))
        mock_restart.assert_not_called()
        assert result is None


# ---------------------------------------------------------------------------
# PreforkServer.process_signals()
# ---------------------------------------------------------------------------


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
        from odoo.service import lifecycle  # noqa: PLC0415

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
# server_phoenix / server — single source of truth (lifecycle)
# ---------------------------------------------------------------------------


class TestServerPhoenixSingleSourceOfTruth:
    """``server`` and ``server_phoenix`` live only in ``lifecycle``.

    Regression: ``server.py`` used to expose them via a module ``__getattr__``
    forwarding to ``lifecycle``.  Because module ``__getattr__`` only fires for
    *absent* names, a single ``server.server_phoenix = X`` assignment created a
    real attribute that shadowed the forwarder permanently, silently desyncing
    later reads from ``lifecycle``.  The shim was removed; these tests pin that.
    """

    def test_lifecycle_is_the_canonical_holder(self):
        from odoo.service import lifecycle  # noqa: PLC0415

        assert hasattr(lifecycle, "server")
        assert hasattr(lifecycle, "server_phoenix")

    def test_server_module_does_not_forward_phoenix(self, srv):
        # No forwarding ``__getattr__`` -> the name is simply absent here, so a
        # stray ``server.server_phoenix = X`` can never masquerade as canonical.
        with pytest.raises(AttributeError):
            srv.server_phoenix  # noqa: B018

    def test_server_module_does_not_forward_server(self, srv):
        with pytest.raises(AttributeError):
            srv.server  # noqa: B018


# ---------------------------------------------------------------------------
# WorkerCron._connect_postgres()
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
            patch("odoo.service._worker.db.db_connect", return_value=conn) as mock_connect,
            patch("odoo.service._worker.selectors.DefaultSelector", return_value=MagicMock()),
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
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError("SSL")
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
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError("SSL")
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
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError("SSL")
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
        worker_cron.dbcursor.connection.notifies.side_effect = psycopg.OperationalError("SSL")
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
                side_effect=lambda s: current_cycle_sleeps.append(s),
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
                worker_cron, "_connect_postgres",
                side_effect=Exception("PG unreachable"),
            ),
            patch.object(
                worker_cron, "_sleep_with_watchdog", side_effect=stop_after_first,
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

    @pytest.fixture()
    def mock_ir_cron(self):
        """Stub the deferred ``IrCron`` import inside ``process_work()``."""
        mock_module = MagicMock()
        with patch.dict("sys.modules", {"odoo.addons.base.models.ir_cron": mock_module}):
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
            patch("odoo.service._worker.cron_database_list", return_value=["db1", "db2", "db3"]),
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

        all_dbs = list(worker_cron.db_queue) + [mock_ir_cron._process_jobs.call_args[0][0]]
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


def _worker_check_limits_patches(memory_bytes=0, config_override=None):
    """Return a list of context managers that stub all syscalls in check_limits."""
    cfg = {**_WORKER_CONFIG, **(config_override or {})}
    mock_resource = MagicMock()
    mock_resource.getrusage.return_value.ru_utime = 0.0
    mock_resource.getrusage.return_value.ru_stime = 0.0
    mock_resource.getrlimit.return_value = (0, 9999)
    mock_resource.RLIMIT_CPU = 0
    mock_resource.RUSAGE_SELF = 0
    return [
        # Worker.check_limits lives in odoo.service._worker after the extraction;
        # its ``config`` / ``resource`` references resolve against ``_worker``'s
        # namespace.  The RSS read goes through ``over_memory_soft_limit`` (also
        # imported into ``_worker``), which looks up ``memory_info`` in its
        # defining module ``_helpers`` — so that is where the stub belongs, and
        # patching it lets the real soft-limit threshold logic run.
        patch("odoo.service._worker.config", cfg),
        patch("odoo.service._helpers.memory_info", return_value=memory_bytes),
        patch("odoo.service._worker.resource", mock_resource),
    ], mock_resource


@pytest.fixture()
def bare_worker(srv, multi):
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
        patches, _ = _worker_check_limits_patches()
        with patches[0], patches[1], patches[2]:
            bare_worker.check_limits()
        assert bare_worker.alive is True

    def test_parent_changed_sets_alive_false(self, bare_worker):
        bare_worker.ppid = 99999  # deliberate mismatch with os.getppid()
        patches, _ = _worker_check_limits_patches()
        with patches[0], patches[1], patches[2]:
            bare_worker.check_limits()
        assert bare_worker.alive is False

    def test_request_max_reached_sets_alive_false(self, bare_worker):
        bare_worker.request_count = 100
        bare_worker.request_max = 100
        patches, _ = _worker_check_limits_patches()
        with patches[0], patches[1], patches[2]:
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
        patches, _ = _worker_check_limits_patches()
        with patches[0], patches[1], patches[2]:
            bare_worker.check_limits()
        assert bare_worker.alive is True

    def test_memory_soft_exceeded_sets_alive_false(self, bare_worker):
        patches, _ = _worker_check_limits_patches(
            memory_bytes=500,
            config_override={"limit_memory_soft": 100},
        )
        with patches[0], patches[1], patches[2]:
            bare_worker.check_limits()
        assert bare_worker.alive is False

    def test_cpu_rlimit_set_to_usage_plus_limit(self, bare_worker):
        """RLIMIT_CPU soft = current_cpu_time + limit_time_cpu."""
        patches, mock_resource = _worker_check_limits_patches(
            config_override={"limit_time_cpu": 30}
        )
        mock_resource.getrusage.return_value.ru_utime = 5.0
        mock_resource.getrusage.return_value.ru_stime = 3.0  # total = 8s
        mock_resource.getrlimit.return_value = (0, 9999)
        with patches[0], patches[1], patches[2]:
            bare_worker.check_limits()
        # int(8.0 + 30) = 38
        mock_resource.setrlimit.assert_called_once_with(0, (38, 9999))

    def test_cpu_rlimit_not_armed_when_disabled(self, bare_worker):
        """limit_time_cpu=0 must NOT arm RLIMIT_CPU.

        Arming it to ``int(cpu_already_consumed + 0)`` sets the soft limit at
        or below the CPU the worker has already used, so the kernel raises
        SIGXCPU immediately and the worker dies in a fork loop.  0 means
        "disabled", consistent with every other limit in this module.
        """
        patches, mock_resource = _worker_check_limits_patches(
            config_override={"limit_time_cpu": 0}
        )
        mock_resource.getrusage.return_value.ru_utime = 8.0
        mock_resource.getrusage.return_value.ru_stime = 0.0
        with patches[0], patches[1], patches[2]:
            bare_worker.check_limits()
        mock_resource.setrlimit.assert_not_called()
        assert bare_worker.alive is True

    def _resource_stub(self):
        mock_resource = MagicMock()
        mock_resource.getrusage.return_value.ru_utime = 0.0
        mock_resource.getrusage.return_value.ru_stime = 0.0
        mock_resource.getrlimit.return_value = (0, 9999)
        mock_resource.RLIMIT_CPU = 0
        mock_resource.RUSAGE_SELF = 0
        return mock_resource

    def test_rss_not_read_when_soft_limit_disabled(self, bare_worker):
        """The RSS ``/proc`` read is skipped entirely when ``limit_memory_soft``
        is 0 (disabled) — it was previously paid on every cycle for nothing."""
        mem = MagicMock(return_value=0)
        with patch("odoo.service._worker.config",
                   {"limit_memory_soft": 0, "limit_time_cpu": 60}), \
             patch("odoo.service._helpers.memory_info", mem), \
             patch("odoo.service._worker.resource", self._resource_stub()):
            bare_worker.check_limits()
        mem.assert_not_called()
        assert bare_worker.alive is True

    def test_rss_read_when_soft_limit_enabled(self, bare_worker):
        """With the soft limit set, RSS is read exactly once and a value under
        the limit keeps the worker alive."""
        mem = MagicMock(return_value=50)
        with patch("odoo.service._worker.config",
                   {"limit_memory_soft": 100, "limit_time_cpu": 60}), \
             patch("odoo.service._helpers.memory_info", mem), \
             patch("odoo.service._worker.resource", self._resource_stub()):
            bare_worker.check_limits()
        mem.assert_called_once()
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
        import functools  # noqa: PLC0415

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


class TestCronDatabaseList:
    """``cron_database_list()``: config override vs list_dbs fallback."""

    def test_returns_config_db_name_when_set(self, srv):
        with (
            patch("odoo.service._helpers.config", {"db_name": "mydb"}),
            patch("odoo.service._helpers.list_dbs") as mock_list,
        ):
            result = _helpers.cron_database_list()
        assert result == "mydb"
        mock_list.assert_not_called()

    def test_falls_back_to_list_dbs_when_empty(self, srv):
        with (
            patch("odoo.service._helpers.config", {"db_name": None}),
            patch("odoo.service._helpers.list_dbs", return_value=["db1", "db2"]) as mock_list,
        ):
            result = _helpers.cron_database_list()
        mock_list.assert_called_once_with(True)
        assert result == ["db1", "db2"]


# ---------------------------------------------------------------------------
# PreforkServer.process_zombie()
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
# PreforkServer respawn throttle (fork-storm guard)
# ---------------------------------------------------------------------------


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
        result = prefork_server.worker_spawn(klass, {})
        assert result is None
        fake_worker.close.assert_called_once()
        assert prefork_server.workers == {}

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
        # Must not raise.
        prefork_server.long_polling_spawn()
        assert prefork_server.long_polling_pid is None


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
            _prefork._graceful_stop_timeout(logger)
            == _prefork.GRACEFUL_STOP_TIMEOUT_S
        )
        monkeypatch.delenv("ODOO_GRACEFUL_STOP_TIMEOUT")
        assert (
            _prefork._graceful_stop_timeout(logger)
            == _prefork.GRACEFUL_STOP_TIMEOUT_S
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
        with patch.object(_prefork, "config", cfg), \
             patch.object(_base_server, "config", cfg):
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


@pytest.fixture()
def log_handler(srv):
    """Minimal CommonRequestHandler for log_request / log_error tests."""
    import threading  # noqa: PLC0415

    h = object.__new__(srv.CommonRequestHandler)
    h.path = "/web/test"
    h.command = "GET"
    h.request_version = "HTTP/1.1"
    h.requestline = "GET /web/test HTTP/1.1"
    h.log = MagicMock()
    threading.current_thread().rpc_model_method = ""
    return h


class TestCommonRequestHandlerLogError:
    """``log_error()``: timeout errors are downgraded; others delegate to super."""

    def test_timeout_logs_at_debug(self, srv, log_handler):
        with patch("odoo.service.wsgi._logger") as mock_logger:
            log_handler.log_error("Request timed out: %r", "socket")
        mock_logger.debug.assert_called_once()

    def test_other_error_calls_super(self, srv, log_handler):
        with (
            patch("odoo.service.wsgi._logger"),
            patch.object(werkzeug.serving.WSGIRequestHandler, "log_error") as mock_super,
        ):
            log_handler.log_error("Some other error: %s", "detail")
        mock_super.assert_called_once()


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

    def test_bad_requestline_falls_back_to_requestline(self, srv):
        """AttributeError on ``self.path`` (malformed request) must not raise."""
        import threading  # noqa: PLC0415

        h = object.__new__(srv.CommonRequestHandler)
        # Intentionally do NOT set h.path → AttributeError in the try block
        h.requestline = "GARBAGE_LINE"
        h.log = MagicMock()
        threading.current_thread().rpc_model_method = ""
        h.log_request(200, 0)
        logged_msg = str(h.log.call_args)
        assert "GARBAGE_LINE" in logged_msg


# ---------------------------------------------------------------------------
# RequestHandler.send_header() / end_headers() — WebSocket guards
# ---------------------------------------------------------------------------


@pytest.fixture()
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
        with patch.object(http.server.BaseHTTPRequestHandler, "send_header") as mock_send:
            request_handler.send_header("Connection", "close")
        mock_send.assert_not_called()
        assert request_handler.close_connection is True

    def test_non_websocket_connection_close_forwarded(self, request_handler):
        request_handler.headers.get.return_value = None
        with patch.object(http.server.BaseHTTPRequestHandler, "send_header") as mock_send:
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


# ---------------------------------------------------------------------------
# ThreadedWSGIServerReloadable — semaphore throttle
# ---------------------------------------------------------------------------


@pytest.fixture()
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


class TestThreadedWSGIServerSemaphore:
    """Concurrent connection throttle via ``max_http_threads`` semaphore."""

    def test_semaphore_full_skips_processing(self, threaded_server):
        threaded_server.http_threads_sem.acquire.return_value = False
        with patch.object(werkzeug.serving.ThreadedWSGIServer, "_handle_request_noblock") as mock_super:
            threaded_server._handle_request_noblock()
        mock_super.assert_not_called()

    def test_semaphore_acquired_calls_super(self, threaded_server):
        threaded_server.http_threads_sem.acquire.return_value = True
        with patch.object(werkzeug.serving.ThreadedWSGIServer, "_handle_request_noblock") as mock_super:
            threaded_server._handle_request_noblock()
        mock_super.assert_called_once()

    def test_no_semaphore_calls_super_directly(self, threaded_server):
        threaded_server.max_http_threads = None
        with patch.object(werkzeug.serving.ThreadedWSGIServer, "_handle_request_noblock") as mock_super:
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
# service/common.py — dispatch() and exp_version()
# ---------------------------------------------------------------------------


class TestServiceCommon:
    """``odoo.service.common``: RPC dispatch table and version endpoint."""

    @staticmethod
    @pytest.fixture(scope="class")
    def common():
        import odoo.service.common as mod  # noqa: PLC0415

        return mod

    def test_exp_version_has_required_keys(self, common):
        result = common.exp_version()
        assert "server_version" in result
        assert "server_version_info" in result
        assert "server_serie" in result
        assert result["protocol_version"] == 1

    def test_dispatch_version(self, common):
        result = common.dispatch("version", [])
        assert result["protocol_version"] == 1

    def test_dispatch_unknown_method_raises(self, common):
        with pytest.raises(Exception, match="Method not found"):
            common.dispatch("nonexistent_method", [])


# ---------------------------------------------------------------------------
# service/db.py — check_db_management_enabled / check_super
# ---------------------------------------------------------------------------


class TestServiceDb:
    """``odoo.service.db``: admin gate decorators."""

    @staticmethod
    @pytest.fixture(scope="class")
    def db_mod():
        import odoo.service.db as mod  # noqa: PLC0415

        return mod

    def test_check_super_correct_password_returns_true(self, db_mod):
        import odoo.tools  # noqa: PLC0415

        with patch.object(odoo.tools.config, "verify_admin_password", return_value=True):
            assert db_mod.check_super("correct") is True

    def test_check_super_wrong_password_raises(self, db_mod):
        import odoo.tools  # noqa: PLC0415
        from odoo.exceptions import AccessDenied  # noqa: PLC0415

        with patch.object(odoo.tools.config, "verify_admin_password", return_value=False):
            with pytest.raises(AccessDenied):
                db_mod.check_super("wrong")

    def test_check_super_empty_string_raises(self, db_mod):
        from odoo.exceptions import AccessDenied  # noqa: PLC0415

        with pytest.raises(AccessDenied):
            db_mod.check_super("")

    def test_db_management_blocked_when_list_db_false(self, db_mod):
        import odoo.tools  # noqa: PLC0415
        from odoo.exceptions import AccessDenied  # noqa: PLC0415

        @db_mod.check_db_management_enabled
        def _op():
            return "ok"

        # Patching __getitem__ on an instance doesn't work for special methods —
        # Python looks them up on the class.  Replace the object with a plain dict.
        with patch.object(odoo.tools, "config", {"list_db": False}):
            with pytest.raises(AccessDenied):
                _op()

    def test_db_management_passes_when_list_db_true(self, db_mod):
        import odoo.tools  # noqa: PLC0415

        @db_mod.check_db_management_enabled
        def _op():
            return "ok"

        with patch.object(odoo.tools, "config", {"list_db": True}):
            assert _op() == "ok"


# ---------------------------------------------------------------------------
# ThreadedServer.process_limit()
# ---------------------------------------------------------------------------


@pytest.fixture()
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

    def _base_patches(self, memory=0, config_override=None):
        cfg = {
            "limit_memory_soft": 0,
            "limit_time_real": 60,
            "limit_time_real_cron": 0,
            **(config_override or {}),
        }
        return [
            patch("odoo.service._helpers.memory_info", return_value=memory),
            patch("odoo.service._threaded.config", cfg),
            patch("odoo.service._threaded.psutil"),
        ]

    def test_memory_soft_exceeded_adds_current_thread(self, tserver):
        patches = self._base_patches(memory=2000, config_override={"limit_memory_soft": 1000})
        with patches[0], patches[1], patches[2], patch("threading.enumerate", return_value=[]):
            tserver.process_limit()
        import threading  # noqa: PLC0415
        assert threading.current_thread() in tserver.limits_reached_threads

    def test_thread_real_time_exceeded_adds_thread(self, tserver):
        mock_thread = MagicMock()
        mock_thread.daemon = False
        mock_thread.type = "http"
        mock_thread.start_time = time.monotonic() - 9999
        mock_thread.is_alive.return_value = True

        patches = self._base_patches(config_override={"limit_time_real": 60})
        with patches[0], patches[1], patches[2], patch("threading.enumerate", return_value=[mock_thread]):
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

        patches = self._base_patches(config_override={"limit_time_real": 3600, "limit_time_real_cron": 60})
        with patches[0], patches[1], patches[2], patch("threading.enumerate", return_value=[mock_thread]):
            tserver.process_limit()
        assert mock_thread in tserver.limits_reached_threads

    def test_dead_thread_pruned_from_limits_reached(self, tserver):
        dead = MagicMock()
        dead.is_alive.return_value = False
        tserver.limits_reached_threads.add(dead)

        patches = self._base_patches()
        with patches[0], patches[1], patches[2], patch("threading.enumerate", return_value=[]):
            tserver.process_limit()
        assert dead not in tserver.limits_reached_threads

    def test_limit_reached_time_set_and_cleared(self, tserver):
        """``limit_reached_time`` is set when threads exceed limits, cleared when all clear."""
        mock_thread = MagicMock()
        mock_thread.daemon = False
        mock_thread.type = "http"
        mock_thread.start_time = time.monotonic() - 9999
        mock_thread.is_alive.return_value = True

        patches = self._base_patches(config_override={"limit_time_real": 60})
        with patches[0], patches[1], patches[2], patch("threading.enumerate", return_value=[mock_thread]):
            tserver.process_limit()
        assert tserver.limit_reached_time is not None

        # remove the offending thread and run again — time should clear
        tserver.limits_reached_threads.clear()
        mock_thread.start_time = None  # no longer over limit
        with patches[0], patches[1], patches[2], patch("threading.enumerate", return_value=[mock_thread]):
            tserver.process_limit()
        assert tserver.limit_reached_time is None

    def test_websocket_thread_not_counted(self, tserver):
        """WebSocket threads are never subject to real-time limits."""
        mock_thread = MagicMock()
        mock_thread.daemon = False
        mock_thread.type = "websocket"
        mock_thread.start_time = time.monotonic() - 9999  # way over any limit
        mock_thread.is_alive.return_value = True

        patches = self._base_patches(config_override={"limit_time_real": 1})
        with patches[0], patches[1], patches[2], patch("threading.enumerate", return_value=[mock_thread]):
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

        patches = self._base_patches(config_override={"limit_time_real": 1})
        call_count = 0
        original_monotonic = time.monotonic

        def counting_monotonic():
            nonlocal call_count
            call_count += 1
            return original_monotonic()

        with patches[0], patches[1], patches[2], \
             patch("threading.enumerate", return_value=threads), \
             patch("odoo.service._threaded.time") as mock_time:
            mock_time.monotonic.side_effect = counting_monotonic
            tserver.process_limit()

        # One call for the loop snapshot + one call for limit_reached_time = 2 max.
        # Before the fix this would be len(threads) + 1 = 6.
        assert mock_time.monotonic.call_count <= 2


# ---------------------------------------------------------------------------
# Socket activation: IPv6 family detection
# ---------------------------------------------------------------------------


class TestSocketActivationIPv6:
    """The systemd socket-activation path must not lose the IPv6 family.

    Regression: replacing ``socket.fromfd(fd, AF_INET, SOCK_STREAM)`` with
    ``socket.socket(fileno=fd)`` — the latter auto-detects the kernel-assigned
    family via SO_DOMAIN, so an IPv6 listener stays AF_INET6 across wrapping.

    Before the fix: ``getsockname()`` and ``accept()`` returned ``sockaddr_in``
    structs unpacked from ``sockaddr_in6`` memory, producing garbage addresses
    like ``('::900:0:0:0', port, 0, <random>)`` and corrupting every access
    log line from an IPv6 client.
    """

    def test_wrapped_ipv6_socket_preserves_family(self):
        import socket

        real = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        real.bind(("::1", 0))
        real.listen(1)
        try:
            # The call used by server.py:297 and server.py:1182 after the fix.
            wrapped = socket.socket(fileno=real.fileno())
            try:
                assert wrapped.family == socket.AF_INET6
                # getsockname() must return a valid v6 loopback address —
                # the IPv4-misinterpretation sentinel '::900:0:0:0' must NOT
                # appear, and the scope_id slot must be 0 (not random bytes).
                bound = wrapped.getsockname()
                assert bound[0] == "::1"
                assert bound[3] == 0
            finally:
                wrapped.detach()
        finally:
            real.close()

    def test_wrapped_ipv4_socket_still_works(self):
        """The fix must not regress the common IPv4 path."""
        import socket

        real = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        real.bind(("127.0.0.1", 0))
        real.listen(1)
        try:
            wrapped = socket.socket(fileno=real.fileno())
            try:
                assert wrapped.family == socket.AF_INET
                assert wrapped.getsockname()[0] == "127.0.0.1"
            finally:
                wrapped.detach()
        finally:
            real.close()


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
            patch.object(time, "monotonic", side_effect=[0.0, 0.1, 0.2]),
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

        # Drive the monotonic clock past the 60-second budget immediately.
        # The while loop exits on the first check since now > reload_timeout.
        times = iter([0.0, 70.0, 70.1, 70.2, 70.3])

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
        import odoo  # noqa: PLC0415
        from odoo.service import lifecycle  # noqa: PLC0415

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
        # The Windows branch spawns a Thread targeting _reexec; assert
        # neither raised and the indirection is the one we expect.
        mock_thread.assert_called_once()
        kwargs = mock_thread.call_args.kwargs
        assert kwargs.get("target") is mock_reexec or mock_thread.call_args.args
        mock_thread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# ThreadedServer SIGCHLD no-op handler removed
# ---------------------------------------------------------------------------


class TestThreadedServerSignalSetup:
    """``ThreadedServer.start()`` does NOT install SIGCHLD.

    Regression: a handler was registered but had no code branch for SIGCHLD,
    causing spurious wakeups of the main loop whenever a subprocess (pg_dump,
    etc.) exited. ThreadedServer does not fork worker children, so reaping
    is handled by subprocess.run's internal waitpid.
    """

    def test_threaded_server_does_not_install_sigchld(self, srv):
        """Regression guard: no ``signal.signal(signal.SIGCHLD, ...)`` call.

        AST-based: comments referring to SIGCHLD in the source are fine.
        Only an actual ``signal.signal(SIGCHLD, ...)`` call is a regression.
        """
        import ast  # noqa: PLC0415
        import inspect  # noqa: PLC0415
        import textwrap  # noqa: PLC0415

        src = textwrap.dedent(inspect.getsource(srv.ThreadedServer.start))
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Match signal.signal(signal.SIGCHLD, ...) — attribute chain
            func = node.func
            if (isinstance(func, ast.Attribute)
                    and func.attr == "signal"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "signal"
                    and node.args):
                first = node.args[0]
                if (isinstance(first, ast.Attribute)
                        and first.attr == "SIGCHLD"):
                    pytest.fail(
                        "ThreadedServer.start() re-installed a SIGCHLD handler; "
                        "removing it eliminates spurious main-loop wakeups."
                    )


# ---------------------------------------------------------------------------
# cron_thread uses monotonic clock for scheduling
# ---------------------------------------------------------------------------


class TestCronThreadMonotonic:
    """``ThreadedServer._listen_thread`` (the shared cron/job worker loop)
    must not mix ``time.time()`` and ``time.monotonic()`` for the same
    scheduling decision.

    Regression: ``check_all_time`` was compared to ``time.time()`` (wall
    clock). An NTP slew or manual clock correction would mis-schedule the
    full-scan pass.
    """

    def test_listen_thread_uses_monotonic_for_check_all_time(self, srv):
        import inspect  # noqa: PLC0415

        src = inspect.getsource(srv.ThreadedServer._listen_thread)
        # The scheduling comparison must use monotonic, not wall clock.
        # Substring check is sufficient because the relevant line is unique.
        assert "time.time() - SLEEP_INTERVAL > check_all_time" not in src, (
            "Regression: _listen_thread back to time.time() for scheduling"
        )
        assert "time.monotonic() - SLEEP_INTERVAL > check_all_time" in src


# ---------------------------------------------------------------------------
# _ON_STOP_FUNCS module-level + backward-compatible class alias
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
        import os  # noqa: PLC0415

        if os.name == "posix":
            assert srv._SIGHUP_AVAILABLE is True

    def test_threaded_server_handler_guards_sighup(self, srv):
        """ThreadedServer.signal_handler reaches the SIGHUP branch through the
        sentinel, not an unconditional attribute access on ``signal``.
        """
        import ast  # noqa: PLC0415
        import inspect  # noqa: PLC0415
        import textwrap  # noqa: PLC0415

        src = textwrap.dedent(inspect.getsource(srv.ThreadedServer.signal_handler))
        tree = ast.parse(src)

        # Walk the `elif` chain — the SIGHUP branch must be inside a test
        # that references `_SIGHUP_AVAILABLE`.
        found_guarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test_src = ast.unparse(node.test)
            if "_SIGHUP_AVAILABLE" in test_src and "SIGHUP" in test_src:
                found_guarded = True
                break
        assert found_guarded, (
            "signal_handler must guard the SIGHUP check with _SIGHUP_AVAILABLE "
            "so Windows doesn't AttributeError on `signal.SIGHUP`."
        )


# ---------------------------------------------------------------------------
# Params.__str__ — deterministic log output
# ---------------------------------------------------------------------------


class TestParamsStr:
    """``Params.__str__`` sorts kwargs (for stable logs) and preserves args
    order (positional semantics)."""

    def test_args_preserve_order(self):
        from odoo.service.model import Params  # noqa: PLC0415

        # args in reversed alphabetical order must remain reversed
        p = Params(["z", "a", "m"], {})
        assert str(p) == "'z', 'a', 'm'"

    def test_kwargs_sorted_alphabetically(self):
        from odoo.service.model import Params  # noqa: PLC0415

        p = Params([], {"z_last": 1, "a_first": 2, "m_middle": 3})
        assert str(p) == "a_first=2, m_middle=3, z_last=1"

    def test_mixed_args_and_kwargs(self):
        from odoo.service.model import Params  # noqa: PLC0415

        p = Params(["first", "second"], {"z": 1, "a": 2})
        assert str(p) == "'first', 'second', a=2, z=1"

    def test_deterministic_across_dict_orderings(self):
        from odoo.service.model import Params  # noqa: PLC0415

        # Python dicts preserve insertion order — build two dicts with
        # the same keys in different orders and verify the stringification
        # is identical.
        p1 = Params([], dict.fromkeys(["x", "y", "z"], 0))
        p2 = Params([], dict.fromkeys(["z", "x", "y"], 0))
        assert str(p1) == str(p2)


# ---------------------------------------------------------------------------
# stop_workers_gracefully — dict-mutation race regression
# ---------------------------------------------------------------------------


class TestStopWorkersGracefullyDictRace:
    """``stop_workers_gracefully`` iterates ``self.workers`` while
    ``worker_kill`` may pop entries (on ESRCH for an already-dead worker).
    The fix snapshots the keys with ``list(...)`` to avoid
    ``RuntimeError: dictionary changed size during iteration``.

    Regression: this race only fires under load (an HTTP worker dying right
    when graceful shutdown begins), so the pure-pytest test exercises the
    pattern in isolation rather than relying on a live prefork server.
    """

    def test_pop_during_iteration_does_not_raise(self, srv, prefork_server):
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
        with patch.object(prefork_server, "process_signals", side_effect=KeyboardInterrupt), \
             patch.object(prefork_server, "process_zombie"), \
             patch.object(prefork_server, "sleep"), \
             patch.object(prefork_server, "process_timeout"):
            # Must NOT raise "dictionary changed size during iteration"
            prefork_server.stop_workers_gracefully()

        # Confirm the popped entry is actually gone
        assert 2 not in prefork_server.workers

    def test_uses_list_snapshot_pattern(self, srv):
        """Pin the implementation: ``stop_workers_gracefully`` must use
        ``list(self.workers)``, not ``self.workers`` directly, in its kill loop.

        A future refactor that drops the ``list(...)`` reintroduces the
        crash under load.
        """
        import inspect  # noqa: PLC0415

        src = inspect.getsource(srv.PreforkServer.stop_workers_gracefully)
        # Find the SIGINT-kill loop specifically
        assert "for pid in list(self.workers)" in src, (
            "stop_workers_gracefully must snapshot self.workers via list() "
            "before iterating; raw 'for pid in self.workers' raises RuntimeError "
            "when worker_kill pops a dead worker mid-loop."
        )


# ---------------------------------------------------------------------------
# memory_info log strings — RSS not VMS
# ---------------------------------------------------------------------------


class TestMemoryLogStrings:
    """``memory_info`` returns RSS (resident memory).  Log strings must say
    so — operators chasing 'virtual memory' issues will look at the wrong
    metric otherwise.
    """

    def test_worker_check_limits_says_RSS_not_virtual(self, srv):
        import inspect  # noqa: PLC0415

        src = inspect.getsource(srv.Worker.check_limits)
        assert "RSS" in src, "Worker.check_limits log message must say 'RSS'"
        assert "Virtual memory" not in src, (
            "Worker.check_limits still uses misleading 'Virtual memory' label"
        )

    def test_event_server_process_limits_says_RSS_not_virtual(self, srv):
        import inspect  # noqa: PLC0415

        src = inspect.getsource(srv.EventServer.process_limits)
        assert "RSS" in src, "EventServer.process_limits log message must say 'RSS'"
        assert "Virtual memory" not in src, (
            "EventServer.process_limits still uses misleading 'Virtual memory' label"
        )

    def test_memory_info_returns_rss(self, srv):
        """Belt-and-suspenders: confirm the helper actually returns RSS."""
        import psutil  # noqa: PLC0415
        proc = psutil.Process(os.getpid())
        info = proc.memory_info()
        assert _helpers.memory_info(proc) == info.rss
        # And explicitly NOT vms
        assert _helpers.memory_info(proc) != info.vms or info.vms == info.rss


# ---------------------------------------------------------------------------
# EventServer — SIGTERM graceful shutdown (on_stop hooks must run)
# ---------------------------------------------------------------------------


@pytest.fixture()
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
    def test_start_installs_sigint_and_sigterm(self, srv, event_server):
        with patch.object(signal, "signal") as mock_signal, \
             patch.object(werkzeug.serving, "make_server",
                          return_value=MagicMock()), \
             patch.object(threading, "Thread"):
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
        event_server.httpd.shutdown.assert_called_once()


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
        with patch.object(_threaded, "config", cfg), \
             patch.object(_helpers, "memory_info", return_value=0), \
             patch.object(threading, "enumerate", return_value=[fake_thread]):
            ts.process_limit()

        ts.logger.warning.assert_called_once()
        fmt = ts.logger.warning.call_args.args[0]
        assert "%.1f" in fmt, "elapsed time must use %.1f (not %d, which floors)"
        assert "virtual" not in fmt, "wall time must not be mislabeled 'virtual'"
        rendered = fmt % ts.logger.warning.call_args.args[1:]
        assert "12.7" in rendered, f"fractional seconds must survive; got {rendered!r}"
