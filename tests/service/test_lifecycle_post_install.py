from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from odoo.service import lifecycle


@pytest.fixture
def registry():
    reg = MagicMock()
    reg.cursor.return_value = nullcontext(MagicMock())
    reg.updated_modules = ["updated_one", "updated_two"]
    reg._init_modules = {"zeta", "alpha"}
    reg._assertion_report.testsRun = 0
    return reg


@pytest.fixture
def loader():
    """Patch the two function-local imports and the module-level `db`/`api`."""
    suite = MagicMock()
    suite.has_http_case.return_value = False
    suite.countTestCases.return_value = 25
    fake = MagicMock()
    fake.prepare_suite.return_value = suite
    fake.run_suite.return_value.testsRun = 25
    with (
        patch.dict("sys.modules", {}),
        patch("odoo.tests.loader", fake, create=True),
        patch("odoo.db.utils.seed_planner_stats", return_value=0) as seed,
        patch.object(lifecycle, "db", MagicMock(sql_counter=0)),
    ):
        yield fake, suite, seed


class TestWhichModulesThePostInstallSuiteRunsFor:
    """The set is chosen from one flag, and choosing wrong is silent.

    Too narrow and a `--test-enable` boot reports success having run almost
    nothing; too wide and an `-i one_module` run drags in every installed
    module's post_install suite.
    """

    def test_an_updating_run_tests_only_what_it_updated(self, registry, loader):
        fake, _suite, _seed = loader

        lifecycle._run_post_install_tests(registry, update_module=True)

        fake.prepare_suite.assert_called_once_with(
            ["updated_one", "updated_two"], "post_install"
        )

    def test_a_plain_boot_tests_every_installed_module_in_a_stable_order(
        self, registry, loader
    ):
        """`_init_modules` is a set; an unordered suite is an unreproducible run."""
        fake, _suite, _seed = loader

        lifecycle._run_post_install_tests(registry, update_module=False)

        fake.prepare_suite.assert_called_once_with(["alpha", "zeta"], "post_install")


class TestAssetsArePregeneratedOnlyWhenSomethingServesHttp:
    def test_an_http_suite_pregenerates_the_bundles(self, registry, loader):
        _fake, suite, _seed = loader
        suite.has_http_case.return_value = True
        env = {"ir.qweb": MagicMock()}

        with patch.object(lifecycle, "api", MagicMock()) as api:
            api.Environment.return_value = env
            lifecycle._run_post_install_tests(registry, update_module=True)

        env["ir.qweb"]._pregenerate_assets_bundles.assert_called_once_with()

    def test_a_suite_with_no_http_case_does_not(self, registry, loader):
        _fake, suite, _seed = loader
        suite.has_http_case.return_value = False

        with patch.object(lifecycle, "api", MagicMock()) as api:
            lifecycle._run_post_install_tests(registry, update_module=True)

        assert not api.Environment.called, (
            "building the environment and pregenerating every asset bundle is "
            "expensive; a suite that never serves a request must not pay it"
        )


class TestSeedingPlannerStatsIsBestEffort:
    """It exists to make the tests faster, so it may never stop them running.

    `_run_post_install_tests` is called inside `preload_registries`' try/except,
    which turns anything raised here into `Failed to initialize database` and a
    return of -1 -- so a transient failure while seeding would present as the
    database being broken rather than as a slow test run.
    """

    def test_a_failure_to_seed_does_not_stop_the_suite(self, registry, loader):
        fake, _suite, seed = loader
        seed.side_effect = RuntimeError("planner stats unavailable")

        lifecycle._run_post_install_tests(registry, update_module=True)

        fake.run_suite.assert_called_once()

    def test_the_report_is_updated_with_the_result(self, registry, loader):
        fake, _suite, _seed = loader

        lifecycle._run_post_install_tests(registry, update_module=True)

        registry._assertion_report.update.assert_called_once_with(
            fake.run_suite.return_value
        )


class TestAHollowPhaseIsReportedToTheCaller:
    """Prepared N, started none: the shape `--no-http` produces when every
    post_install class is an HttpCase. `testsRun` is counted at `startTest`,
    which a class skipped at setUpClass never reaches, so the report alone
    cannot tell this from a module that ships no post_install tests."""

    def test_prepared_but_unstarted_returns_the_prepared_count(self, registry, loader):
        fake, suite, _seed = loader
        suite.countTestCases.return_value = 25
        fake.run_suite.return_value.testsRun = 0

        assert lifecycle._run_post_install_tests(registry, update_module=True) == 25

    def test_a_phase_that_started_something_returns_zero(self, registry, loader):
        fake, suite, _seed = loader
        suite.countTestCases.return_value = 25
        fake.run_suite.return_value.testsRun = 3

        assert lifecycle._run_post_install_tests(registry, update_module=True) == 0

    def test_a_module_with_no_post_install_tests_is_not_hollow(self, registry, loader):
        fake, suite, _seed = loader
        suite.countTestCases.return_value = 0
        fake.run_suite.return_value.testsRun = 0

        assert lifecycle._run_post_install_tests(registry, update_module=True) == 0
