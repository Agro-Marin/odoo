import subprocess
import sys

from .conftest import ODOO_BIN, REPO_ROOT, requires_pg, requires_posix

ADDONS_PATH = f"{REPO_ROOT / 'odoo' / 'addons'},{REPO_ROOT / 'addons'}"


def _stop_after_init(tmp_path, *args):
    return subprocess.run(
        [
            sys.executable,
            str(ODOO_BIN),
            "--addons-path",
            ADDONS_PATH,
            "--data-dir",
            str(tmp_path / "data"),
            "--logfile",
            str(tmp_path / "odoo.log"),
            "--stop-after-init",
            "--no-http",
            "--max-cron-threads",
            "0",
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


@requires_pg
@requires_posix
class TestTheProcessExitCodeIsRead:
    """No process test read `returncode` before this one.

    Every lane in integration_tests.yml trusts it -- "odoo-bin exits non-zero
    when any test fails" -- and a status nothing asserts on is a status that
    can silently stop meaning that.
    """

    def test_a_plain_boot_that_stops_after_init_exits_zero(self, tmp_path):
        proc = _stop_after_init(tmp_path)
        assert proc.returncode == 0, (
            f"exit {proc.returncode}; stderr tail:\n{proc.stderr[-2000:]}"
        )
