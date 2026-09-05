import os
import subprocess
import sys

from .conftest import REPO_ROOT, requires_pg

AT_INSTALL_CLASS = "/base:TestIrDefault"
POST_INSTALL_HTTP_CLASS = "/base:TestHttpCase"
POST_INSTALL_DB_TEST = (
    "/base:TestCopyDataContract.test_deduplicated_recordset_copies_normally"
)


def _update_base_with_tests(
    base_db, tmp_path, tags, *, require_infra=None, serve_http=False
):
    environment = dict(os.environ)
    environment.pop("ODOO_REQUIRE_INFRA", None)
    if require_infra is not None:
        environment["ODOO_REQUIRE_INFRA"] = require_infra
    http_options = (
        ["--http-interface", "127.0.0.1", "--http-port", "0"]
        if serve_http
        else ["--no-http"]
    )
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "odoo-bin"),
            "--addons-path",
            f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'}",
            "--data-dir",
            str(tmp_path / "data"),
            "-d",
            base_db,
            "-u",
            "base",
            "--test-enable",
            "--test-tags",
            tags,
            "--stop-after-init",
            *http_options,
            "--max-cron-threads",
            "0",
            "--log-level",
            "test",
            "--logfile",
            str(tmp_path / "run.log"),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        env=environment,
    )


def _summary(tmp_path):
    text = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
    return [line for line in text.splitlines() if "odoo.tests.result" in line]


@requires_pg
class TestAHollowPostInstallPhaseFailsTheProcess:
    """`-u base --test-enable --no-http` with an at_install class and an
    HttpCase-only post_install selection.

    The at_install class runs during loading, so the report holds tests and
    the narrowed-spec guard is silent; the HttpCase skips itself at setUpClass,
    so the post_install phase prepared N and started none. Until 2026-09-01
    that run exited 0 -- the shape every `--no-http` lane reports as green
    when its selection turns out to be HttpCase-only.
    """

    def test_a_prepared_but_unstarted_phase_exits_non_zero(self, base_db, tmp_path):
        proc = _update_base_with_tests(
            base_db,
            tmp_path,
            f"{AT_INSTALL_CLASS},{POST_INSTALL_HTTP_CLASS}",
            require_infra="0",
        )
        log = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
        assert "post_install prepared" in log, (
            "the hollow phase was not named in the log:\n"
            + "\n".join(_summary(tmp_path))
        )
        assert proc.returncode != 0, (
            "at_install ran and post_install prepared tests it never started, "
            "and the process still exited 0:\n" + "\n".join(_summary(tmp_path))
        )

    def test_a_phase_that_ran_what_it_prepared_exits_zero(self, base_db, tmp_path):
        proc = _update_base_with_tests(base_db, tmp_path, AT_INSTALL_CLASS)
        log = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
        assert "post_install prepared" not in log
        assert proc.returncode == 0, f"exit {proc.returncode}:\n" + "\n".join(
            _summary(tmp_path)
        )

    def test_missing_http_fails_even_when_the_same_phase_runs_database_tests(
        self, base_db, tmp_path
    ):
        proc = _update_base_with_tests(
            base_db, tmp_path, f"{POST_INSTALL_DB_TEST},{POST_INSTALL_HTTP_CLASS}"
        )
        log = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
        assert (
            "Starting TestCopyDataContract.test_deduplicated_recordset_copies_normally"
            in log
        )
        assert "requires a running HTTP server" in log
        assert proc.returncode != 0, (
            "a mixed phase silently accepted missing HTTP coverage"
        )

    def test_explicit_partial_run_reports_its_missing_http_coverage(
        self, base_db, tmp_path
    ):
        proc = _update_base_with_tests(
            base_db,
            tmp_path,
            f"{POST_INSTALL_DB_TEST},{POST_INSTALL_HTTP_CLASS}",
            require_infra="0",
        )
        log = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
        assert "explicitly permits this incomplete run" in log
        assert proc.returncode == 0, log[-4000:]

    def test_served_http_and_database_tests_run_successfully(self, base_db, tmp_path):
        http_test = (
            "/base:TestAllowRequests.test_allow_all_requests_flag_restored_after_xmlrpc"
        )
        proc = _update_base_with_tests(
            base_db, tmp_path, f"{POST_INSTALL_DB_TEST},{http_test}", serve_http=True
        )
        log = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
        assert (
            "Starting TestAllowRequests.test_allow_all_requests_flag_restored_after_xmlrpc"
            in log
        )
        assert (
            "Starting TestCopyDataContract.test_deduplicated_recordset_copies_normally"
            in log
        )
        assert proc.returncode == 0, log[-4000:]

    def test_infrastructure_result_accounting_contract_runs_under_the_default(
        self, base_db, tmp_path
    ):
        proc = _update_base_with_tests(
            base_db, tmp_path, "/base:TestInfrastructureUnavailable"
        )
        log = (tmp_path / "run.log").read_text(encoding="utf-8", errors="replace")
        assert "Starting TestInfrastructureUnavailable." in log
        assert proc.returncode == 0, log[-4000:]
