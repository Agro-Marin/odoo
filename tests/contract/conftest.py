import subprocess
import uuid

import pytest

from .._pg import (
    createdb_path,
    dependency_plugin,
    dropdb_path,
    pg_dump_path,
    pg_reachable,
    psql_path,
)

requires_pg = pytest.mark.requires_pg
requires_psql = pytest.mark.requires_psql
requires_pg_dump = pytest.mark.requires_pg_dump
requires_createdb = pytest.mark.requires_createdb


def _createdb_available() -> bool:
    return createdb_path() is not None and dropdb_path() is not None


REQUIREMENTS = {
    "requires_pg": (pg_reachable, "no reachable PostgreSQL (contract suite needs one)"),
    "requires_psql": (lambda: psql_path() is not None, "psql not on PATH"),
    "requires_pg_dump": (lambda: pg_dump_path() is not None, "pg_dump not on PATH"),
    "requires_createdb": (_createdb_available, "createdb/dropdb not on PATH"),
}

pytest_configure, _skip_without_dependencies = dependency_plugin(REQUIREMENTS)


@pytest.fixture(scope="session", autouse=True)
def odoo_config():
    from odoo.tools import config

    config.parse_config([], setup_logging=False)
    return config


@pytest.fixture(scope="session")
def scratch_db():
    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    if not _createdb_available():
        pytest.skip("createdb/dropdb not on PATH")
    name = f"odoo_contract_{uuid.uuid4().hex[:12]}"
    subprocess.run(
        [createdb_path(), "-T", "template0", name], check=True, capture_output=True
    )
    try:
        yield name
    finally:
        subprocess.run(
            [dropdb_path(), "--if-exists", "--force", name],
            check=False,
            capture_output=True,
        )


@pytest.fixture
def scratch_cursor(scratch_db):
    import odoo.db

    cr = odoo.db.db_connect(scratch_db).cursor()
    try:
        yield cr
    finally:
        cr.close()


@pytest.fixture
def run_psql(scratch_db):
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
        )

    return _run
