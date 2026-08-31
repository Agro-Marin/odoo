from odoo.tests.common import TransactionCase


class SkillsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.skill_type = cls.env["hr.skill.type"].create({"name": "Instruments"})
        cls.level_novice, cls.level_expert = cls.env["hr.skill.level"].create(
            [
                {
                    "name": "Novice",
                    "skill_type_id": cls.skill_type.id,
                    "level_progress": 25,
                },
                {
                    "name": "Expert",
                    "skill_type_id": cls.skill_type.id,
                    "level_progress": 100,
                },
            ],
        )
        cls.skill_piano, cls.skill_guitar = cls.env["hr.skill"].create(
            [
                {"name": "Piano", "skill_type_id": cls.skill_type.id},
                {"name": "Guitar", "skill_type_id": cls.skill_type.id},
            ],
        )

        cls.certification_type = cls.env["hr.skill.type"].create(
            {"name": "Diplomas", "is_certification": True},
        )
        cls.level_certified = cls.env["hr.skill.level"].create(
            {
                "name": "Certified",
                "skill_type_id": cls.certification_type.id,
                "level_progress": 100,
            },
        )
        cls.certification = cls.env["hr.skill"].create(
            {"name": "Conservatory", "skill_type_id": cls.certification_type.id},
        )
