"""Fixtures for the real-dependency contract suite (see ``__init__``-less
package docstring in ``test_pg_connect_contract.py``).

Everything here skips rather than fails when the dependency is absent, so the
suite is safe to run in a container without PostgreSQL — but it must NOT be
silently skipped in CI, or it stops being evidence.  ``test_dependencies_are_
present`` in ``test_pg_connect_contract.py`` is the canary for that.
"""

import os
import shutil
import subprocess
import uuid

import pytest


def _pg_reachable() -> bool:
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        return False
    try:
        psycopg.connect(dbname="postgres", connect_timeout=5).close()
    except Exception:
        return False
    return True


PG_REACHABLE = _pg_reachable()
PSQL = shutil.which("psql")
PG_DUMP = shutil.which("pg_dump")

requires_pg = pytest.mark.skipif(
    not PG_REACHABLE, reason="no reachable PostgreSQL (contract suite needs one)"
)
requires_psql = pytest.mark.skipif(not PSQL, reason="psql not on PATH")
requires_pg_dump = pytest.mark.skipif(not PG_DUMP, reason="pg_dump not on PATH")


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
    if not PG_REACHABLE:
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


@pytest.fixture()
def run_psql(scratch_db):
    """Run ``psql -f <file>`` against the scratch DB the way ``restore_db`` does.

    Same flags as the real restore path (``-q -v ON_ERROR_STOP=1 -f``), because
    a differential test that used different flags would be measuring a different
    program than the one shipped.
    """

    def _run(sql_path):
        return subprocess.run(
            [
                PSQL,
                "-d",
                scratch_db,
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
