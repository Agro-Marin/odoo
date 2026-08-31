from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import tagged

from .common import SkillsCase


@tagged("post_install", "-at_install")
class TestMultiRecordSkillWrite(SkillsCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = date.today()
        cls.novice_holder, cls.newcomer = cls.env["hr.employee"].create(
            [{"name": "Already plays"}, {"name": "Brand new"}],
        )

    def _piano_rows(self, employee):
        return employee.employee_skill_ids.filtered(
            lambda skill: skill.skill_id == self.skill_piano
        )

    def test_skill_lands_on_every_employee(self):
        (self.novice_holder | self.newcomer).write(
            {
                "employee_skill_ids": [
                    [
                        0,
                        0,
                        {
                            "skill_id": self.skill_piano.id,
                            "skill_level_id": self.level_novice.id,
                            "skill_type_id": self.skill_type.id,
                        },
                    ]
                ],
            },
        )

        for employee in (self.novice_holder, self.newcomer):
            self.assertEqual(len(self._piano_rows(employee)), 1, employee.name)

    def test_existing_skill_is_archived_on_every_employee(self):
        self.env["hr.employee.skill"].create(
            {
                "employee_id": self.novice_holder.id,
                "skill_id": self.skill_piano.id,
                "skill_level_id": self.level_novice.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": self.today - relativedelta(months=2),
            },
        )

        (self.novice_holder | self.newcomer).write(
            {
                "employee_skill_ids": [
                    [
                        0,
                        0,
                        {
                            "skill_id": self.skill_piano.id,
                            "skill_level_id": self.level_expert.id,
                            "skill_type_id": self.skill_type.id,
                        },
                    ]
                ],
            },
        )

        superseded = self._piano_rows(self.novice_holder).filtered("valid_to")
        self.assertEqual(superseded.skill_level_id, self.level_novice)
        self.assertEqual(superseded.valid_to, self.today - relativedelta(days=1))

        for employee in (self.novice_holder, self.newcomer):
            live = self._piano_rows(employee).filtered(lambda skill: not skill.valid_to)
            self.assertEqual(len(live), 1, employee.name)
            self.assertEqual(live.skill_level_id, self.level_expert, employee.name)

    def test_a_line_is_edited_only_on_the_employee_that_owns_it(self):
        owned = self.env["hr.employee.skill"].create(
            {
                "employee_id": self.novice_holder.id,
                "skill_id": self.skill_guitar.id,
                "skill_level_id": self.level_novice.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": self.today,
            },
        )

        (self.novice_holder | self.newcomer).write(
            {
                "employee_skill_ids": [
                    [1, owned.id, {"skill_level_id": self.level_expert.id}]
                ],
            },
        )

        rows = self.novice_holder.employee_skill_ids.filtered(
            lambda skill: skill.skill_id == self.skill_guitar
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.skill_level_id, self.level_expert)
        self.assertFalse(self.newcomer.employee_skill_ids)

    def test_the_mixin_archives_across_every_replay_target(self):
        """The transformation is a public extension point for other modules.

        hr.employee and hr.job now hand it one record at a time, but
        hr_recruitment_skills and hr_appraisal_skills still pass the whole
        recordset and let the ORM replay one command against each. The archive
        of the skill each of those records already holds has to be resolved
        across all of them, not against whichever id reached the vals.
        """
        self.env["hr.employee.skill"].create(
            {
                "employee_id": self.novice_holder.id,
                "skill_id": self.skill_piano.id,
                "skill_level_id": self.level_novice.id,
                "skill_type_id": self.skill_type.id,
                "valid_from": self.today - relativedelta(months=2),
            },
        )
        self.env.flush_all()

        commands = self.env["hr.employee.skill"]._get_transformed_commands(
            [
                [
                    0,
                    0,
                    {
                        "skill_id": self.skill_piano.id,
                        "skill_level_id": self.level_expert.id,
                        "skill_type_id": self.skill_type.id,
                    },
                ]
            ],
            self.novice_holder | self.newcomer,
        )

        archives = [command for command in commands if command[0] in (1, 2)]
        creates = [command for command in commands if command[0] == 0]
        self.assertEqual(
            len(creates), 1, "one CREATE, replayed by the ORM against each record"
        )
        self.assertTrue(
            archives,
            "the skill novice_holder already holds must be archived; without it "
            "the replayed CREATE collides with it and the constraint rejects "
            "the whole write",
        )
        self.assertEqual(archives[0][2]["valid_to"], self.today - relativedelta(days=1))

    def test_creating_an_employee_without_skills_touches_no_skill_field(self):
        employee = self.env["hr.employee"].create({"name": "No skills at all"})
        self.assertFalse(employee.employee_skill_ids)
