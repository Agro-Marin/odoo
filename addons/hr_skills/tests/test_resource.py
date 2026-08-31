from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import Form
from odoo.tests.common import TransactionCase


class TestResourceSkills(TransactionCase):
    def test_availability_skills_infos_resource(self):
        user = self.env["res.users"].create(
            [
                {
                    "name": "Test user",
                    "login": "test",
                    "email": "test@odoo.perso",
                    "phone": "+32488990011",
                }
            ]
        )
        resource = self.env["resource.resource"].create(
            [
                {
                    "name": "Test resource",
                    "user_id": user.id,
                }
            ]
        )
        employee = self.env["hr.employee"].create(
            [
                {
                    "name": "Test employee",
                    "user_id": user.id,
                    "resource_id": resource.id,
                }
            ]
        )

        with Form(self.env["hr.skill.type"]) as skill_type:
            skill_type.name = "Best Music"
            for i in range(3):
                with skill_type.skill_ids.new() as skill:
                    skill.name = f"Fortunate Son {i}"
            for x in range(10):
                with skill_type.skill_level_ids.new() as level:
                    level.name = f"level {x}"
                    level.level_progress = x * 10
                    level.default_level = x % 2
        skill_type = skill_type.save()

        self.env["hr.employee.skill"].create(
            {
                "employee_id": employee.id,
                "skill_id": skill_type.skill_ids[2].id,
                "skill_level_id": skill_type.skill_level_ids[1].id,
                "skill_type_id": skill_type.id,
            }
        )
        self.assertEqual(resource.employee_skill_ids, employee.employee_skill_ids)

        default_levels = skill_type.skill_level_ids.filtered(
            lambda level: level.default_level
        )
        self.assertEqual(len(default_levels), 1)

    def test_the_popover_reads_only_the_skills_still_held(self):
        """The avatar card tags a resource's skills; lapsed ones are not skills.

        avatar_card_resource_popover_patch reads this field to build its tag
        list, and it read employee_skill_ids -- every row ever recorded -- so a
        skill the employee lost, and both versions of one that changed level,
        showed as current tags.
        """
        skill_type = self.env["hr.skill.type"].create({"name": "Popover type"})
        level = self.env["hr.skill.level"].create(
            {
                "name": "Popover level",
                "skill_type_id": skill_type.id,
                "level_progress": 50,
            },
        )
        lapsed, held = self.env["hr.skill"].create(
            [
                {"name": "Lapsed skill", "skill_type_id": skill_type.id},
                {"name": "Held skill", "skill_type_id": skill_type.id},
            ],
        )
        user = self.env["res.users"].create(
            {"name": "Popover user", "login": "popover.user"},
        )
        resource = self.env["resource.resource"].create(
            {"name": "Popover resource", "user_id": user.id},
        )
        employee = self.env["hr.employee"].create(
            {
                "name": "Popover employee",
                "user_id": user.id,
                "resource_id": resource.id,
            },
        )
        today = date.today()
        self.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": employee.id,
                    "skill_id": lapsed.id,
                    "skill_level_id": level.id,
                    "skill_type_id": skill_type.id,
                    "valid_from": today - relativedelta(months=8),
                    "valid_to": today - relativedelta(months=4),
                },
                {
                    "employee_id": employee.id,
                    "skill_id": held.id,
                    "skill_level_id": level.id,
                    "skill_type_id": skill_type.id,
                    "valid_from": today - relativedelta(months=2),
                },
            ],
        )
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(resource.current_employee_skill_ids.skill_id, held)
        self.assertIn(lapsed, resource.employee_skill_ids.skill_id)
