from odoo.fields import Command

from odoo.addons.project.tests.test_project_base import TestProjectCommon


class TestProjectWorkflowStep(TestProjectCommon):
    def test_step_created_from_a_project_context_is_attached_to_it(self) -> None:
        Step = self.env["project.workflow.step"]
        step_id, _label = Step.with_context(
            default_project_id=self.project_goats.id
        ).name_create("Doing")
        step = Step.browse(step_id)

        self.assertEqual(step.project_ids, self.project_goats)
        self.assertIn(step, self.project_goats.workflow_step_ids)

    def test_step_has_no_owner_concept(self) -> None:
        self.assertNotIn("user_id", self.env["project.workflow.step"]._fields)

    def test_step_created_with_explicit_projects(self) -> None:
        Step = self.env["project.workflow.step"]
        for label, project_ids in {
            "recordset": self.project_goats,
            "id list": self.project_goats.ids,
            "set": [Command.set(self.project_goats.ids)],
            "link": [Command.link(self.project_goats.id)],
        }.items():
            with self.subTest(project_ids=label):
                step = Step.create(
                    {"name": f"Step via {label}", "project_ids": project_ids}
                )
                self.assertEqual(step.project_ids, self.project_goats)

    def test_detaching_a_step_leaves_it_unattached(self) -> None:
        step = self.env["project.workflow.step"].create(
            {"name": "Detachable", "project_ids": self.project_goats.ids}
        )
        step.write({"project_ids": False})
        self.assertFalse(step.project_ids)
        self.assertTrue(step.exists())

    def test_step_find_ignores_unattached_steps(self) -> None:
        orphan = self.env["project.workflow.step"].create({"name": "Orphan"})
        found = self.env["project.task"].step_find(self.project_goats.id)
        self.assertNotEqual(found, orphan.id)
        self.assertIn(found, self.project_goats.workflow_step_ids.ids)
