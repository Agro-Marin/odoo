"""Fixtures for the real-dependency contract suite (see ``__init__``-less
package docstring in ``test_pg_connect_contract.py``).

Everything here skips rather than fails when the dependency is absent, so the
suite is safe to run in a container without PostgreSQL — but it must NOT be
silently skipped in CI, or it stops being evidence.  ``test_dependencies_are_
present`` in ``test_pg_connect_contract.py`` is the canary for that.
"""

import os
import subprocess
import uuid

import pytest

from .._pg import pg_dump_path, pg_reachable, psql_path

# Plain markers, NOT ``skipif`` conditions.  A ``skipif`` argument is evaluated
# when the decorator runs — i.e. at import, during collection — which made a
# mere ``--collect-only`` pay a real connect attempt (10.57 s with PostgreSQL
# unreachable; see ``tests/_pg``).  The autouse fixture below resolves each
# marker at SETUP instead, so a collected-but-unrun suite probes nothing.
requires_pg = pytest.mark.requires_pg
requires_psql = pytest.mark.requires_psql
requires_pg_dump = pytest.mark.requires_pg_dump

_REQUIREMENTS = {
    "requires_pg": (pg_reachable, "no reachable PostgreSQL (contract suite needs one)"),
    "requires_psql": (lambda: psql_path() is not None, "psql not on PATH"),
    "requires_pg_dump": (lambda: pg_dump_path() is not None, "pg_dump not on PATH"),
}


def pytest_configure(config):
    for name in _REQUIREMENTS:
        config.addinivalue_line("markers", f"{name}: needs that external dependency")


@pytest.fixture(autouse=True)
def _skip_without_dependencies(request):
    """Skip a test whose external dependency is absent — resolved lazily."""
    for name, (available, reason) in _REQUIREMENTS.items():
        if request.node.get_closest_marker(name) and not available():
            pytest.skip(reason)


@pytest.fixture(scope="session", autouse=True)
def odoo_config():
    """Initialise ``odoo.tools.config`` once.

    ``odoo.db.db_connect`` reads connection settings from it.  Parsed with an
    empty argv so the suite uses the environment's own PG defaults (peer auth as
    the OS user) rather than any particular workspace config file.
    """
    from odoo.tools import config

    config.parse_config([], setup_logging=False)
    return config


@pytest.fixture(scope="session")
def scratch_db():
    """A disposable database, dropped at the end of the session.

    Created from ``template0`` so it carries nothing that could mask a contract
    difference, and named uniquely so a parallel run or a leftover from a
    crashed session cannot collide.
    """
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    name = f"odoo_contract_{uuid.uuid4().hex[:12]}"
    subprocess.run(
        ["createdb", "-T", "template0", name], check=True, capture_output=True
    )
    try:
        yield name
    finally:
        subprocess.run(
            ["dropdb", "--if-exists", "--force", name], check=False, capture_output=True
        )


@pytest.fixture
def run_psql(scratch_db):
    """Run ``psql -f <file>`` against the scratch DB the way ``restore_db`` does.

    Same flags as the real restore path (``-X -q -v ON_ERROR_STOP=1 -f``),
    because a differential test that used different flags would be measuring a
    different program than the one shipped — including ``-X``, without which a
    host ``psqlrc`` could flip ``ON_ERROR_STOP`` in both the fixture and
    production identically and hide the very defect the suite exists to catch.
    """

    def _run(sql_path):
        return subprocess.run(
            [
                psql_path(),
                "-d",
                scratch_db,
                "-X",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                str(sql_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PGDATABASE": scratch_db},
        )

    return _run
