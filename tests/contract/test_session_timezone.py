import subprocess
import uuid

import pytest

from .conftest import _createdb_available, createdb_path, dropdb_path, requires_pg

NON_UTC_ZONE = "Asia/Kathmandu"


@pytest.fixture(scope="module")
def non_utc_db():
    if not _createdb_available():
        pytest.skip("createdb/dropdb not on PATH")
    name = f"odoo_contract_tz_{uuid.uuid4().hex[:12]}"
    subprocess.run(
        [createdb_path(), "-T", "template0", name], check=True, capture_output=True
    )
    import psycopg

    with psycopg.connect(dbname="postgres", autocommit=True) as conn:
        conn.execute(f"ALTER DATABASE {name} SET TimeZone = '{NON_UTC_ZONE}'")
    try:
        yield name
    finally:
        import odoo.db

        odoo.db.close_db(name)
        subprocess.run(
            [dropdb_path(), "--if-exists", "--force", name],
            check=False,
            capture_output=True,
        )


def _show_timezone(dbname: str) -> str:
    import odoo.db

    with odoo.db.db_connect(dbname).cursor() as cr:
        cr.execute("SHOW TimeZone")
        return cr.fetchone()[0]


@requires_pg
class TestAForkSessionRunsInUtc:
    def test_a_raw_connection_sees_the_database_zone(self, non_utc_db):
        import psycopg

        with psycopg.connect(dbname=non_utc_db) as conn:
            zone = conn.execute("SHOW TimeZone").fetchone()[0]
        assert zone == NON_UTC_ZONE, "the fixture no longer produces a non-UTC session"

    def test_a_fork_cursor_is_utc_whatever_the_database_default(self, non_utc_db):
        assert _show_timezone(non_utc_db) == "UTC"

    def test_now_as_a_naive_timestamp_is_the_utc_wall_clock(self, non_utc_db):
        import odoo.db

        with odoo.db.db_connect(non_utc_db).cursor() as cr:
            cr.execute(
                "SELECT now()::timestamp = (now() AT TIME ZONE 'UTC'),"
                " CURRENT_DATE = (now() AT TIME ZONE 'UTC')::date"
            )
            assert cr.fetchone() == (True, True)

    def test_a_borrower_set_does_not_survive_the_return(self, non_utc_db):
        import odoo.db

        with odoo.db.db_connect(non_utc_db).cursor() as cr:
            cr.execute(f"SET TimeZone = '{NON_UTC_ZONE}'")
            cr.commit()
        assert _show_timezone(non_utc_db) == "UTC"

    def test_an_operator_pgoptions_zone_is_overridden(self, non_utc_db, monkeypatch):
        import odoo.db

        odoo.db.close_db(non_utc_db)
        monkeypatch.setenv("PGOPTIONS", f"-c TimeZone={NON_UTC_ZONE}")
        try:
            assert _show_timezone(non_utc_db) == "UTC"
        finally:
            odoo.db.close_db(non_utc_db)
