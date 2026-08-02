"""Pure-pytest tests for ``odoo.service.lifecycle``'s startup checks.

Run with::

    python -m pytest tests/service/test_lifecycle.py -v
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def mod():
    """Return ``odoo.service.lifecycle``, imported once per session."""
    import odoo.service.lifecycle as m

    return m


def make_config(**overrides):
    base = {
        "db_maxconn": 64,
        "db_maxconn_gevent": None,
        "workers": 0,
        "max_cron_threads": 2,
        "job_workers": 2,
        "http_enable": True,
    }
    base.update(overrides)
    return base


def limits_cursor(max_connections=100, reserved=3):
    cr = MagicMock()
    cr.fetchone.side_effect = [(str(max_connections),), (str(reserved),)]
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

    @pytest.fixture()
    def spec(self, mod):
        return mod._narrowing_test_spec

    def _with_tags(self, tags):
        import odoo.tools

        return patch.dict(odoo.tools.config.options, {"test_tags": tags})

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

    @pytest.fixture()
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
