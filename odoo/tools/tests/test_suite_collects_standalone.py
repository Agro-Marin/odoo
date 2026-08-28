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

Derived rather than hand-kept, because a hand-kept list is the thing that goes
stale. It was one entry, ``odoo/tools/tests``, and three suites were broken when
this was widened: ``odoo/libs/_field_access/tests`` (a CI lane,
``unit_tests.yml``), ``odoo/libs/sql/tests`` (three files importing ``SQL`` from
the package), and ``odoo/libs/lint/tests``.

The set is the **union** of two, because neither alone is what a person names:

* every ``testpaths`` entry in ``pytest.ini`` -- what CI names, and what the
  file itself calls the Tier-1 suites;
* every directory whose ``conftest.py`` installs the stubs -- what makes a
  suite nameable in the first place, and where the shadowing can bite.
  ``odoo/libs/lint/tests`` is in the second set and not the first, which is
  exactly why the ``testpaths``-only version of this gate did not see it.

The stubs are not merely tolerable here, they are load-bearing, and it is worth
knowing why before anyone proposes deleting them. Measured: with
``odoo_rust`` uninstalled -- the shape of the ``orm/components`` lane, which
installs no Rust on purpose -- ``pytest odoo/orm/components/tests`` passes 400
tests under the stubs and cannot collect at all without them, because the real
import chain reaches ``odoo/init.py`` and that refuses to start without the
extension. The stubs are what make "Tier 1 needs no Rust and no framework"
true.
"""

import configparser
import functools
import pathlib
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _nameable_suites() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(_REPO_ROOT / "pytest.ini")
    suites = set(parser["pytest"]["testpaths"].split())
    assert suites, "pytest.ini declares no testpaths"

    for conftest in _REPO_ROOT.rglob("conftest.py"):
        if "stub_odoo_packages" in conftest.read_text(encoding="utf-8"):
            suites.add(conftest.parent.relative_to(_REPO_ROOT).as_posix())
    return sorted(suites)


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


@pytest.mark.parametrize("suite", _nameable_suites())
def test_the_suite_collects_when_named_on_its_own(suite: str) -> None:
    proc = _collect(suite)
    assert proc.returncode == 0, (
        f"`pytest {suite} --collect-only` exited {proc.returncode}. Something "
        f"under {suite} imports a package facade that the Tier-1 stubs shadow, "
        f"or reaches the framework at module scope. Import the leaf module "
        f"instead.\nstdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-2000:]}"
    )


@pytest.mark.parametrize("suite", _nameable_suites())
def test_collection_reports_no_errors(suite: str) -> None:
    proc = _collect(suite)
    assert "error" not in proc.stdout.rsplit("\n", 3)[-2].lower(), (
        f"collection errors while enumerating {suite}:\n{proc.stdout[-3000:]}"
    )
