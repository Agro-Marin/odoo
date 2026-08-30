import pytest

from odoo.service import _cron, _limits


class _Conf(dict):
    def __getitem__(self, key):
        return self.get(key)


@pytest.fixture
def conf(monkeypatch):
    c = _Conf({"db_name": [], "dbfilter": "", "db_template": "tpl"})
    monkeypatch.setattr(_cron, "config", c)
    monkeypatch.setattr(_cron, "_dbfilter_warned", False)
    return c


@pytest.fixture
def catalogue(monkeypatch):
    names = ["alpha_prod", "alpha_test", "beta_prod", "postgres", "tpl"]
    monkeypatch.setattr(_cron, "list_dbs", lambda force: list(names))
    monkeypatch.setattr(
        _cron, "is_maintenance_db", lambda n: n in {"postgres", "template1", "tpl"}
    )
    return names


class TestCronDatabaseList:
    def test_db_name_wins_and_is_copied(self, conf, catalogue):
        conf["db_name"] = ["only_this"]
        got = _cron.cron_database_list()
        assert got == ["only_this"]
        got.append("mutated")
        assert conf["db_name"] == ["only_this"], "the caller mutated the config list"

    def test_maintenance_databases_never_get_cron(self, conf, catalogue):
        assert _cron.cron_database_list() == [
            "alpha_prod",
            "alpha_test",
            "beta_prod",
        ]

    def test_a_static_dbfilter_scopes_the_sweep(self, conf, catalogue):
        conf["dbfilter"] = "alpha_.*"
        assert _cron.cron_database_list() == ["alpha_prod", "alpha_test"]

    def test_a_host_dependent_dbfilter_cannot_scope_and_says_so(
        self, conf, catalogue, caplog
    ):
        conf["dbfilter"] = "%d_prod"
        with caplog.at_level("WARNING", logger="odoo.service.server"):
            assert _cron.cron_database_list() == [
                "alpha_prod",
                "alpha_test",
                "beta_prod",
            ]
        assert "cannot scope cron" in caplog.text

    def test_the_host_dependent_warning_fires_once_per_process(
        self, conf, catalogue, caplog
    ):
        conf["dbfilter"] = "%h"
        with caplog.at_level("WARNING", logger="odoo.service.server"):
            for _ in range(5):
                _cron.cron_database_list()
        assert caplog.text.count("cannot scope cron") == 1

    def test_an_invalid_dbfilter_does_not_take_the_sweep_down(
        self, conf, catalogue, caplog
    ):
        conf["dbfilter"] = "alpha_[("
        with caplog.at_level("WARNING", logger="odoo.service.server"):
            assert _cron.cron_database_list() == [
                "alpha_prod",
                "alpha_test",
                "beta_prod",
            ]
        assert "not a valid regular expression" in caplog.text

    def test_the_filter_anchors_at_the_start_like_db_filter_does(self, conf, catalogue):
        conf["dbfilter"] = "prod"
        assert _cron.cron_database_list() == []


class TestInheritFromCron:
    def test_the_sentinel_is_the_one_the_budgets_compare_against(self, monkeypatch):
        c = _Conf(
            {
                "limit_time_worker_job": _limits.INHERIT_FROM_CRON,
                "limit_time_worker_cron": 900,
                "limit_time_real_job": _limits.INHERIT_FROM_CRON,
                "limit_time_real_cron": 300,
                "limit_time_real": 120,
            }
        )
        monkeypatch.setattr(_limits, "config", c)
        assert _limits.job_max_age() == 900
        assert _limits.job_real_time_budget() == 300

    def test_zero_disables_rather_than_inherits(self, monkeypatch):
        c = _Conf({"limit_time_worker_job": 0, "limit_time_worker_cron": 900})
        monkeypatch.setattr(_limits, "config", c)
        assert _limits.job_max_age() == 0
