"""Canary: this suite must not be silently skipped in CI.

Every test in ``tests/process`` carries ``@requires_pg`` / ``@requires_posix``,
which the conftest resolves into a skip when the dependency is absent.  That is
right on a developer's machine and wrong in CI: measured with PostgreSQL
pointed at a black hole, ``pytest tests/process -q`` reported **7 skipped, exit
0** — a blocking workflow step that ran nothing and said success.

``service_suites.yml`` already sets ``ODOO_CONTRACT_REQUIRE_DEPS=1`` at job
level, for all three of its steps, with the comment "This turns a missing
dependency into a FAILURE here".  Until this file existed that was true of one
step out of three: only ``tests/contract`` read the variable.

This module deliberately carries **no** ``pytestmark`` and no ``requires_*``
marker.  A canary the suite's own skip fixture can skip guards nothing — which
is precisely how ``tests/loading``'s version came to be inert.
"""

from .._pg import assert_dependencies_present
from .conftest import REQUIREMENTS


def test_dependencies_are_present():
    assert_dependencies_present(REQUIREMENTS)
