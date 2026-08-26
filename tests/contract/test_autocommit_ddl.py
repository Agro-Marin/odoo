import subprocess
import uuid

import pytest

from .conftest import requires_pg, requires_psql


def _in_transaction(sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "psql",
            "-d",
            "postgres",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f"BEGIN; {sql}; COMMIT;",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def scratch_name():
    name = f"odoo_ac_{uuid.uuid4().hex[:12]}"
    yield name
    for candidate in (name, f"{name}_renamed"):
        subprocess.run(
            ["dropdb", "--if-exists", "--force", candidate],
            check=False,
            capture_output=True,
        )


@requires_pg
@requires_psql
class TestDatabaseDdlNeedsAutocommit:
    def test_create_database_is_refused_inside_a_transaction(self, scratch_name):
        proc = _in_transaction(f'CREATE DATABASE "{scratch_name}"')
        assert proc.returncode != 0
        assert "cannot run inside a transaction block" in proc.stderr, proc.stderr

    def test_drop_database_is_refused_inside_a_transaction(self, scratch_name):
        subprocess.run(
            ["createdb", "-T", "template0", scratch_name],
            check=True,
            capture_output=True,
        )
        proc = _in_transaction(f'DROP DATABASE "{scratch_name}"')
        assert proc.returncode != 0
        assert "cannot run inside a transaction block" in proc.stderr, proc.stderr

    def test_alter_database_rename_is_ALLOWED_inside_a_transaction(self, scratch_name):
        subprocess.run(
            ["createdb", "-T", "template0", scratch_name],
            check=True,
            capture_output=True,
        )
        proc = _in_transaction(
            f'ALTER DATABASE "{scratch_name}" RENAME TO "{scratch_name}_renamed"'
        )
        assert proc.returncode == 0, proc.stderr

    def test_the_probe_would_notice_a_statement_that_succeeds(self, scratch_name):
        proc = _in_transaction("SELECT 1")
        assert proc.returncode == 0, proc.stderr
