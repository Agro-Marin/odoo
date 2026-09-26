import subprocess
import uuid
from datetime import UTC, datetime

import pytest

from .conftest import _createdb_available, createdb_path, dropdb_path, requires_pg

CLUSTER_ZONE = "America/Mexico_City"

SCHEMA = """
    CREATE TABLE ir_config_parameter (
        id serial PRIMARY KEY, key varchar UNIQUE, value text,
        create_uid integer, write_uid integer,
        create_date timestamp, write_date timestamp
    );
    CREATE TABLE ir_module_module (
        id serial PRIMARY KEY, name varchar, write_date timestamp
    );
    CREATE TABLE phone_number (
        id serial PRIMARY KEY, name varchar,
        create_date timestamp, write_date timestamp
    );
    CREATE TABLE res_partner (
        id serial PRIMARY KEY, name varchar,
        create_date timestamp, write_date timestamp
    );
    CREATE TABLE orm_signaling_registry (
        id serial PRIMARY KEY, date timestamp DEFAULT now()
    );
    CREATE TABLE stray_clock (id serial PRIMARY KEY, stamp timestamp DEFAULT now());
"""


@pytest.fixture
def pre_fix_db():
    if not _createdb_available():
        pytest.skip("createdb/dropdb not on PATH")
    import psycopg

    name = f"odoo_contract_zone_repair_{uuid.uuid4().hex[:12]}"
    subprocess.run(
        [createdb_path(), "-T", "template0", name], check=True, capture_output=True
    )
    with psycopg.connect(dbname="postgres", autocommit=True) as conn:
        conn.execute(f"ALTER DATABASE {name} SET TimeZone = '{CLUSTER_ZONE}'")
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


def _seed_before_the_fix(dbname: str) -> None:
    import psycopg

    with psycopg.connect(dbname=dbname) as conn:
        assert conn.execute("SHOW TimeZone").fetchone()[0] == CLUSTER_ZONE
        conn.execute(SCHEMA)
        conn.commit()
        conn.execute("""
            INSERT INTO phone_number (name, create_date, write_date)
                 VALUES ('migrated', now(), now()),
                        ('orm', now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC');
            INSERT INTO res_partner (name, create_date, write_date)
                 VALUES ('migrated', now(), now());
            INSERT INTO ir_module_module (name, write_date)
                 VALUES ('crm', now() AT TIME ZONE 'UTC');
            INSERT INTO orm_signaling_registry DEFAULT VALUES;
        """)
        conn.commit()
        conn.execute(
            "INSERT INTO phone_number (name, create_date, write_date)"
            " VALUES ('unwitnessed', now(), now())"
        )
        conn.commit()


def _values(dbname: str, table: str) -> dict:
    import odoo.db

    with odoo.db.db_connect(dbname).cursor() as cr:
        cr.execute(f"SELECT name, create_date, write_date FROM {table}")
        return {name: (created, written) for name, created, written in cr.fetchall()}


def _crm_instant(dbname: str) -> datetime:
    import odoo.db

    with odoo.db.db_connect(dbname).cursor() as cr:
        cr.execute("SELECT write_date FROM ir_module_module WHERE name = 'crm'")
        return cr.fetchone()[0]


def _deploy_then_write_through_the_fork(dbname: str) -> datetime:
    import odoo.db

    until = datetime.now(UTC)
    with odoo.db.db_connect(dbname).cursor() as cr:
        cr.execute(
            "INSERT INTO phone_number (name, create_date, write_date)"
            " VALUES ('after', now(), now())"
        )
        cr.commit()
    return until


def _plan(dbname: str, until: datetime):
    import odoo.db
    from odoo.modules import sql_zone_repair

    cr = odoo.db.db_connect(dbname).cursor()
    return cr, sql_zone_repair.plan_repair(cr, CLUSTER_ZONE, until)


def _column(plan, name: str):
    return next(p for p in plan.columns if p.column.name == name)


@requires_pg
class TestTheRepairMovesOnlyWitnessedSqlClockValues:
    def test_a_pre_fix_session_stored_the_cluster_wall_clock(self, pre_fix_db):
        _seed_before_the_fix(pre_fix_db)
        phones = _values(pre_fix_db, "phone_number")
        offset = _crm_instant(pre_fix_db) - phones["migrated"][0]
        assert offset.total_seconds() == 6 * 3600
        assert phones["orm"][0] == _crm_instant(pre_fix_db)

    def test_the_probe_reads_the_zone_a_pre_fix_session_got(self, pre_fix_db):
        from odoo.modules import sql_zone_repair

        probe = sql_zone_repair.probe_session_zone(pre_fix_db)
        assert (probe.zone, probe.source) == (CLUSTER_ZONE, "database")
        assert "TimeZone=UTC" not in probe.options

    def test_the_dry_run_counts_and_writes_nothing(self, pre_fix_db):
        _seed_before_the_fix(pre_fix_db)
        until = _deploy_then_write_through_the_fork(pre_fix_db)
        before = _values(pre_fix_db, "phone_number")
        cr, plan = _plan(pre_fix_db, until)
        try:
            created = _column(plan, "phone_number.create_date")
            assert (created.status, created.in_window, created.witnessed) == (
                "repair",
                2,
                1,
            ), "the ORM row reads later than the deploy's wall clock, so it is out"
            assert created.samples == [
                (before["migrated"][0], _crm_instant(pre_fix_db))
            ]
            assert created.unwitnessed_samples == [before["unwitnessed"][0]]
            signaling = _column(plan, "orm_signaling_registry.date")
            assert (signaling.status, signaling.in_window) == ("report", 1)
            assert _column(plan, "wallet_card.create_date").status == "absent"
            assert ("stray_clock", "stamp", "now()", False) in plan.default_clocks
            assert (
                "orm_signaling_registry",
                "date",
                "now()",
                True,
            ) in plan.default_clocks
            assert plan.to_repair == 4
        finally:
            cr.rollback()
            cr.close()
        assert _values(pre_fix_db, "phone_number") == before

    def test_apply_moves_the_sql_rows_to_the_orm_instant_and_nothing_else(
        self, pre_fix_db
    ):
        from odoo.modules import sql_zone_repair

        _seed_before_the_fix(pre_fix_db)
        until = _deploy_then_write_through_the_fork(pre_fix_db)
        before = _values(pre_fix_db, "phone_number")
        cr, plan = _plan(pre_fix_db, until)
        try:
            assert sql_zone_repair.apply_repair(cr, plan)
            cr.commit()
        finally:
            cr.close()
        after = _values(pre_fix_db, "phone_number")
        crm = _crm_instant(pre_fix_db)
        assert after["migrated"] == (crm, crm)
        assert _values(pre_fix_db, "res_partner")["migrated"] == (crm, crm)
        for untouched in ("orm", "unwitnessed", "after"):
            assert after[untouched] == before[untouched], untouched

        cr, plan = _plan(pre_fix_db, until)
        try:
            assert _column(plan, "phone_number.create_date").witnessed == 0
            guard = sql_zone_repair.read_guard(cr)
            assert guard["repaired"]["phone_number.create_date"] == 1
            with pytest.raises(RuntimeError, match="already ran"):
                sql_zone_repair.apply_repair(cr, plan)
        finally:
            cr.rollback()
            cr.close()

    def test_one_failing_column_rolls_the_whole_repair_back(self, pre_fix_db):
        import odoo.db
        from odoo.modules import sql_zone_repair

        _seed_before_the_fix(pre_fix_db)
        with odoo.db.db_connect(pre_fix_db).cursor() as cr:
            cr.execute("""
                CREATE FUNCTION refuse() RETURNS trigger LANGUAGE plpgsql AS
                $$ BEGIN RAISE EXCEPTION 'partner rows are frozen'; END $$;
                CREATE TRIGGER frozen BEFORE UPDATE ON res_partner
                   FOR EACH ROW EXECUTE FUNCTION refuse();
            """)
            cr.commit()
        until = _deploy_then_write_through_the_fork(pre_fix_db)
        before = _values(pre_fix_db, "phone_number")
        cr, plan = _plan(pre_fix_db, until)
        try:
            assert not sql_zone_repair.apply_repair(cr, plan)
            failed = [p.column.name for p in plan.columns if p.error]
            assert failed == ["res_partner.create_date", "res_partner.write_date"]
            assert _column(plan, "phone_number.create_date").repaired == 1
        finally:
            cr.rollback()
            cr.close()
        assert _values(pre_fix_db, "phone_number") == before
        with odoo.db.db_connect(pre_fix_db).cursor() as cr:
            assert sql_zone_repair.read_guard(cr) is None
