import errno
import os
import signal
import threading
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def mod():
    import odoo.service.lifecycle as m

    return m


@pytest.fixture(scope="module")
def srv():
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
    cr = MagicMock()
    cr.fetchone.side_effect = [
        (str(max_connections),),
        (str(reserved),),
        (server_port,),
    ]
    return cr


class TestConnectionBudgetDemand:
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
        with patch.object(
            mod, "config", make_config(workers=1, max_cron_threads=0, job_workers=0)
        ):
            processes, _ = mod._connection_budget_demand()
        assert processes == 2


class TestWarnOnConnectionBudget:
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
        template, *args = logger.warning.call_args[0]
        message = template % tuple(args)
        assert "9 process" in message, message
        assert "576" in message, message
        assert "97" in message, message
        assert "to 10 or less" in message, message

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
        logger = self._run(
            mod,
            make_config(workers=8),
            connect_error=RuntimeError("no route to host"),
        )
        logger.warning.assert_not_called()

    def test_suggested_ceiling_is_never_zero(self, mod):
        logger = self._run(
            mod, make_config(workers=200, max_cron_threads=0, job_workers=0)
        )
        assert logger.warning.call_args[0][-1] >= 1

    def test_no_advice_behind_a_pooler(self, mod):
        logger = self._run(
            mod,
            make_config(workers=4, max_cron_threads=2, job_workers=2),
            cursor=limits_cursor(server_port=5433),
        )
        logger.warning.assert_not_called()
        logger.info.assert_called_once()

    def test_a_unix_socket_does_not_read_as_a_pooler(self, mod):
        logger = self._run(
            mod,
            make_config(workers=4, max_cron_threads=2, job_workers=2),
            cursor=limits_cursor(server_port=None),
        )
        logger.warning.assert_called_once()

    def test_an_incomplete_config_cannot_break_the_boot(self, mod):
        logger = self._run(mod, {"workers": 0})
        logger.warning.assert_not_called()

    def test_a_hostile_config_mapping_cannot_break_the_boot(self, mod):
        exploding = MagicMock()
        exploding.__getitem__.side_effect = RuntimeError("config is gone")
        logger = self._run(mod, exploding)
        logger.warning.assert_not_called()

    def test_skipped_in_the_evented_child(self, mod):
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
    @pytest.fixture
    def spec(self, mod):
        return mod._narrowing_test_spec

    def _with_tags(self, tags):
        import odoo.tools

        return odoo.tools.config.patch(test_tags=tags)

    @pytest.mark.parametrize("tags", ["", None, "+standard"])
    def test_implicit_selection_is_not_narrowing(self, spec, tags):
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
        rc, _, _, _ = preload(
            ["a", "b", "c"],
            report=make_report(successful=False),
            config_overrides={"test_enable": True},
        )
        assert rc == 3

    def test_a_narrowed_spec_that_ran_nothing_fails_the_run(self, preload):
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
        rc, logger, _, _ = preload(
            ["db1"],
            report=make_report(tests_run=0),
            config_overrides={"test_enable": True},
            spec="",
        )
        assert rc == 0
        logger.error.assert_not_called()

    def test_a_successful_run_is_never_second_guessed(self, preload):
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
        boom = MagicMock(side_effect=RuntimeError("registry is toast"))
        rc, logger, registry_cls, _ = preload(["db1", "db2"], new=boom)
        assert rc == -1
        assert registry_cls.new.call_count == 1, "db2 should never be attempted"
        logger.critical.assert_called_once()
        assert "db1" in str(logger.critical.call_args)

    def test_the_registry_cache_grows_to_hold_every_database(self, preload):
        _, _, registry_cls, _ = preload(
            [f"db{i}" for i in range(40)], report=make_report()
        )
        assert registry_cls.registries.count >= 40


class TestReexecNtServiceRestart:
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
    def test_lifecycle_is_the_canonical_holder(self):
        from odoo.service import lifecycle

        assert hasattr(lifecycle, "server")
        assert hasattr(lifecycle, "server_phoenix")

    def test_server_module_does_not_forward_phoenix(self, srv):
        with pytest.raises(AttributeError):
            _ = srv.server_phoenix

    def test_server_module_does_not_forward_server(self, srv):
        with pytest.raises(AttributeError):
            _ = srv.server


# ---------------------------------------------------------------------------
# lifecycle.start() — watcher cleanup on the error path
# ---------------------------------------------------------------------------


class TestLifecycleStartWatcherCleanup:
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
    def test_restart_with_none_server_is_noop(self, srv, caplog):
        with (
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
        fake_server = MagicMock()
        fake_server.pid = 12345

        with (
            patch("odoo.service.lifecycle.server", fake_server),
            patch.object(os, "name", "posix"),
            patch.object(os, "kill") as mock_kill,
        ):
            srv.restart()

        mock_kill.assert_called_once_with(12345, signal.SIGHUP)

    def test_threaded_server_reload_delegates_to_lifecycle(self, srv):
        ts = object.__new__(srv.ThreadedServer)
        ts.pid = 12345
        with patch("odoo.service.lifecycle.restart") as mock_restart:
            ts.reload()
        mock_restart.assert_called_once_with()

    def test_threaded_server_reload_is_windows_safe(self, srv):
        ts = object.__new__(srv.ThreadedServer)
        ts.pid = 12345
        from odoo.service import lifecycle

        with (
            patch("odoo.service.lifecycle.server", ts),
            patch.object(lifecycle.os, "name", "nt"),
            patch.object(lifecycle, "_reexec") as mock_reexec,
            patch.object(lifecycle.threading, "Thread") as mock_thread,
        ):
            ts.reload()
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


class TestSigHupSentinel:
    def test_local_sentinel_exported(self, srv):
        assert hasattr(srv, "_SIGHUP_AVAILABLE")
        assert isinstance(srv._SIGHUP_AVAILABLE, bool)

    def test_on_posix_sentinel_is_true(self, srv):
        import os

        if os.name == "posix":
            assert srv._SIGHUP_AVAILABLE is True
