import importlib.util
from pathlib import Path

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "1.1" / "pre-migrate.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("hr_skills_pre_migrate", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestValidFromBackfill(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = _load_migration()

    def test_the_discovery_query_runs_under_psycopg3(self):
        tables = self.migration._individual_skill_tables(self.env.cr)
        self.assertIn(
            "hr_employee_skill",
            tables,
            "the discovery query must run and find the mixin's own tables; "
            "'IN %s' is a syntax error under psycopg 3, which binds server-side "
            "-- the spelling that works is '= ANY(%s)' with a list",
        )
        self.assertIn("hr_job_skill", tables)

    def test_every_discovered_table_carries_the_mixin_columns(self):
        for table in self.migration._individual_skill_tables(self.env.cr):
            self.env.cr.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = ANY(%s)",
                (table, list(self.migration.INDIVIDUAL_SKILL_FIELDS)),
            )
            found = {name for (name,) in self.env.cr.fetchall()}
            self.assertEqual(
                found,
                set(self.migration.INDIVIDUAL_SKILL_FIELDS),
                f"{table} was discovered but does not carry the mixin's columns",
            )

    def test_a_null_valid_from_is_backfilled_from_create_date(self):
        skill_type = self.env["hr.skill.type"].create({"name": "Backfill type"})
        level = self.env["hr.skill.level"].create(
            {
                "name": "Backfill level",
                "skill_type_id": skill_type.id,
                "level_progress": 50,
            },
        )
        skill = self.env["hr.skill"].create(
            {"name": "Backfill skill", "skill_type_id": skill_type.id},
        )
        employee = self.env["hr.employee"].create({"name": "Backfill employee"})
        row = self.env["hr.employee.skill"].create(
            {
                "employee_id": employee.id,
                "skill_id": skill.id,
                "skill_level_id": level.id,
                "skill_type_id": skill_type.id,
            },
        )
        self.env.flush_all()

        self.env.cr.execute(
            "ALTER TABLE hr_employee_skill ALTER COLUMN valid_from DROP NOT NULL"
        )
        self.env.cr.execute(
            "UPDATE hr_employee_skill SET valid_from = NULL, "
            "create_date = '2020-03-04 00:00:00' WHERE id = %s",
            (row.id,),
        )

        self.migration.migrate(self.env.cr, "1.0")

        self.env.cr.execute(
            "SELECT valid_from FROM hr_employee_skill WHERE id = %s", (row.id,)
        )
        (backfilled,) = self.env.cr.fetchone()
        self.assertEqual(
            str(backfilled),
            "2020-03-04",
            "making valid_from required lets the ORM fill NULLs from the field "
            "default, which stamps the upgrade date onto a historical row; the "
            "migration must date the row from when it was recorded instead",
        )

    def test_a_fresh_install_is_left_alone(self):
        self.assertIsNone(self.migration.migrate(self.env.cr, None))
