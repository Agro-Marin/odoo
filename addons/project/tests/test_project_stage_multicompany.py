from odoo.exceptions import UserError

from .test_multicompany import TestMultiCompanyProject


class TestProjectStagesMulticompany(TestMultiCompanyProject):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()

        Users = cls.env["res.users"].with_context({"no_reset_password": True})
        cls.user_manager_companies = Users.create(
            {
                "name": "Manager Companies",
                "login": "manager-all",
                "email": "manager@companies.com",
                "company_id": cls.company_a.id,
                "company_ids": [(4, cls.company_a.id), (4, cls.company_b.id)],
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("project.group_project_stages").id,
                            cls.env.ref("project.group_project_manager").id,
                        ],
                    )
                ],
            }
        )
        (
            cls.stage_company_a,
            cls.stage_company_b,
            cls.stage_company_none,
        ) = cls.env["project.phase"].create(
            [
                {
                    "name": "Stage Company A",
                    "company_id": cls.company_a.id,
                },
                {
                    "name": "Stage Company B",
                    "company_id": cls.company_b.id,
                },
                {
                    "name": "Stage Company None",
                },
            ]
        )
        cls.project_company_none = cls.env["project.project"].create(
            {"name": "Project Company None"}
        )

    def test_move_linked_project_stage_other_company(self) -> None:
        self.project_company_a.phase_id = self.stage_company_a.id
        with self.assertRaises(UserError):
            self.project_company_a.phase_id = self.stage_company_b.id

    def test_move_project_stage_other_company(self) -> None:
        self.project_company_none.phase_id = self.stage_company_none.id
        with self.assertRaises(UserError):
            self.project_company_none.phase_id = (self.stage_company_b.id,)

    def test_move_linked_project_stage_same_company(self) -> None:
        self.project_company_b.phase_id = self.stage_company_none.id
        self.project_company_b.phase_id = self.stage_company_b.id

    def test_move_project_stage_same_company(self) -> None:
        self.project_company_a.phase_id = self.stage_company_a.id
        self.stage_company_none.company_id = self.company_a.id
        self.project_company_a.phase_id = self.stage_company_none.id

    def test_change_project_company(self) -> None:
        project = self.project_company_a.with_user(self.user_manager_companies)
        project.phase_id = self.stage_company_a.id
        project.company_id = self.company_b.id

        self.assertFalse(
            self.project_company_a.phase_id.company_id,
            "Project Company A should now be in a stage without company",
        )

    def test_project_creation_default_stage(self) -> None:
        self.stage_company_a.sequence = 1
        self.stage_company_b.sequence = 3

        project_company_b = (
            self.env["project.project"]
            .with_user(self.user_manager_companies)
            .create(
                {
                    "name": "Project company B",
                    "company_id": self.company_b.id,
                }
            )
        )
        self.assertEqual(project_company_b.company_id, self.company_b)
        self.assertEqual(project_company_b.phase_id, self.stage_company_b)

        self.stage_company_none.sequence = 2

        project_company_b = (
            self.env["project.project"]
            .with_user(self.user_manager_companies)
            .create(
                {
                    "name": "Project company B",
                    "company_id": self.company_b.id,
                }
            )
        )
        self.assertEqual(project_company_b.company_id, self.company_b)
        self.assertEqual(project_company_b.phase_id, self.stage_company_none)

        project_no_company = (
            self.env["project.project"]
            .with_user(self.user_manager_companies)
            .create(
                {
                    "name": "Project no company",
                }
            )
        )
        self.assertFalse(project_no_company.company_id)
        self.assertEqual(project_no_company.phase_id, self.stage_company_none)

        self.env["project.phase"].search([]).active = False
        project_no_company = (
            self.env["project.project"]
            .with_user(self.user_manager_companies)
            .create(
                {
                    "name": "Project no company",
                }
            )
        )
        self.assertFalse(project_no_company.phase_id)

    def test_project_creation_default_stage_in_context(self) -> None:
        project = (
            self.env["project.project"]
            .with_user(self.user_manager_companies)
            .with_context(default_phase_id=self.stage_company_b.id)
            .create(
                {
                    "name": "Project company B",
                }
            )
        )
        self.assertEqual(project.company_id, self.company_b)

    def test_create_project_in_stage(self) -> None:
        self.env["res.config.settings"].create({"group_project_stages": True}).execute()
        stage = self.env["project.phase"].create(
            {
                "name": "Stage 2",
                "sequence": 100,
            }
        )
        project = self.env["project.project"].create(
            {
                "name": "Project in stage 2",
                "phase_id": stage.id,
            }
        )
        self.assertEqual(project.phase_id, stage)
