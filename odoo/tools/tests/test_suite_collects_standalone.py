"""Every Tier-1 testpath must stay runnable when it is named on its own.

``pytest <testpath>`` is the per-path form CI uses (``unit_tests.yml``), and it
is the form anyone iterating on one area reaches for. It is also the *only* form
in which the Tier-1 stubs are in force: with no path on the command line pytest
loads the initial conftests first and imports every parent package for real, so
every ``_stub_package`` call is a no-op and the bare run cannot see a violation
the named run trips over.

Naming a package narrows the stub set to its ancestors, and a stub carries only
``__path__`` -- its ``__init__.py`` never runs. So a test module under it must
import from the **leaf module**, never from the package facade:
``from odoo.libs.sql.builder import SQL``, not ``from odoo.libs.sql import
SQL``. The second resolves against a module with no attributes and aborts the
whole run at collection, which hides every other test in the suite behind one
unrelated import.

This asserts *collection*, not that the suite passes. Failures under this
invocation are tracked on their own; what must never come back is a suite that
cannot even be enumerated.

Parametrised over `pytest.ini` rather than over a hand-kept list: the list is
the thing that goes stale. It was one entry, ``odoo/tools/tests``, and two
other lanes were broken at the time this was widened --
``odoo/libs/_field_access/tests`` (a CI lane, ``unit_tests.yml``) and
``odoo/libs/sql/tests``, three files each importing ``SQL`` from the package.
"""

import configparser
import functools
import pathlib
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _testpaths() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(_REPO_ROOT / "pytest.ini")
    paths = parser["pytest"]["testpaths"].split()
    assert paths, "pytest.ini declares no testpaths"
    return paths


@functools.cache
def _collect(suite: str) -> subprocess.CompletedProcess:
    # --collect-only, so the child imports every module but runs no test and
    # cannot re-enter this one.  Cached: the two assertions below share one
    # subprocess per suite instead of paying for it twice.
    return subprocess.run(
        [sys.executable, "-m", "pytest", suite, "--collect-only", "-q"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("suite", _testpaths())
def test_the_suite_collects_when_named_on_its_own(suite: str) -> None:
    proc = _collect(suite)
    assert proc.returncode == 0, (
        f"`pytest {suite} --collect-only` exited {proc.returncode}. Something "
        f"under {suite} imports a package facade that the Tier-1 stubs shadow, "
        f"or reaches the framework at module scope. Import the leaf module "
        f"instead.\nstdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-2000:]}"
    )


@pytest.mark.parametrize("suite", _testpaths())
def test_collection_reports_no_errors(suite: str) -> None:
    proc = _collect(suite)
    assert "error" not in proc.stdout.rsplit("\n", 3)[-2].lower(), (
        f"collection errors while enumerating {suite}:\n{proc.stdout[-3000:]}"
    )
