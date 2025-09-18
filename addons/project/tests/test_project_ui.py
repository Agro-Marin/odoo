import odoo.tests


@odoo.tests.tagged("post_install", "-at_install")
class TestUi(odoo.tests.HttpCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.env.ref("base.group_user").sudo().implied_ids |= cls.env.ref(
            "project.group_project_milestone"
        )

    def test_01_project_tour(self) -> None:
        self.start_tour("/odoo", "project_tour", login="admin")

    def test_project_task_history(self) -> None:
        """This tour will check that the history works properly."""
        stage = self.env["project.workflow.step"].create({"name": "To Do"})
        _dummy, project2 = self.env["project.project"].create(
            [
                {
                    "name": "Without tasks project",
                    "workflow_step_ids": stage.ids,
                },
                {
                    "name": "Test History Project",
                    "workflow_step_ids": stage.ids,
                },
            ]
        )

        self.env["project.task"].create(
            {
                "name": "Test History Task",
                "step_id": stage.id,
                "project_id": project2.id,
            }
        )

        self.start_tour("/odoo?debug=1", "project_task_history_tour", login="admin")

    def test_project_task_last_history_steps(self) -> None:
        """This tour will check that the history works properly."""
        stage = self.env["project.workflow.step"].create({"name": "To Do"})
        project = self.env["project.project"].create(
            [
                {
                    "name": "Test History Project",
                    "workflow_step_ids": stage.ids,
                }
            ]
        )

        self.env["project.task"].create(
            {
                "name": "Test History Task",
                "step_id": stage.id,
                "project_id": project.id,
            }
        )

        self.start_tour("/odoo", "project_task_last_history_steps_tour", login="admin")
