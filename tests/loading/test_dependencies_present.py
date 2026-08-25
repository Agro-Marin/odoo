"""Canary: this suite must not be silently skipped in CI.

The version this replaces lived in ``test_load_modules_phases.py`` and was
inert twice over:

* it skipped on ``not pg_reachable()`` — the very condition it exists to
  detect — so a missing PostgreSQL made the canary skip alongside everything
  it was guarding;
* that module carries ``pytestmark = pytest.mark.requires_pg``, so the
  conftest's autouse fixture skipped it first regardless of its body.

Measured before this file existed: with PostgreSQL unreachable,
``pytest tests/loading -q`` reported **10 skipped, exit 0** — a blocking
workflow step that ran nothing and said success.

No ``pytestmark`` here, and no ``requires_*`` marker on the test, for the same
reason ``tests/process/test_dependencies_present.py`` has none.
"""

from .._pg import assert_dependencies_present
from .conftest import REQUIREMENTS


def test_dependencies_are_present():
    assert_dependencies_present(REQUIREMENTS)
