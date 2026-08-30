import datetime

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from lxml import etree

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


class TestEmployeeSkills(TransactionCase):
    @classmethod
    def _create_skill_types(cls, vals_list):
        skill_types = cls.env["hr.skill.type"]
        for vals in vals_list:
            with Form(cls.env["hr.skill.type"]) as skill_type_form:
                skill_type_form.name = vals["name"]
                skill_type_form.is_certification = vals.get("certificate", False)
                for skill_val in vals["skills"]:
                    with skill_type_form.skill_ids.new() as skill:
                        skill.name = skill_val["name"]
                for level_val in vals["levels"]:
                    with skill_type_form.skill_level_ids.new() as level:
                        level.name = level_val["name"]
                        level.level_progress = level_val["level_progress"]
            skill_types += skill_type_form.save()
        return skill_types

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.skipTest(cls, "To be reintroduced post 18.4 freeze")
        cls.employee = cls.env["hr.employee"].create(
            [
                {"name": "Test Employee"},
            ]
        )
        cls.certification, cls.language = cls._create_skill_types(
            [
                {
                    "name": "Certificate",
                    "certificate": True,
                    "skills": [
                        {"name": "Odoo"},
                        {"name": "Scrum"},
                    ],
                    "levels": [
                        {"name": "20%", "level_progress": 20},
                        {"name": "50%", "level_progress": 50},
                        {"name": "70%", "level_progress": 70},
                        {"name": "100%", "level_progress": 100},
                    ],
                },
                {
                    "name": "Languages",
                    "skills": [
                        {"name": "Arabic"},
                        {"name": "English"},
                        {"name": "French"},
                    ],
                    "levels": [
                        {"name": "A1", "level_progress": 10},
                        {"name": "A2", "level_progress": 30},
                        {"name": "B1", "level_progress": 50},
                        {"name": "B2", "level_progress": 70},
                        {"name": "C1", "level_progress": 90},
                        {"name": "C2", "level_progress": 100},
                    ],
                },
            ]
        )

        # |-------------------------------|  |----------------------------------|
        # |           Skills              |  |              Level               |
        # |-------------------------------|  |----------------------------------|---------------------------------|
        # | Id  |  Skill Type  |   Name   |  |   Id  |  Skill Type  |   Name    | Index (in skill_type.level_ids) |
        # |   1 |  Certificate |     Odoo |  |     1 |  Certificate |       20% |                               0 |
        # |   2 |  Certificate |    Scrum |  |     2 |  Certificate |       50% |                               1 |
        # |     |              |          |  |     3 |  Certificate |       70% |                               2 |
        # |     |              |          |  |     4 |  Certificate |      100% |                               3 |
        # |-------------------------------|  |----------------------------------|---------------------------------|
        # |   2 |    Languages |  Arabic  |  |     5 |    Languages |        A1 |                               0 |
        # |   3 |    Languages | English  |  |     6 |    Languages |        A2 |                               1 |
        # |   4 |    Languages |  French  |  |     7 |    Languages |        B1 |                               2 |
        # |     |              |          |  |     8 |    Languages |        B2 |                               3 |
        # |     |              |          |  |     9 |    Languages |        C1 |                               4 |
        # |     |              |          |  |    10 |    Languages |        C2 |                               5 |
        # |-------------------------------|  |----------------------------------|---------------------------------|

        # |-------------------------------------------------------------------------------------|
        # |                                Employee Skill                                       |
        # |-------------------------------------------------------------------------------------|
        # |  Id  |  Skill Type  |  Skill  |  Level  | Certificate  |  Start Date  |  Stop Date  |
        # |    1 |  Certificate |    Odoo |     50% |        True  |     24-03-02 |           - |
        # |    2 |  Certificate |    Odoo |     20% |        True  |     24-01-01 |    24-04-01 | <- not present in current_employee_skill (because a valid certification for this skill exist)
        # |    3 |    Languages | English |     A2  |       False  |     24-01-01 |           - |
        # |    4 |    Languages |  Arabic |     A2  |       False  |     24-02-01 |           - |
        # |    4 |    Languages |  Arabic |     A1  |       False  |     24-01-01 |    24-01-31 | <- not present in current_employee_skill (because this regular skill is expired)
        # |-------------------------------------------------------------------------------------|

        cls.line1, cls.line2, cls.line3, cls.line4, cls.line5 = cls.env[
            "hr.employee.skill"
        ].create(
            [
                {
                    "skill_type_id": cls.certification.id,
                    "skill_id": cls.certification.skill_ids[0].id,
                    "skill_level_id": cls.certification.skill_level_ids[1].id,
                    "employee_id": cls.employee.id,
                    "valid_from": datetime.date(2024, 3, 2),
                },
                {
                    "skill_type_id": cls.certification.id,
                    "skill_id": cls.certification.skill_ids[0].id,
                    "skill_level_id": cls.certification.skill_level_ids[0].id,
                    "employee_id": cls.employee.id,
                    "valid_from": datetime.date(2024, 1, 1),
                    "valid_to": datetime.date(2024, 4, 1),
                },
                {
                    "skill_type_id": cls.language.id,
                    "skill_id": cls.language.skill_ids[1].id,
                    "skill_level_id": cls.language.skill_level_ids[1].id,
                    "employee_id": cls.employee.id,
                    "valid_from": datetime.date(2024, 1, 1),
                },
                {
                    "skill_type_id": cls.language.id,
                    "skill_id": cls.language.skill_ids[0].id,
                    "skill_level_id": cls.language.skill_level_ids[1].id,
                    "employee_id": cls.employee.id,
                    "valid_from": datetime.date(2024, 2, 1),
                },
                {
                    "skill_type_id": cls.language.id,
                    "skill_id": cls.language.skill_ids[0].id,
                    "skill_level_id": cls.language.skill_level_ids[0].id,
                    "employee_id": cls.employee.id,
                    "valid_from": datetime.date(2024, 1, 1),
                    "valid_to": datetime.date(2024, 1, 31),
                },
            ]
        )

    def test_add_english_b1(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.language
            employee_skill_form.skill_id = self.language.skill_ids[1]
            employee_skill_form.skill_level_id = self.language.skill_level_ids[2]

        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertEqual(len(self.employee.employee_skill_ids.ids), 6)
        self.assertEqual(new_employee_skill.valid_from, fields.Date.today())
        self.assertEqual(
            self.line3.valid_to, fields.Date.today() - relativedelta(days=1)
        )

    def test_edit_english_a2_to_english_b1(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        index = self.employee.current_employee_skill_ids.ids.index(self.line3.id)
        with employee_form.current_employee_skill_ids.edit(
            index
        ) as employee_skill_form:
            employee_skill_form.skill_level_id = self.language.skill_level_ids[2]

        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertEqual(len(employee.employee_skill_ids.ids), 6)
        self.assertEqual(new_employee_skill.valid_from, fields.Date.today())
        self.assertEqual(
            self.line3.valid_to, fields.Date.today() - relativedelta(days=1)
        )

    def test_edit_odoo_50_stop_date(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        index = self.employee.current_employee_skill_ids.ids.index(self.line1.id)
        with employee_form.current_employee_skill_ids.edit(
            index
        ) as employee_skill_form:
            employee_skill_form.valid_to = fields.Date.today() + relativedelta(months=2)

        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertFalse(new_employee_skill)
        self.assertEqual(len(employee.employee_skill_ids.ids), 5)
        self.assertEqual(
            self.line1.valid_to, fields.Date.today() + relativedelta(months=2)
        )

    def test_create_scrum_50_and_edit_it_to_french_a1(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        self.assertEqual(len(self.employee.employee_skill_ids.ids), 5)
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[1]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[1]
            employee_skill_form.valid_from = fields.Date.today() + relativedelta(
                months=-11
            )
            employee_skill_form.valid_to = fields.Date.today() + relativedelta(
                months=-5
            )

        employee = employee_form.save()
        self.assertEqual(len(employee.employee_skill_ids.ids), 6)
        self.assertEqual(
            len(employee.current_employee_skill_ids.ids),
            4,
            "this expired certification should be added because this employee doesn't any valid certification for this skill",
        )

        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        index = self.employee.current_employee_skill_ids.ids.index(
            new_employee_skill.id
        )
        new_previous_employee_skills = employee.employee_skill_ids

        with employee_form.current_employee_skill_ids.edit(
            index
        ) as employee_skill_form:
            employee_skill_form.skill_type_id = self.language
            employee_skill_form.skill_id = self.language.skill_ids[2]
            employee_skill_form.skill_level_id = self.language.skill_level_ids[0]

        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - new_previous_employee_skills
        delete_one = new_previous_employee_skills - employee.employee_skill_ids
        self.assertEqual(len(employee.employee_skill_ids.ids), 6)
        self.assertEqual(
            len(employee.current_employee_skill_ids.ids),
            4,
            "the expired certification is deleted and the skill french a1 is valid so this skill should be in current_employee_skill_ids",
        )
        self.assertEqual(len(delete_one.ids), 1)
        self.assertEqual(new_employee_skill.valid_from, fields.Date.today())
        self.assertFalse(new_employee_skill.valid_to)

    def test_edit_arabic_a2_to_odoo_50_from_1_jan_to_1_june(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        index = self.employee.current_employee_skill_ids.ids.index(self.line4.id)
        with employee_form.current_employee_skill_ids.edit(
            index
        ) as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[1]
            employee_skill_form.valid_from = fields.Date.today() - relativedelta(
                months=5
            )
            employee_skill_form.valid_to = fields.Date.today() + relativedelta(months=7)

        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertEqual(
            self.line4.valid_to, fields.Date.today() - relativedelta(days=1)
        )
        self.assertEqual(self.line4.valid_from, datetime.date(2024, 2, 1))
        self.assertEqual(
            new_employee_skill.valid_from, fields.Date.today() - relativedelta(months=5)
        )
        self.assertEqual(
            new_employee_skill.valid_to, fields.Date.today() + relativedelta(months=7)
        )

    def test_add_odoo_50_from_2_mar_to_infinite(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[1]
            employee_skill_form.valid_from = datetime.date(2024, 3, 2)

        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertFalse(
            new_employee_skill, "this certificate already exist for this date range"
        )
        self.assertEqual(len(self.employee.employee_skill_ids.ids), 5)

    def test_add_english_a2(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.language
            employee_skill_form.skill_id = self.language.skill_ids[1]
            employee_skill_form.skill_level_id = self.language.skill_level_ids[2]
        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertEqual(new_employee_skill.valid_from, fields.Date.today())
        self.assertFalse(new_employee_skill.valid_to)
        self.assertEqual(
            self.line3.valid_to, fields.Date.today() - relativedelta(days=1)
        )
        self.assertEqual(len(employee.employee_skill_ids.ids), 6)

    def test_add_french_a1_and_edit_it_after_to_french_a2(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.language
            employee_skill_form.skill_id = self.language.skill_ids[2]
            employee_skill_form.skill_level_id = self.language.skill_level_ids[1]
        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills

        self.assertEqual(new_employee_skill.valid_from, fields.Date.today())
        self.assertFalse(new_employee_skill.valid_to)
        self.assertEqual(len(employee.employee_skill_ids.ids), 6)

        index = self.employee.current_employee_skill_ids.ids.index(
            new_employee_skill.id
        )
        with employee_form.current_employee_skill_ids.edit(
            index
        ) as employee_skill_form:
            employee_skill_form.skill_level_id = self.language.skill_level_ids[4]
        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertEqual(new_employee_skill.valid_from, fields.Date.today())
        self.assertFalse(new_employee_skill.valid_to)
        self.assertEqual(
            new_employee_skill.skill_level_id, self.language.skill_level_ids[4]
        )
        self.assertEqual(len(employee.employee_skill_ids.ids), 6)

    def test_archiving_vs_deleting_regular_skill(self):
        employee_form = Form(self.employee)
        self.assertEqual(
            len(self.employee.employee_skill_ids.ids),
            5,
            "The test employee should start with 5 skills.",
        )

        # Remove one of the skills from the setup
        index = self.employee.current_employee_skill_ids.ids.index(self.line3.id)
        employee_form.current_employee_skill_ids.remove(index=index)
        employee = employee_form.save()
        self.assertEqual(
            len(employee.employee_skill_ids.ids),
            5,
            "The test employee should still have 5 skills, as the archived skill was not created within the last day",
        )

        self.assertEqual(
            self.line3.valid_to,
            fields.Date.today() - relativedelta(days=1),
            "The skill that got removed should have date_to set to one day before now",
        )

        previous_employee_skills = self.employee.employee_skill_ids
        # Add French C1
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.language
            employee_skill_form.skill_id = self.language.skill_ids[2]
            employee_skill_form.skill_level_id = self.language.skill_level_ids[4]
        employee = employee_form.save()
        new_employee_skill = employee.employee_skill_ids - previous_employee_skills
        self.assertEqual(
            len(employee.employee_skill_ids.ids),
            6,
            "Creating a new skill should result in the employee having 6 skills.",
        )

        # Remove it
        index = self.employee.current_employee_skill_ids.ids.index(
            new_employee_skill.id
        )
        employee_form.current_employee_skill_ids.remove(index=index)
        employee = employee_form.save()
        self.assertEqual(
            len(employee.employee_skill_ids.ids),
            5,
            "The skill that got removed should have been deleted as it was created within the last day",
        )

    def test_archiving_vs_deleting_certification(self):
        employee_form = Form(self.employee)
        self.assertEqual(
            len(self.employee.employee_skill_ids.ids),
            5,
            "The test employee should start with 5 skills.",
        )

        # Remove one of certification from the setup (not expired certification)
        index = self.employee.current_employee_skill_ids.ids.index(self.line1.id)
        employee_form.current_employee_skill_ids.remove(index=index)
        employee = employee_form.save()
        self.assertEqual(
            len(employee.employee_skill_ids.ids),
            5,
            "The test employee should have 5 skills",
        )
        self.assertEqual(
            self.line1.valid_to, fields.Date.today() - relativedelta(days=1)
        )

        # Remove one of certification from the setup (expired certification)
        index = self.employee.current_employee_skill_ids.ids.index(self.line1.id)
        employee_form.current_employee_skill_ids.remove(index=index)
        employee = employee_form.save()
        self.assertEqual(
            len(employee.employee_skill_ids.ids),
            4,
            "The test employee should have 4 skills since the expired certification is removed",
        )

    def test_add_odoo_70_from_1_jan_1_mar(self):
        self.assertEqual(
            len(self.employee.employee_skill_ids.ids),
            5,
            "The test employee should have 5 skills",
        )
        employee_form = Form(self.employee)
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[2]
            employee_skill_form.valid_from = datetime.date(
                2024, 1, 1
            )  # so same as odoo 20%
            employee_skill_form.valid_to = datetime.date(
                2024, 4, 1
            )  # so same as odoo 20%

        employee = employee_form.save()
        self.assertEqual(
            len(employee.employee_skill_ids.ids),
            6,
            "The test employee should have 6 skills",
        )

    def test_add_odoo_50_from_1_jan_to_infinite(self):
        self.assertEqual(
            len(self.employee.employee_skill_ids.ids),
            5,
            "The test employee should have 5 skills",
        )
        employee_form = Form(self.employee)
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[
                1
            ]  # so same as odoo 50%
            employee_skill_form.valid_from = datetime.date(2024, 1, 1)

        employee = employee_form.save()
        self.assertEqual(
            len(employee.employee_skill_ids.ids),
            6,
            "The test employee should have 6 skills",
        )

    def test_multiple_exact_same_skills_are_deduplicated_before_creation(self):
        """
        Assert that when you add multiple entries of the same skill:level,
        only one employee skill will be created.
        """
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        for _ in range(3):
            with employee_form.current_employee_skill_ids.new() as employee_skill_form:
                employee_skill_form.skill_type_id = self.certification
                employee_skill_form.skill_id = self.certification.skill_ids[0]
                employee_skill_form.skill_level_id = self.certification.skill_level_ids[
                    1
                ]
        employee_form.save()
        new_skill = self.employee.employee_skill_ids - previous_employee_skills

        self.assertTrue(new_skill)
        self.assertEqual(len(new_skill), 1)
        self.assertEqual(new_skill.valid_from, fields.Date.today())
        self.assertEqual(len(self.employee.employee_skill_ids), 6)

    def test_multiple_same_skill_different_level_are_deduplicated_before_creation(self):
        """
        Assert that when you add multiple entries of the same skill but different level,
        only one employee skill will be created.
        """
        skill_levels = self.language.skill_level_ids
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        for level in skill_levels:
            with employee_form.current_employee_skill_ids.new() as employee_skill_form:
                employee_skill_form.skill_type_id = self.language
                employee_skill_form.skill_id = self.language.skill_ids[0]
                employee_skill_form.skill_level_id = level
        employee_form.save()
        new_skill = self.employee.employee_skill_ids - previous_employee_skills

        self.assertTrue(new_skill)
        self.assertEqual(len(new_skill), 1)
        self.assertEqual(new_skill.valid_from, fields.Date.today())
        self.assertEqual(len(self.employee.employee_skill_ids), 6)

    def test_same_certification_with_different_levels_but_same_dates_can_coexist(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        self.assertEqual(len(self.employee.current_employee_skill_ids), 3)
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[1]
            employee_skill_form.valid_from = fields.Date.today() - relativedelta(
                months=4
            )
            employee_skill_form.valid_to = fields.Date.today() + relativedelta(months=8)
        employee_form.save()
        new_skill = self.employee.employee_skill_ids - previous_employee_skills

        self.assertTrue(new_skill)
        self.assertEqual(
            len(self.employee.employee_skill_ids),
            6,
            "The new certification should be added",
        )
        self.assertEqual(
            len(self.employee.current_employee_skill_ids),
            4,
            "The new certification should be added",
        )

    def test_duplicate_certifications_in_the_past_are_not_created(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids
        previous_current_employee_skills = self.employee.current_employee_skill_ids
        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[2]
            employee_skill_form.valid_from = fields.Date.today() - relativedelta(
                years=2
            )
            employee_skill_form.valid_to = fields.Date.today() - relativedelta(years=2)
        employee_form.save()
        new_skill = self.employee.employee_skill_ids - previous_employee_skills
        new_previous_employee_skills = self.employee.employee_skill_ids
        self.assertTrue(new_skill)
        self.assertEqual(len(self.employee.employee_skill_ids), 6)
        self.assertEqual(
            self.employee.current_employee_skill_ids,
            previous_current_employee_skills,
            "an active certification already existed for this skill type; so the current_employee_skills should be the same",
        )

        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[2]
            employee_skill_form.valid_from = fields.Date.today() - relativedelta(
                years=2
            )
            employee_skill_form.valid_to = fields.Date.today() - relativedelta(years=2)
        employee_form.save()
        new_skill = self.employee.employee_skill_ids - new_previous_employee_skills
        self.assertFalse(
            new_skill,
            "A certification with the exact same values already exists so a new one shouldn't be created",
        )
        self.assertEqual(len(self.employee.employee_skill_ids), 6)
        self.assertEqual(
            self.employee.current_employee_skill_ids,
            previous_current_employee_skills,
            "an active certification already existed for this skill type; so the current_employee_skills should be the same",
        )

    def test_rpc_call_editing_range_date_regular_skill(self):
        """Ensure a direct create/write (bypassing the form view) can edit a regular skill's date range."""

        # French levels for the test employee, before and after shifting the A1/A2 boundary:
        # start:
        #         2025-01-15        2025-03-20                             2025-05-20
        # -------------|-----------------|--------------------------------------|------------------
        #             A1                 A2                                     B1
        # stop:
        #         2025-01-15                          2025-04-20           2025-05-20
        # -------------|----------------------------------|---------------------|------------------
        #             A1                                  A2                    B1
        french_a1, french_a2, _ = self.env["hr.employee.skill"].create(
            [
                {
                    "skill_type_id": self.language.id,
                    "skill_id": self.language.skill_ids[2].id,
                    "skill_level_id": self.language.skill_level_ids[0].id,
                    "employee_id": self.employee.id,
                    "valid_from": datetime.date(2025, 1, 15),
                    "valid_to": datetime.date(2025, 3, 19),
                },
                {
                    "skill_type_id": self.language.id,
                    "skill_id": self.language.skill_ids[2].id,
                    "skill_level_id": self.language.skill_level_ids[1].id,
                    "employee_id": self.employee.id,
                    "valid_from": datetime.date(2025, 3, 20),
                    "valid_to": datetime.date(2025, 5, 19),
                },
                {
                    "skill_type_id": self.language.id,
                    "skill_id": self.language.skill_ids[2].id,
                    "skill_level_id": self.language.skill_level_ids[2].id,
                    "employee_id": self.employee.id,
                    "valid_from": datetime.date(2025, 5, 20),
                },
            ]
        )
        french_a2.write({"valid_from": datetime.date(2025, 4, 20)})
        french_a1.write({"valid_to": datetime.date(2025, 4, 19)})
        self.assertEqual(french_a1.valid_to, datetime.date(2025, 4, 19))
        self.assertEqual(french_a2.valid_from, datetime.date(2025, 4, 20))
        with self.assertRaises(ValidationError):
            french_a1.write({"valid_to": datetime.date(2025, 4, 25)})
        with self.assertRaises(ValidationError):
            french_a2.write({"valid_from": datetime.date(2025, 2, 25)})

    def test_expire_current_certification_with_one_expired_for_the_same_date(self):
        employee_form = Form(self.employee)
        previous_employee_skills = self.employee.employee_skill_ids

        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[2]
            employee_skill_form.valid_from = fields.Date.today() - relativedelta(
                years=2
            )
            employee_skill_form.valid_to = fields.Date.today() + relativedelta(years=2)
        employee_form.save()
        new_skill = self.employee.employee_skill_ids - previous_employee_skills

        with employee_form.current_employee_skill_ids.new() as employee_skill_form:
            employee_skill_form.skill_type_id = self.certification
            employee_skill_form.skill_id = self.certification.skill_ids[0]
            employee_skill_form.skill_level_id = self.certification.skill_level_ids[2]
            employee_skill_form.valid_from = fields.Date.today() - relativedelta(
                years=2
            )
            employee_skill_form.valid_to = fields.Date.today() - relativedelta(days=1)
        employee_form.save()

        self.assertEqual(len(self.employee.employee_skill_ids), 7)

        index = self.employee.current_employee_skill_ids.ids.index(new_skill.id)
        employee_form.current_employee_skill_ids.remove(index=index)
        employee_form.save()
        self.assertEqual(
            len(self.employee.employee_skill_ids),
            6,
            "the certification is removed because an other expired certification has the same validity range",
        )


class TestSkillFieldDefaults(TransactionCase):
    """Regression: hr.individual.skill.mixin.valid_from default must be a callable
    (evaluated per-record at create time), not fields.Date.today() captured once at
    class-body/module-load time."""

    def test_valid_from_default_evaluated_per_record(self):
        skill_type = self.env["hr.skill.type"].create({"name": "Default Test Type"})
        level = self.env["hr.skill.level"].create(
            {
                "name": "L1",
                "skill_type_id": skill_type.id,
                "level_progress": 50,
            }
        )
        skill = self.env["hr.skill"].create(
            {"name": "S1", "skill_type_id": skill_type.id}
        )
        employee = self.env["hr.employee"].create({"name": "Default Test Employee"})
        with freeze_time("2099-01-01"):
            emp_skill = self.env["hr.employee.skill"].create(
                {
                    "employee_id": employee.id,
                    "skill_id": skill.id,
                    "skill_type_id": skill_type.id,
                    "skill_level_id": level.id,
                }
            )
        self.assertEqual(
            emp_skill.valid_from,
            datetime.date(2099, 1, 1),
            "valid_from default must be evaluated per-record at create time, "
            "not captured once at module load",
        )


class TestIndividualSkillOrder(TransactionCase):
    """The employee profile, the job position and the applicant must all list
    the skills of a type from the highest level down."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.skill_type = cls.env["hr.skill.type"].create({"name": "Order Test Type"})
        cls.low, cls.mid, cls.high = cls.env["hr.skill.level"].create(
            [
                {
                    "name": "Low",
                    "skill_type_id": cls.skill_type.id,
                    "level_progress": 10,
                },
                {
                    "name": "Mid",
                    "skill_type_id": cls.skill_type.id,
                    "level_progress": 50,
                },
                {
                    "name": "High",
                    "skill_type_id": cls.skill_type.id,
                    "level_progress": 90,
                },
            ]
        )
        cls.skill_a, cls.skill_b, cls.skill_c = cls.env["hr.skill"].create(
            [
                {"name": "Order Skill A", "skill_type_id": cls.skill_type.id},
                {"name": "Order Skill B", "skill_type_id": cls.skill_type.id},
                {"name": "Order Skill C", "skill_type_id": cls.skill_type.id},
            ]
        )
        cls.employee = cls.env["hr.employee"].create({"name": "Order Test Employee"})
        cls.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": cls.employee.id,
                    "skill_type_id": cls.skill_type.id,
                    "skill_id": skill.id,
                    "skill_level_id": level.id,
                }
                for skill, level in (
                    (cls.skill_a, cls.low),
                    (cls.skill_b, cls.mid),
                    (cls.skill_c, cls.high),
                )
            ]
        )

    def test_employee_skills_are_ordered_by_descending_level(self):
        self.assertEqual(
            self.employee.employee_skill_ids.mapped("skill_level_id.level_progress"),
            [90, 50, 10],
            "the strongest skill of a type must come first on the employee",
        )

    def test_employee_and_job_skills_share_the_same_order(self):
        job = self.env["hr.job"].create({"name": "Order Test Job"})
        self.env["hr.job.skill"].create(
            [
                {
                    "job_id": job.id,
                    "skill_type_id": self.skill_type.id,
                    "skill_id": skill.id,
                    "skill_level_id": level.id,
                }
                for skill, level in (
                    (self.skill_a, self.low),
                    (self.skill_b, self.mid),
                    (self.skill_c, self.high),
                )
            ]
        )
        self.assertEqual(
            self.employee.current_employee_skill_ids.mapped("skill_id.name"),
            job.current_job_skill_ids.mapped("skill_id.name"),
            "the employee profile and the job position must agree on the order",
        )


class TestSkillValidityTimezone(TransactionCase):
    """Validity dates are calendar dates, so they must be read in the user's
    timezone. At UTC-6 the local day and the UTC day disagree for the last six
    hours of every local day."""

    # 02:00 UTC on the 31st is 20:00 on the 30th in America/Mexico_City.
    EVENING_UTC = "2026-08-31 02:00:00"
    LOCAL_DAY = datetime.date(2026, 8, 30)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = "America/Mexico_City"
        cls.skill_type = cls.env["hr.skill.type"].create({"name": "Timezone Type"})
        cls.level = cls.env["hr.skill.level"].create(
            {
                "name": "TZ Level",
                "skill_type_id": cls.skill_type.id,
                "level_progress": 50,
            }
        )
        cls.skill = cls.env["hr.skill"].create(
            {"name": "Timezone Skill", "skill_type_id": cls.skill_type.id}
        )
        cls.employee = cls.env["hr.employee"].create({"name": "Timezone Employee"})

    def _local_env(self):
        return self.env["base"].with_context(tz="America/Mexico_City").env

    def test_valid_from_default_uses_the_local_day(self):
        env = self._local_env()
        with freeze_time(self.EVENING_UTC):
            employee_skill = env["hr.employee.skill"].create(
                {
                    "employee_id": self.employee.id,
                    "skill_type_id": self.skill_type.id,
                    "skill_id": self.skill.id,
                    "skill_level_id": self.level.id,
                }
            )
        self.assertEqual(
            employee_skill.valid_from,
            self.LOCAL_DAY,
            "a skill added at 20:00 must start today, not tomorrow",
        )

    def test_job_skill_valid_until_today_is_still_current(self):
        env = self._local_env()
        with freeze_time(self.EVENING_UTC):
            job = env["hr.job"].create({"name": "Timezone Test Job"})
            job_skill = env["hr.job.skill"].create(
                {
                    "job_id": job.id,
                    "skill_type_id": self.skill_type.id,
                    "skill_id": self.skill.id,
                    "skill_level_id": self.level.id,
                    "valid_from": datetime.date(2026, 8, 1),
                    "valid_to": self.LOCAL_DAY,
                }
            )
            self.assertIn(
                job_skill,
                job.current_job_skill_ids,
                "a skill valid until today must not expire six hours early",
            )
            self.assertIn(
                job,
                env["hr.job"].search([("current_job_skill_ids", "in", job_skill.ids)]),
                "the search side must agree with the computed side",
            )


class TestCertificationViews(TransactionCase):
    """The Certifications tab of the employee form must expose the uploaded
    certificate so it can be downloaded from the list."""

    def test_certification_list_shows_the_certificate_file(self):
        arch = etree.fromstring(
            self.env["hr.employee"].get_view(view_type="form")["arch"]
        )
        certification_lists = arch.xpath("//field[@name='certification_ids']//list")
        self.assertTrue(
            certification_lists, "the Certifications tab must embed a list view"
        )
        columns = certification_lists[0].xpath("./field/@name")
        self.assertIn(
            "certificate_file",
            columns,
            "the certificate must be reachable from the certifications list",
        )
        self.assertIn(
            "certificate_filename",
            columns,
            "the binary widget needs the filename column to name the download",
        )


class TestCertificationCompany(TransactionCase):
    """Certifications belong to the employee's company, and the Certifications
    list must only show the companies the user has selected."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a, cls.company_b = cls.env["res.company"].create(
            [{"name": "Certification Co A"}, {"name": "Certification Co B"}]
        )
        cls.skill_type = cls.env["hr.skill.type"].create(
            {"name": "Company Certificate", "is_certification": True}
        )
        cls.level = cls.env["hr.skill.level"].create(
            {
                "name": "Certified",
                "skill_type_id": cls.skill_type.id,
                "level_progress": 100,
            }
        )
        cls.skill = cls.env["hr.skill"].create(
            {"name": "Company Skill", "skill_type_id": cls.skill_type.id}
        )
        cls.employee_a, cls.employee_b = cls.env["hr.employee"].create(
            [
                {"name": "Employee A", "company_id": cls.company_a.id},
                {"name": "Employee B", "company_id": cls.company_b.id},
            ]
        )
        cls.certification_a, cls.certification_b = cls.env["hr.employee.skill"].create(
            [
                {
                    "employee_id": employee.id,
                    "skill_type_id": cls.skill_type.id,
                    "skill_id": cls.skill.id,
                    "skill_level_id": cls.level.id,
                }
                for employee in (cls.employee_a, cls.employee_b)
            ]
        )

    def test_certification_carries_the_employee_company(self):
        self.assertEqual(self.certification_a.company_id, self.company_a)
        self.assertEqual(self.certification_b.company_id, self.company_b)

    def test_certification_action_filters_on_the_selected_companies(self):
        action = self.env.ref("hr_skills.action_hr_employee_skill_certification")
        domain = safe_eval(action.domain, {"allowed_company_ids": self.company_a.ids})
        found = self.env["hr.employee.skill"].search(domain)
        self.assertIn(self.certification_a, found)
        self.assertNotIn(
            self.certification_b,
            found,
            "a company the user did not select must stay out of the list",
        )
