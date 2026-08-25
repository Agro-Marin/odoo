"""``odoo/tools/tests`` must stay runnable on its own.

``pytest odoo/tools/tests`` is the per-path form CI uses for every other Tier-1
suite (``.github/workflows/unit_tests.yml``). Naming the package narrows the
Tier-1 stub set to ``odoo`` and ``odoo.tools``, so a module under ``odoo/tools``
that reaches back into the framework at import time cannot be imported: the
chain loads the real framework, which ends at ``from odoo.tools import SQL``
against the stub. pytest then aborts the whole run at collection, which hides
every other test in the suite behind an unrelated import.

This asserts *collection*, not that the suite passes. Failures under this
invocation are tracked on their own; what must never come back is a suite that
cannot even be enumerated.
"""

import pathlib
import subprocess
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SUITE = "odoo/tools/tests"


def _collect() -> subprocess.CompletedProcess:
    # --collect-only, so the child imports every module but runs no test and
    # cannot re-enter this one.
    return subprocess.run(
        [sys.executable, "-m", "pytest", _SUITE, "--collect-only", "-q"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_the_suite_collects_when_named_on_its_own():
    proc = _collect()
    assert proc.returncode == 0, (
        f"`pytest {_SUITE} --collect-only` exited {proc.returncode}. A module "
        f"under odoo/tools imports the framework at module scope again.\n"
        f"stdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-2000:]}"
    )


def test_collection_reports_no_errors():
    proc = _collect()
    assert "errors during collection" not in proc.stdout, (
        f"collection errors while enumerating {_SUITE}:\n{proc.stdout[-3000:]}"
    )
