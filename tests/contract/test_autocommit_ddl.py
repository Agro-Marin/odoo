"""Which database DDL PostgreSQL refuses inside a transaction block.

``odoo/service/db/lifecycle.py`` sets ``cr.connection.autocommit = True`` at five
places — in ``_create_empty_database``, ``_duplicate_database``,
``_drop_database`` (twice) and ``_rename_database`` — before issuing its
statement.  That line encodes an assumption about the SERVER, not about our code,
and psycopg opens a transaction implicitly on the first statement, so without it
the DDL arrives inside one.

The assumption was pinned by nothing.  A mock cannot pin it: a stubbed cursor
accepts whatever it is handed, which is the belief under test.  Measured here
against the real server, and the answer is not uniform — which is itself worth
recording, because it says which of those five lines is load-bearing and which is
consistency.
"""

import subprocess
import uuid

import pytest

from .conftest import requires_pg, requires_psql


def _in_transaction(sql: str) -> subprocess.CompletedProcess:
    """Run ``sql`` inside an explicit transaction block and report what happened."""
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
    """The three statements ``odoo.service.db`` issues against ``postgres``."""

    def test_create_database_is_refused_inside_a_transaction(self, scratch_name):
        """``_create_empty_database`` and ``_duplicate_database``.

        Without autocommit this is the error an operator sees instead of a new
        database, and it names the cause — which is why the defect would be
        caught quickly in production, and why nothing here noticed the line was
        untested.
        """
        proc = _in_transaction(f'CREATE DATABASE "{scratch_name}"')
        assert proc.returncode != 0
        assert "cannot run inside a transaction block" in proc.stderr, proc.stderr

    def test_drop_database_is_refused_inside_a_transaction(self, scratch_name):
        """``_drop_database``, both of its autocommit sites."""
        subprocess.run(
            ["createdb", "-T", "template0", scratch_name],
            check=True,
            capture_output=True,
        )
        proc = _in_transaction(f'DROP DATABASE "{scratch_name}"')
        assert proc.returncode != 0
        assert "cannot run inside a transaction block" in proc.stderr, proc.stderr

    def test_alter_database_rename_is_ALLOWED_inside_a_transaction(self, scratch_name):
        """``_rename_database`` — and this one does NOT need the flag.

        Recorded because the asymmetry is the useful part: four of the five
        autocommit assignments are load-bearing and this one is consistency.  If
        that ever changes (a server version that starts refusing it), this test
        is where it surfaces, rather than a rename failing in the field.
        """
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
        """Non-vacuity: ``_in_transaction`` must not report failure for everything."""
        proc = _in_transaction("SELECT 1")
        assert proc.returncode == 0, proc.stderr
