from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTaskSkillSearch(TransactionCase):
    """user_skill_ids read every skill an assignee ever recorded, so filtering
    tasks by skill matched people who had lost it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = date.today()
        skill_type = cls.env["hr.skill.type"].create({"name": "Task type"})
        level = cls.env["hr.skill.level"].create(
            {"name": "Able", "skill_type_id": skill_type.id, "level_progress": 60},
        )
        cls.welding, cls.painting = cls.env["hr.skill"].create(
            [
                {"name": "Welding", "skill_type_id": skill_type.id},
                {"name": "Painting", "skill_type_id": skill_type.id},
            ],
        )
        cls.employee = cls.env["hr.employee"].create({"name": "Task assignee"})
        cls.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": cls.employee.id,
                    "skill_id": cls.welding.id,
                    "skill_level_id": level.id,
                    "skill_type_id": skill_type.id,
                    "valid_from": today - relativedelta(years=1),
                },
                {
                    "employee_id": cls.employee.id,
                    "skill_id": cls.painting.id,
                    "skill_level_id": level.id,
                    "skill_type_id": skill_type.id,
                    "valid_from": today - relativedelta(years=1),
                    "valid_to": today - relativedelta(months=1),
                },
            ],
        )
        project = cls.env["project.project"].create({"name": "Skilled project"})
        cls.task = cls.env["project.task"].create(
            {
                "name": "Needs a welder",
                "project_id": project.id,
                "employee_ids": cls.employee.ids,
            },
        )
        cls.env.flush_all()

    def _tasks_with(self, skill_name):
        return self.env["project.task"].search(
            [("user_skill_ids", "ilike", skill_name), ("id", "=", self.task.id)]
        )

    def test_a_task_is_found_by_a_skill_its_assignee_holds(self):
        self.assertIn(self.welding, self.task.user_skill_ids.skill_id)
        self.assertEqual(self._tasks_with("Welding"), self.task)

    def test_a_task_is_not_found_by_a_skill_its_assignee_lost(self):
        self.assertNotIn(self.painting, self.task.user_skill_ids.skill_id)
        self.assertFalse(self._tasks_with("Painting"))
