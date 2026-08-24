from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestTodoAclScope(TransactionCase):
    """project_todo is auto_install, so whatever it grants lands on every
    database that has ``project``. It needs write access to ``project.task``
    (bounded by its own record rule) and to ``project.tags`` (the ``#tag``
    quick-create syntax), and nothing beyond that.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = new_test_user(
            cls.env, login="todo_employee", groups="base.group_user"
        )
        cls.project = cls.env["project.project"].create(
            {"name": "Someone else's project"}
        )

    def test_employee_cannot_touch_project_workflow_steps(self):
        """Project stages are not a to-do concept: to-dos file into project.triage."""
        self.assertFalse(self.employee.has_group("project.group_project_user"))
        step = self.env["project.workflow.step"].create(
            {
                "name": "Important stage",
                "project_ids": self.project.ids,
            }
        )
        step_as_employee = step.with_user(self.employee)
        self.assertTrue(step_as_employee.name, "employees still read project stages")
        for operation, thunk in (
            ("write", lambda: step_as_employee.write({"name": "hijacked"})),
            (
                "create",
                lambda: (
                    self.env["project.workflow.step"]
                    .with_user(self.employee)
                    .create({"name": "x"})
                ),
            ),
            ("unlink", step_as_employee.unlink),
        ):
            with self.subTest(operation=operation), self.assertRaises(AccessError):
                thunk()
                self.env.flush_all()

    def test_employee_cannot_delete_project_tags(self):
        """Removing a tag from a to-do is a write on the task, not an unlink."""
        tag = self.env["project.tags"].create({"name": "Company-wide tag"})
        with self.assertRaises(AccessError):
            tag.with_user(self.employee).unlink()
            self.env.flush_all()

    def test_employee_can_still_create_and_rename_tags(self):
        """What the quick-create's ``#tag`` syntax and the colour picker need."""
        tag = self.env["project.tags"].with_user(self.employee).create({"name": "mine"})
        tag.write({"color": 3})
        self.assertEqual(tag.color, 3)

    def test_employee_owns_only_their_own_private_tasks(self):
        """The blanket CRUD on project.task is bounded by the module's rule."""
        someone_elses = self.env["project.task"].create(
            {
                "name": "Not yours",
                "project_id": self.project.id,
            }
        )
        with self.assertRaises(AccessError):
            someone_elses.with_user(self.employee).write({"name": "hijacked"})
            self.env.flush_all()

        mine = (
            self.env["project.task"]
            .with_user(self.employee)
            .create(
                {
                    "name": "Mine",
                    "user_ids": [Command.set(self.employee.ids)],
                }
            )
        )
        mine.write({"name": "Still mine"})
        self.assertEqual(mine.name, "Still mine")
        mine.unlink()
