import inspect
from unittest.mock import patch

import pytest

from odoo.service._limits import BACKOFF_CEILING_S, capped_backoff

CURVES = {
    60: [1, 2, 4, 8, 16, 32, 60, 60, 60, 60, 60, 60],
    30: [1, 2, 4, 8, 16, 30, 30, 30, 30, 30, 30, 30],
    10: [1, 2, 4, 8, 10, 10, 10, 10, 10, 10, 10, 10],
    1: [1] * 12,
    0: [0] * 12,
}


@pytest.mark.parametrize("ceiling", sorted(CURVES))
def test_curve_doubles_then_clamps(ceiling):
    assert [capped_backoff(a, ceiling) for a in range(12)] == CURVES[ceiling]


def test_default_ceiling_is_the_sleep_interval():
    assert BACKOFF_CEILING_S == 60
    assert [capped_backoff(a) for a in range(12)] == CURVES[60]


def test_a_runaway_attempt_count_stays_clamped_and_cheap():
    assert capped_backoff(10_000) == BACKOFF_CEILING_S


class TestJobLimitsAreSeparableFromCron:
    CRON = {"limit_time_worker_cron": 300, "limit_time_real_cron": 120}

    def _with(self, **overrides):
        from odoo.tools import config

        return patch.dict(config.options, {**self.CRON, **overrides})

    def test_the_default_follows_cron(self):
        from odoo.service._limits import job_max_age, job_real_time_budget

        with self._with(limit_time_worker_job=-1, limit_time_real_job=-1):
            assert job_max_age() == 300
            assert job_real_time_budget() == 120

    def test_an_explicit_job_limit_wins(self):
        from odoo.service._limits import job_max_age, job_real_time_budget

        with self._with(limit_time_worker_job=900, limit_time_real_job=3600):
            assert job_max_age() == 900
            assert job_real_time_budget() == 3600

    def test_zero_disables_for_jobs_without_disabling_cron(self):
        from odoo.service._limits import job_max_age, job_real_time_budget

        with self._with(limit_time_worker_job=0, limit_time_real_job=0):
            assert job_max_age() == 0
            assert job_real_time_budget() == 0
        from odoo.tools import config

        with self._with(limit_time_worker_job=0, limit_time_real_job=0):
            assert config["limit_time_worker_cron"] == 300

    def test_both_options_are_registered(self):
        from odoo.tools import config

        assert "limit_time_worker_job" in config.options
        assert "limit_time_real_job" in config.options

    def test_worker_job_overrides_the_cron_max_age(self):
        from odoo.service._worker import WorkerCron, WorkerJob

        assert WorkerJob.max_age is not WorkerCron.max_age
        worker = WorkerJob.__new__(WorkerJob)
        with self._with(limit_time_worker_job=900):
            assert worker.max_age() == 900
        with self._with(limit_time_worker_job=-1):
            assert worker.max_age() == 300

    def test_worker_job_arms_its_watchdog_from_the_job_timeout(self):
        from odoo.service._worker import WorkerJob

        source = inspect.getsource(WorkerJob)
        assert "multi.job_timeout" in source


CRON_BUDGET_CASES = [
    (120, -1, 120),
    (120, -5, 120),
    (120, 0, 0),
    (120, 30, 30),
    (0, -5, 0),
    (0, 0, 0),
]


@pytest.mark.parametrize(("real", "cron", "expected"), CRON_BUDGET_CASES)
def test_the_cron_budget_resolves_the_whole_sentinel_chain(real, cron, expected):
    from odoo.service._limits import cron_real_time_budget
    from odoo.tools import config

    with patch.dict(
        config.options, {"limit_time_real": real, "limit_time_real_cron": cron}
    ):
        assert cron_real_time_budget() == expected


@pytest.mark.parametrize(("real", "cron", "expected"), CRON_BUDGET_CASES)
def test_the_prefork_watchdog_agrees_with_the_resolver(real, cron, expected):
    from unittest.mock import MagicMock

    from odoo.service import _base_server, _prefork, server
    from odoo.service._limits import cron_real_time_budget

    cfg = {
        "http_interface": "",
        "http_port": 8069,
        "workers": 2,
        "limit_request": 100,
        "limit_time_real": real,
        "limit_time_real_cron": cron,
        "limit_time_real_job": -1,
    }
    with (
        patch.object(_prefork, "config", cfg),
        patch.object(_base_server, "config", cfg),
        patch("odoo.service._limits.config", cfg),
    ):
        prefork = server.PreforkServer(MagicMock())
        assert prefork.cron_timeout == (cron_real_time_budget() or None)
        assert prefork.cron_timeout == (expected or None)


def test_nothing_outside_the_resolver_reads_the_raw_cron_knob():
    import pathlib

    import odoo

    root = pathlib.Path(odoo.__file__).resolve().parent
    scanned = [
        *sorted((root / "service").glob("*.py")),
        root / "addons" / "base" / "models" / "ir_cron.py",
        root / "addons" / "base" / "models" / "ir_job.py",
    ]
    offenders = sorted(
        path.name
        for path in scanned
        if path.exists()
        and "limit_time_real_cron" in path.read_text()
        and path.name != "_limits.py"
    )
    assert offenders == [], (
        "cron_real_time_budget() is the one answer to how long cron work may "
        f"run; {offenders} resolve the knob themselves"
    )


SENTINELS = [-5, -1, 0, 30, 300]


def _legacy_inherits(limit):
    """The pre-`_get_inherited_budget` predicate, spelled out as it was."""
    return limit == -1 or limit < -1


@pytest.mark.parametrize("worker_job", SENTINELS)
@pytest.mark.parametrize("worker_cron", SENTINELS)
def test_job_max_age_still_walks_the_two_level_chain(worker_job, worker_cron):
    """`_get_inherited_budget` must be a rewrite, not a behaviour change."""
    from odoo.service._limits import job_max_age
    from odoo.tools import config

    expected = worker_cron if _legacy_inherits(worker_job) else worker_job
    with patch.dict(
        config.options,
        {
            "limit_time_worker_job": worker_job,
            "limit_time_worker_cron": worker_cron,
        },
    ):
        assert job_max_age() == expected


@pytest.mark.parametrize("real_job", SENTINELS)
@pytest.mark.parametrize("real_cron", SENTINELS)
@pytest.mark.parametrize("real", [-1, 0, 120])
def test_the_job_budget_still_walks_the_three_level_chain(real_job, real_cron, real):
    """The one chain with three links, and the only one that re-tests a result.

    The old code reached `limit_time_real` by asking `_inherits_from_cron`
    about the *return value* of a two-level helper, which is a chain hidden in
    the call graph rather than stated.  That helper was deleted on 2026-08-30
    once nothing called it; this pins that the flattened version resolves every
    one of the 75 sentinel combinations identically to the nested one.
    """
    from odoo.service._limits import job_real_time_budget
    from odoo.tools import config

    legacy = real_cron if _legacy_inherits(real_job) else real_job
    if _legacy_inherits(legacy):
        legacy = real
    expected = max(legacy, 0)

    with patch.dict(
        config.options,
        {
            "limit_time_real_job": real_job,
            "limit_time_real_cron": real_cron,
            "limit_time_real": real,
        },
    ):
        assert job_real_time_budget() == expected


def test_a_chain_whose_last_link_also_inherits_returns_the_sentinel():
    """Documented edge: the caller's clamp, not the resolver, absorbs it."""
    from odoo.service._limits import _get_inherited_budget, cron_real_time_budget
    from odoo.tools import config

    with patch.dict(
        config.options, {"limit_time_real_cron": -1, "limit_time_real": -1}
    ):
        assert _get_inherited_budget("limit_time_real_cron", "limit_time_real") == -1
        assert cron_real_time_budget() == 0


class TestBothCronLoopsReleaseADatabaseTheSameWay:
    """One behaviour, one primitive.

    The threaded loop drained and the prefork worker closed, with the same
    guard and the same intent on both sides.  `close_database` pops the pool
    AND discards `_reachable_keys`, so `_get_or_create_pool` then pays a fresh
    connectability probe plus a pool construction for that database on every
    sweep; `drain_database` keeps both.
    """

    def test_it_drains_rather_than_closes(self):
        from odoo.service import _cron

        with (
            patch.object(_cron.db, "drain_db") as drain,
            patch.object(_cron.db, "close_db") as close,
        ):
            _cron.release_swept_database("somedb")

        drain.assert_called_once_with("somedb")
        assert not close.called, (
            "closing discards the pool and its proven-reachable record, so the "
            "next sweep re-probes and rebuilds the pool for this database"
        )

    def test_neither_loop_reaches_past_the_helper(self):
        import pathlib

        import odoo

        service = pathlib.Path(odoo.__file__).resolve().parent / "service"
        offenders = sorted(
            path.name
            for path in (service / "_threaded.py", service / "_worker.py")
            if "close_db(" in path.read_text() or "drain_db(" in path.read_text()
        )
        assert offenders == [], (
            "release_swept_database() is the one answer to how a sweep lets go "
            f"of a database; {offenders} call the pool primitives directly and "
            "can drift apart again"
        )
