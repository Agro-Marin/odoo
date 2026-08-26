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
