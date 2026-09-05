import importlib.util
from pathlib import Path

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "1.2" / "pre-migrate.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("hr_skills_pre_migrate_12", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestSkillLevelTypeMigration(TransactionCase):
    """skill_type_id became required on hr.skill.level. The migration removes
    the levels that predate that and have no type, unless something still points
    at one -- a level nobody references can never be picked, since every picker
    reads skill_type_id.skill_level_ids."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = _load_migration()

    def _make_orphan(self, name):
        self.env.cr.execute(
            "ALTER TABLE hr_skill_level ALTER COLUMN skill_type_id DROP NOT NULL"
        )
        self.env.cr.execute(
            "INSERT INTO hr_skill_level (name, level_progress) VALUES (%s, 10) "
            "RETURNING id",
            (name,),
        )
        return self.env.cr.fetchone()[0]

    def test_an_unreferenced_orphan_is_deleted(self):
        orphan = self._make_orphan("free orphan")
        self.migration.migrate(self.env.cr, "1.1")
        self.env.cr.execute("SELECT id FROM hr_skill_level WHERE id = %s", (orphan,))
        self.assertFalse(self.env.cr.fetchone(), "a level nobody can pick is removed")

    def test_a_referenced_orphan_is_kept(self):
        orphan = self._make_orphan("used orphan")
        skill_type = self.env["hr.skill.type"].create({"name": "Ref type"})
        skill = self.env["hr.skill"].create(
            {"name": "Ref skill", "skill_type_id": skill_type.id},
        )
        employee = self.env["hr.employee"].create({"name": "Ref employee"})
        self.env.cr.execute(
            "INSERT INTO hr_employee_skill "
            "(employee_id, skill_id, skill_level_id, skill_type_id, valid_from) "
            "VALUES (%s, %s, %s, %s, CURRENT_DATE)",
            (employee.id, skill.id, orphan, skill_type.id),
        )

        self.migration.migrate(self.env.cr, "1.1")

        self.env.cr.execute("SELECT id FROM hr_skill_level WHERE id = %s", (orphan,))
        self.assertTrue(
            self.env.cr.fetchone(),
            "a referenced level is kept for the admin to fix by hand rather than "
            "deleted out from under the row that uses it",
        )

    def test_the_discovery_finds_the_referencing_columns(self):
        pairs = self.migration._columns_pointing_at_levels(self.env.cr)
        self.assertIn(("hr_employee_skill", "skill_level_id"), pairs)
        self.assertIn(("hr_job_skill", "skill_level_id"), pairs)
