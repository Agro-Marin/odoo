import inspect
from unittest.mock import patch

import pytest

from odoo.service._helpers import SLEEP_INTERVAL, capped_backoff

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
    assert SLEEP_INTERVAL == 60
    assert [capped_backoff(a) for a in range(12)] == CURVES[60]


def test_a_runaway_attempt_count_stays_clamped_and_cheap():
    assert capped_backoff(10_000) == SLEEP_INTERVAL


class TestJobLimitsAreSeparableFromCron:
    CRON = {"limit_time_worker_cron": 300, "limit_time_real_cron": 120}

    def _with(self, **overrides):
        from odoo.tools import config

        return patch.dict(config.options, {**self.CRON, **overrides})

    def test_the_default_follows_cron(self):
        from odoo.service._helpers import job_max_age, job_time_real

        with self._with(limit_time_worker_job=-1, limit_time_real_job=-1):
            assert job_max_age() == 300
            assert job_time_real() == 120

    def test_an_explicit_job_limit_wins(self):
        from odoo.service._helpers import job_max_age, job_time_real

        with self._with(limit_time_worker_job=900, limit_time_real_job=3600):
            assert job_max_age() == 900
            assert job_time_real() == 3600

    def test_zero_disables_for_jobs_without_disabling_cron(self):
        from odoo.service._helpers import job_max_age, job_time_real

        with self._with(limit_time_worker_job=0, limit_time_real_job=0):
            assert job_max_age() == 0
            assert job_time_real() == 0
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
    from odoo.service._helpers import cron_real_time_budget
    from odoo.tools import config

    with patch.dict(
        config.options, {"limit_time_real": real, "limit_time_real_cron": cron}
    ):
        assert cron_real_time_budget() == expected


@pytest.mark.parametrize(("real", "cron", "expected"), CRON_BUDGET_CASES)
def test_the_prefork_watchdog_agrees_with_the_resolver(real, cron, expected):
    from unittest.mock import MagicMock

    from odoo.service import _base_server, _prefork, server
    from odoo.service._helpers import cron_real_time_budget

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
        patch("odoo.service._helpers.config", cfg),
    ):
        prefork = server.PreforkServer(MagicMock())
        assert prefork.cron_timeout == (cron_real_time_budget() or None)
        assert prefork.cron_timeout == (expected or None)


def test_nothing_outside_the_resolver_reads_the_raw_cron_knob():
    """Three call sites resolved ``--limit-time-real-cron`` inline and each got
    a different subset of its sentinel chain right: a deadline computed from
    ``-1`` lands in the past, and ``if limit and limit > 0`` reads the
    documented "0 means no limit" as "fall back to the http limit"."""
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
        and path.name != "_helpers.py"
    )
    assert offenders == [], (
        "cron_real_time_budget() is the one answer to how long cron work may "
        f"run; {offenders} resolve the knob themselves"
    )
