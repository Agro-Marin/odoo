"""Pure-pytest tests for ``odoo.service.server``.

Covers the mockable, process-local components of the service layer.
No live database, no process forking, and no Odoo module loading required.

NOT covered here (require live infra / fork):
  - PreforkServer.run() / worker_spawn() — fork-based, belong in integration tests
  - ThreadedServer.run() — requires a bound socket and real HTTP traffic
  - WorkerCron.start() / stop() — call real OS/psycopg setup

Run with::

    python -m pytest core/tests/service/ -v
"""

import errno
import http.server
import os
import signal
import time
from collections import deque
from io import BytesIO
from unittest.mock import MagicMock, patch, patch as _patch

import psycopg
import pytest
import werkzeug.serving


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
    """WorkerCron with ``pid`` and ``dbcursor`` pre-set, ready for unit testing."""
    wc = srv.WorkerCron(multi)
    wc.pid = os.getpid()
    wc.dbcursor = MagicMock()
    wc.dbcursor._cnx = MagicMock()
    return wc


@pytest.fixture()
def prefork_server(srv):
    """PreforkServer instance that bypasses ``__init__`` (which reads config/sockets).

    Only the attributes consumed by the tested methods are populated.
    """
    obj = object.__new__(srv.PreforkServer)
    obj.queue = deque()
    obj.population = 4
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
            srv.empty_pipe(r)
            with pytest.raises(BlockingIOError):
                os.read(r, 1)  # pipe must be empty
        finally:
            os.close(r)
            os.close(w)

    def test_already_empty_does_not_raise(self, srv):
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            srv.empty_pipe(r)  # no data written — must not block or raise
        finally:
            os.close(r)
            os.close(w)

    def test_drains_multiple_bytes(self, srv):
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            os.write(w, b"a" * 512)
            srv.empty_pipe(r)
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
        with (
            patch.object(srv, "server_phoenix", False),
            patch.object(srv, "restart") as mock_restart,
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
            patch.object(srv, "server_phoenix", True),
            patch.object(srv, "restart") as mock_restart,
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

    def test_sighup_sets_phoenix_flag_and_raises(self, srv, prefork_server):
        """SIGHUP must set ``server_phoenix`` before raising ``KeyboardInterrupt``."""
        prefork_server.queue.append(signal.SIGHUP)
        with pytest.raises(KeyboardInterrupt):
            prefork_server.process_signals()
        assert srv.server_phoenix is True
        srv.server_phoenix = False  # reset global for subsequent tests

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

    def test_executes_listen_when_not_in_recovery(self, worker_cron):
        conn, cursor = self._mock_db(in_recovery=False)
        with patch("odoo.service.server.db.db_connect", return_value=conn):
            worker_cron._connect_postgres()
        executed = [c.args[0] for c in cursor.execute.call_args_list]
        assert "LISTEN cron_trigger" in executed

    def test_skips_listen_in_recovery_mode(self, worker_cron):
        conn, cursor = self._mock_db(in_recovery=True)
        with patch("odoo.service.server.db.db_connect", return_value=conn):
            worker_cron._connect_postgres()
        executed = [c.args[0] for c in cursor.execute.call_args_list]
        assert "LISTEN cron_trigger" not in executed

    def test_commits_after_listen(self, worker_cron):
        """``COMMIT`` ensures the LISTEN takes effect within the transaction."""
        conn, cursor = self._mock_db(in_recovery=False)
        with patch("odoo.service.server.db.db_connect", return_value=conn):
            worker_cron._connect_postgres()
        cursor.commit.assert_called_once()

    def test_sets_dbcursor_on_self(self, worker_cron):
        conn, cursor = self._mock_db(in_recovery=False)
        with patch("odoo.service.server.db.db_connect", return_value=conn):
            worker_cron._connect_postgres()
        assert worker_cron.dbcursor is cursor

    def test_connects_to_postgres_database(self, worker_cron):
        """Must connect to the ``postgres`` maintenance database, not a tenant db."""
        conn, _ = self._mock_db(in_recovery=False)
        with patch("odoo.service.server.db.db_connect", return_value=conn) as mock_connect:
            worker_cron._connect_postgres()
        mock_connect.assert_called_once_with("postgres")


# ---------------------------------------------------------------------------
# WorkerCron.process_work() — reconnect logic (the bug we fixed)
# ---------------------------------------------------------------------------


class TestWorkerCronProcessWorkReconnect:
    """``process_work()``: recovers from SSL/connection drops without crashing."""

    def test_operational_error_triggers_reconnect(self, worker_cron):
        """An SSL drop during ``notifies()`` must call ``_connect_postgres()``."""
        worker_cron.dbcursor._cnx.notifies.side_effect = psycopg.OperationalError(
            "SSL connection has been closed unexpectedly"
        )
        with (
            patch("odoo.service.server.cron_database_list", return_value=["testdb"]),
            patch.object(worker_cron, "_connect_postgres") as mock_reconnect,
        ):
            worker_cron.process_work()
        mock_reconnect.assert_called_once()

    def test_operational_error_returns_early(self, worker_cron):
        """After reconnecting, no database is queued or processed in this cycle."""
        worker_cron.dbcursor._cnx.notifies.side_effect = psycopg.OperationalError("SSL")
        with (
            patch("odoo.service.server.cron_database_list", return_value=["db1"]),
            patch.object(worker_cron, "_connect_postgres"),
        ):
            worker_cron.process_work()
        assert len(worker_cron.db_queue) == 0
        assert worker_cron.db_count == 0

    def test_operational_error_closes_cnx_before_cursor(self, worker_cron):
        """Connection must be closed before the cursor — mirrors ``stop()`` order."""
        old_cnx = worker_cron.dbcursor._cnx
        old_cursor = worker_cron.dbcursor
        call_order = []
        old_cnx.close.side_effect = lambda: call_order.append("cnx")
        old_cursor.close.side_effect = lambda: call_order.append("cursor")
        old_cnx.notifies.side_effect = psycopg.OperationalError("SSL")

        with (
            patch("odoo.service.server.cron_database_list", return_value=[]),
            patch.object(worker_cron, "_connect_postgres"),
        ):
            worker_cron.process_work()

        assert call_order == ["cnx", "cursor"]

    def test_close_error_on_broken_connection_is_suppressed(self, worker_cron):
        """A broken connection that also raises on ``close()`` must not prevent reconnect."""
        worker_cron.dbcursor._cnx.notifies.side_effect = psycopg.OperationalError("SSL")
        worker_cron.dbcursor._cnx.close.side_effect = Exception("already closed")
        worker_cron.dbcursor.close.side_effect = Exception("already closed")

        with (
            patch("odoo.service.server.cron_database_list", return_value=["db1"]),
            patch.object(worker_cron, "_connect_postgres") as mock_reconnect,
        ):
            worker_cron.process_work()  # must not raise

        mock_reconnect.assert_called_once()

    def test_reconnect_failure_propagates(self, worker_cron):
        """If ``_connect_postgres()`` itself fails, the error propagates to ``_runloop``."""
        worker_cron.dbcursor._cnx.notifies.side_effect = psycopg.OperationalError("SSL")
        with (
            patch("odoo.service.server.cron_database_list", return_value=["db1"]),
            patch.object(
                worker_cron,
                "_connect_postgres",
                side_effect=psycopg.OperationalError("postgres still unreachable"),
            ),
        ):
            with pytest.raises(psycopg.OperationalError, match="still unreachable"):
                worker_cron.process_work()


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
        worker_cron.dbcursor._cnx.notifies.return_value = iter([])
        with patch("odoo.service.server.cron_database_list", return_value=[]):
            worker_cron.process_work()
        assert len(worker_cron.db_queue) == 0
        assert worker_cron.db_count == 0

    def test_all_databases_queued_on_first_call(self, worker_cron, mock_ir_cron):
        """First call with an empty queue must enqueue all databases and process one."""
        worker_cron.dbcursor._cnx.notifies.return_value = iter([])
        with (
            patch("odoo.service.server.cron_database_list", return_value=["db1", "db2", "db3"]),
            patch("odoo.service.server.db"),
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
        worker_cron.dbcursor._cnx.notifies.return_value = iter([notif])

        with (
            patch(
                "odoo.service.server.cron_database_list",
                return_value=["slow_db", "urgent_db"],
            ),
            patch("odoo.service.server.db"),
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
        worker_cron.dbcursor._cnx.notifies.return_value = iter([notif])

        with (
            patch("odoo.service.server.cron_database_list", return_value=["real_db"]),
            patch("odoo.service.server.db"),
        ):
            worker_cron.process_work()

        all_dbs = list(worker_cron.db_queue) + [mock_ir_cron._process_jobs.call_args[0][0]]
        assert "unknown_db" not in all_dbs

    def test_existing_queue_skips_notification_polling(self, worker_cron, mock_ir_cron):
        """When ``db_queue`` is non-empty, ``notifies()`` must not be called."""
        worker_cron.db_queue.append("pending_db")
        worker_cron.db_count = 1

        with patch("odoo.service.server.db"):
            worker_cron.process_work()

        worker_cron.dbcursor._cnx.notifies.assert_not_called()

    def test_request_count_incremented(self, worker_cron, mock_ir_cron):
        worker_cron.dbcursor._cnx.notifies.return_value = iter([])
        with (
            patch("odoo.service.server.cron_database_list", return_value=["db1"]),
            patch("odoo.service.server.db"),
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
            patch("odoo.service.server.config", {"limit_time_worker_cron": 3600}),
            patch.object(srv.Worker, "check_limits"),
        ):
            worker_cron.check_limits()
        assert worker_cron.alive is True

    def test_worker_dies_when_age_exceeded(self, srv, worker_cron):
        worker_cron.alive_time = time.monotonic() - 99_999  # far in the past
        with (
            patch("odoo.service.server.config", {"limit_time_worker_cron": 60}),
            patch.object(srv.Worker, "check_limits"),
        ):
            worker_cron.check_limits()
        assert worker_cron.alive is False

    def test_zero_limit_never_expires(self, srv, worker_cron):
        """``limit_time_worker_cron = 0`` disables the age check entirely."""
        worker_cron.alive_time = time.monotonic() - 99_999
        with (
            patch("odoo.service.server.config", {"limit_time_worker_cron": 0}),
            patch.object(srv.Worker, "check_limits"),
        ):
            worker_cron.check_limits()
        assert worker_cron.alive is True

    def test_negative_limit_never_expires(self, srv, worker_cron):
        """Negative values (sentinel for 'inherit from limit_time_real') disable the check."""
        worker_cron.alive_time = time.monotonic() - 99_999
        with (
            patch("odoo.service.server.config", {"limit_time_worker_cron": -1}),
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
        patch("odoo.service.server.config", cfg),
        patch("odoo.service.server.set_limit_memory_hard"),
        patch("odoo.service.server.memory_info", return_value=memory_bytes),
        patch("odoo.service.server.resource", mock_resource),
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
    return w


class TestWorkerCheckLimits:
    """``Worker.check_limits()``: parent PID, request cap, memory soft limit, CPU rlimit."""

    def test_healthy_worker_stays_alive(self, bare_worker):
        patches, _ = _worker_check_limits_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            bare_worker.check_limits()
        assert bare_worker.alive is True

    def test_parent_changed_sets_alive_false(self, bare_worker):
        bare_worker.ppid = 99999  # deliberate mismatch with os.getppid()
        patches, _ = _worker_check_limits_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            bare_worker.check_limits()
        assert bare_worker.alive is False

    def test_request_max_reached_sets_alive_false(self, bare_worker):
        bare_worker.request_count = 100
        bare_worker.request_max = 100
        patches, _ = _worker_check_limits_patches()
        with patches[0], patches[1], patches[2], patches[3]:
            bare_worker.check_limits()
        assert bare_worker.alive is False

    def test_memory_soft_exceeded_sets_alive_false(self, bare_worker):
        patches, _ = _worker_check_limits_patches(
            memory_bytes=500,
            config_override={"limit_memory_soft": 100},
        )
        with patches[0], patches[1], patches[2], patches[3]:
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
        with patches[0], patches[1], patches[2], patches[3]:
            bare_worker.check_limits()
        # int(8.0 + 30) = 38
        mock_resource.setrlimit.assert_called_once_with(0, (38, 9999))


# ---------------------------------------------------------------------------
# CommonServer.on_stop() / stop()
# ---------------------------------------------------------------------------


class TestCommonServerCallbacks:
    """``on_stop()`` registers cleanup callbacks; ``stop()`` calls them all."""

    @pytest.fixture(autouse=True)
    def _restore_callbacks(self, srv):
        """Restore the class-level callback list after each test."""
        original = list(srv.CommonServer._on_stop_funcs)
        yield
        srv.CommonServer._on_stop_funcs[:] = original

    def test_on_stop_appends_callback(self, srv):
        cb = MagicMock()
        srv.CommonServer.on_stop(cb)
        assert cb in srv.CommonServer._on_stop_funcs

    def test_stop_calls_all_registered_callbacks(self, srv):
        server = object.__new__(srv.CommonServer)
        cb1, cb2 = MagicMock(), MagicMock()
        srv.CommonServer._on_stop_funcs.extend([cb1, cb2])
        server.stop()
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_stop_continues_after_callback_exception(self, srv):
        """An exception in one callback must not prevent subsequent callbacks."""
        server = object.__new__(srv.CommonServer)
        cb1 = MagicMock(side_effect=RuntimeError("boom"))
        cb1.__name__ = "cb1"  # stop() logs func.__name__; MagicMock needs it set
        cb2 = MagicMock()
        cb2.__name__ = "cb2"
        srv.CommonServer._on_stop_funcs.extend([cb1, cb2])
        server.stop()  # must not raise
        cb2.assert_called_once()


# ---------------------------------------------------------------------------
# cron_database_list()
# ---------------------------------------------------------------------------


class TestCronDatabaseList:
    """``cron_database_list()``: config override vs list_dbs fallback."""

    def test_returns_config_db_name_when_set(self, srv):
        with (
            patch("odoo.service.server.config", {"db_name": "mydb"}),
            patch("odoo.service.server.list_dbs") as mock_list,
        ):
            result = srv.cron_database_list()
        assert result == "mydb"
        mock_list.assert_not_called()

    def test_falls_back_to_list_dbs_when_empty(self, srv):
        with (
            patch("odoo.service.server.config", {"db_name": None}),
            patch("odoo.service.server.list_dbs", return_value=["db1", "db2"]) as mock_list,
        ):
            result = srv.cron_database_list()
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

    def test_exit_code_3_raises(self, prefork_server):
        """Exit status 3 signals a critical worker failure and must abort."""
        prefork_server.worker_pop = MagicMock()
        with patch("os.waitpid", return_value=(5678, 3 << 8)):
            with pytest.raises(Exception, match="Critical worker error"):
                prefork_server.process_zombie()

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
    h = object.__new__(srv.CommonRequestHandler)
    h.path = "/web/test"
    h.command = "GET"
    h.request_version = "HTTP/1.1"
    h.requestline = "GET /web/test HTTP/1.1"
    h.log = MagicMock()
    srv.thread_local.rpc_model_method = ""
    return h


class TestCommonRequestHandlerLogError:
    """``log_error()``: timeout errors are downgraded; others delegate to super."""

    def test_timeout_logs_at_debug(self, srv, log_handler):
        with patch("odoo.service.server._logger") as mock_logger:
            log_handler.log_error("Request timed out: %r", "socket")
        mock_logger.debug.assert_called_once()

    def test_other_error_calls_super(self, srv, log_handler):
        with (
            patch("odoo.service.server._logger"),
            patch.object(werkzeug.serving.WSGIRequestHandler, "log_error") as mock_super,
        ):
            log_handler.log_error("Some other error: %s", "detail")
        mock_super.assert_called_once()


class TestCommonRequestHandlerLogRequest:
    """``log_request()``: ANSI colour dispatch per HTTP status code."""

    def _captured_styles(self, log_handler, code):
        """Return the style args passed to ``_ansi_style`` for the given code."""
        captured = []
        with patch.object(
            werkzeug.serving,
            "_ansi_style",
            side_effect=lambda msg, *styles: captured.append(styles) or msg,
        ):
            log_handler.log_request(code, 0)
        return captured

    def test_200_no_ansi_styling(self, log_handler):
        with patch.object(werkzeug.serving, "_ansi_style") as mock_ansi:
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

    def test_bad_requestline_falls_back_to_requestline(self, srv):
        """AttributeError on ``self.path`` (malformed request) must not raise."""
        h = object.__new__(srv.CommonRequestHandler)
        # Intentionally do NOT set h.path → AttributeError in the try block
        h.requestline = "GARBAGE_LINE"
        h.log = MagicMock()
        srv.thread_local.rpc_model_method = ""
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
    s = object.__new__(srv.ThreadedWSGIServerReloadable)
    s.max_http_threads = 4
    s.http_threads_sem = MagicMock()
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


# ---------------------------------------------------------------------------
# service/common.py — dispatch() and exp_version()
# ---------------------------------------------------------------------------


class TestServiceCommon:
    """``odoo.service.common``: RPC dispatch table and version endpoint."""

    @pytest.fixture(scope="class")
    def common(self):
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

    @pytest.fixture(scope="class")
    def db_mod(self):
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
# set_limit_memory_hard()
# ---------------------------------------------------------------------------


class TestSetLimitMemoryHard:
    """``set_limit_memory_hard()``: applies RLIMIT_AS on Linux only."""

    def test_non_linux_is_noop(self, srv):
        mock_resource = MagicMock()
        with (
            patch("odoo.service.server.platform") as mock_platform,
            patch("odoo.service.server.resource", mock_resource),
        ):
            mock_platform.system.return_value = "Darwin"
            srv.set_limit_memory_hard()
        mock_resource.setrlimit.assert_not_called()

    def test_linux_no_limit_is_noop(self, srv):
        mock_resource = MagicMock()
        mock_resource.getrlimit.return_value = (0, 9999)
        mock_resource.RLIMIT_AS = 9
        with (
            patch("odoo.service.server.platform") as mock_platform,
            patch("odoo.service.server.resource", mock_resource),
            patch("odoo.service.server.config", {"limit_memory_hard": 0, "limit_memory_hard_gevent": 0}),
            patch("odoo.service.server.odoo") as mock_odoo,
        ):
            mock_platform.system.return_value = "Linux"
            mock_odoo.evented = False
            srv.set_limit_memory_hard()
        mock_resource.setrlimit.assert_not_called()

    def test_linux_sets_rlimit(self, srv):
        mock_resource = MagicMock()
        mock_resource.getrlimit.return_value = (0, 9999)
        mock_resource.RLIMIT_AS = 9
        limit = 512 * 1024 * 1024
        with (
            patch("odoo.service.server.platform") as mock_platform,
            patch("odoo.service.server.resource", mock_resource),
            patch("odoo.service.server.config", {"limit_memory_hard": limit, "limit_memory_hard_gevent": 0}),
            patch("odoo.service.server.odoo") as mock_odoo,
        ):
            mock_platform.system.return_value = "Linux"
            mock_odoo.evented = False
            srv.set_limit_memory_hard()
        mock_resource.setrlimit.assert_called_once_with(9, (limit, 9999))

    def test_linux_evented_uses_gevent_limit(self, srv):
        """When running evented and ``limit_memory_hard_gevent`` is set, prefer it."""
        mock_resource = MagicMock()
        mock_resource.getrlimit.return_value = (0, 9999)
        mock_resource.RLIMIT_AS = 9
        gevent_limit = 256 * 1024 * 1024
        with (
            patch("odoo.service.server.platform") as mock_platform,
            patch("odoo.service.server.resource", mock_resource),
            patch(
                "odoo.service.server.config",
                {"limit_memory_hard": 512 * 1024 * 1024, "limit_memory_hard_gevent": gevent_limit},
            ),
            patch("odoo.service.server.odoo") as mock_odoo,
        ):
            mock_platform.system.return_value = "Linux"
            mock_odoo.evented = True
            srv.set_limit_memory_hard()
        mock_resource.setrlimit.assert_called_once_with(9, (gevent_limit, 9999))


# ---------------------------------------------------------------------------
# ThreadedServer.process_limit()
# ---------------------------------------------------------------------------


@pytest.fixture()
def tserver(srv):
    """Minimal ThreadedServer bypassing socket/config init for process_limit() tests."""
    s = object.__new__(srv.ThreadedServer)
    s.limits_reached_threads = set()
    s.limit_reached_time = None
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
            patch("odoo.service.server.memory_info", return_value=memory),
            patch("odoo.service.server.config", cfg),
            patch("odoo.service.server.psutil"),
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
             patch("odoo.service.server.time") as mock_time:
            mock_time.monotonic.side_effect = counting_monotonic
            tserver.process_limit()

        # One call for the loop snapshot + one call for limit_reached_time = 2 max.
        # Before the fix this would be len(threads) + 1 = 6.
        assert mock_time.monotonic.call_count <= 2
