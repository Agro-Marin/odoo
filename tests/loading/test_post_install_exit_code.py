import subprocess
import sys

from .conftest import REPO_ROOT, requires_pg

AT_INSTALL_CLASS = "/base:TestIrDefault"
POST_INSTALL_HTTP_CLASS = "/base:TestHttpCase"


def _update_base_with_tests(base_db, tmp_path, tags):
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
            "--no-http",
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
            base_db, tmp_path, f"{AT_INSTALL_CLASS},{POST_INSTALL_HTTP_CLASS}"
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
