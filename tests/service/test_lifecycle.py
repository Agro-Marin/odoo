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
