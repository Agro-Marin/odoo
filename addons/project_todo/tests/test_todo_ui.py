from odoo import Command
from odoo.tests import tagged, users

from odoo.addons.base.tests.common import HttpCaseWithUserDemo


@tagged("post_install", "-at_install")
class TestTodoUi(HttpCaseWithUserDemo):
    @users("admin")
    def test_tour_project_task_activities_split(self):
        self.env.user.tz = "UTC"
        project = self.env["project.project"].create([{"name": "Test project"}])
        stage = self.env["project.workflow.step"].create(
            [
                {
                    "name": "Test Stage",
                    "project_ids": project.ids,
                }
            ]
        )
        private_task, task = self.env["project.task"].create(
            [
                {
                    "name": "New To-Do!",
                    "project_id": False,
                },
                {
                    "name": "New Task!",
                    "project_id": project.id,
                    "step_id": stage.id,
                    "child_ids": [
                        Command.create(
                            {
                                "name": "New Sub-Task!",
                                "project_id": project.id,
                            }
                        ),
                    ],
                },
            ]
        )

        subtask = task.child_ids
        task.activity_schedule(
            act_type_xmlid="mail.mail_activity_data_todo", user_id=self.env.uid
        )
        subtask.activity_schedule(
            act_type_xmlid="mail.mail_activity_data_todo", user_id=self.env.uid
        )
        private_task.activity_schedule(
            act_type_xmlid="mail.mail_activity_data_todo", user_id=self.env.uid
        )

        self.start_tour("/odoo", "project_task_activities_split", login="admin")

    def test_tour_todo_main_ui_functions(self):
        self.env.ref("base.user_admin").write(
            {
                "email": "mitchell.admin@example.com",
            }
        )
        self.start_tour("/odoo", "project_todo_main_functions", login="admin")

    @users("admin")
    def test_project_todo_history(self):

        self.env["project.task"].create(
            {"name": "Test History Todo", "project_id": False}
        )

        self.start_tour("/odoo?debug=1", "project_todo_history_tour", login="admin")
