"""Workflow steps: defaults, private tasks, and the periodic rating cron."""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestDefaultWorkflowStep(TestProjectCommon):
    """Every project starts with a board, whichever way it was created."""

    def test_create_seeds_a_default_step(self) -> None:
        """Seeding lived in ``name_create`` — the Many2one dropdown quick-create
        — so form Save, imports, scripts and template instantiation all
        produced a project with no Kanban column at all."""
        project = self.env["project.project"].create({"name": "Via create"})
        self.assertEqual(len(project.workflow_step_ids), 1)

    def test_form_save_seeds_a_default_step(self) -> None:
        with Form(self.env["project.project"]) as form:
            form.name = "Via form"
        self.assertEqual(len(form.record.workflow_step_ids), 1)

    def test_task_created_in_a_new_project_lands_on_the_board(self) -> None:
        """The cost of the empty board was not cosmetic: a task created before
        the first column existed got ``step_id = False``, and adding a column
        later does not adopt it."""
        project = self.env["project.project"].create({"name": "Boarded"})
        task = self.env["project.task"].create({"name": "T", "project_id": project.id})
        self.assertTrue(task.step_id)
        self.assertIn(task.step_id, project.workflow_step_ids)

    def test_copy_does_not_add_a_second_default_step(self) -> None:
        """A copy brings the source's columns; it must not also be seeded."""
        project = self.env["project.project"].create({"name": "Source"})
        self.env["project.workflow.step"].create(
            {"name": "Doing", "project_ids": [Command.link(project.id)]}
        )
        copy = project.copy()
        self.assertEqual(
            sorted(copy.workflow_step_ids.mapped("name")),
            sorted(project.workflow_step_ids.mapped("name")),
        )


@tagged("post_install", "-at_install")
class TestPrivateTaskStepMessage(TestProjectCommon):
    def test_message_does_not_describe_what_it_refuses(self) -> None:
        """The old text named personal stages as the thing a private task may
        have, then refused exactly that."""
        task = self.env["project.task"].create({"name": "Private"})
        step = self.project_goats.workflow_step_ids[:1]
        with self.assertRaises(UserError) as caught:
            task.write({"step_id": step.id})
        self.assertNotIn("personal stage", str(caught.exception).lower())

    def test_clearing_a_step_a_private_task_never_had_is_allowed(self) -> None:
        """The guard fired on ``"step_id" in vals`` rather than on a value, so
        ``write({"step_id": False})`` — a write that asks for exactly what a
        private task already is — raised."""
        task = self.env["project.task"].create({"name": "Private"})
        task.write({"step_id": False})
        self.assertFalse(task.step_id)


@tagged("post_install", "-at_install")
class TestPeriodicRatingScope(TestProjectCommon):
    def test_closed_tasks_are_not_asked_to_rate_again(self) -> None:
        """A finished task keeps sitting in its step, so the periodic request
        repeated for as long as the step existed."""
        step = self.env["project.workflow.step"].create(
            {
                "name": "Periodic",
                "project_ids": [Command.link(self.project_pigs.id)],
                "rating_active": True,
                "rating_status": "periodic",
            }
        )
        done = self.env["project.task"].create(
            {"name": "Done", "project_id": self.project_pigs.id, "step_id": step.id}
        )
        done.state = "done"
        open_task = self.env["project.task"].create(
            {"name": "Open", "project_id": self.project_pigs.id, "step_id": step.id}
        )
        recipients = step._get_rating_tasks()

        self.assertIn(open_task, recipients)
        self.assertNotIn(done, recipients)

    def test_archived_tasks_are_not_asked_to_rate(self) -> None:
        step = self.env["project.workflow.step"].create(
            {
                "name": "Periodic",
                "project_ids": [Command.link(self.project_pigs.id)],
                "rating_active": True,
                "rating_status": "periodic",
            }
        )
        archived = self.env["project.task"].create(
            {"name": "Archived", "project_id": self.project_pigs.id, "step_id": step.id}
        )
        archived.active = False

        self.assertNotIn(archived, step._get_rating_tasks())


@tagged("post_install", "-at_install")
class TestQuickCreateSeedsAStep(TestProjectCommon):
    """Quick-creating a project still gives it a board."""

    def test_name_create_seeds_a_default_step(self) -> None:
        """A project created on the fly still gets its first board column.

        The seeding moved from ``name_create`` to ``create`` (so the form,
        imports and scripts get one too); this pins that the dropdown
        quick-create did not lose it in the move."""
        project_id, _name = self.env["project.project"].name_create("On the fly")
        step = self.env["project.project"].browse(project_id).workflow_step_ids
        self.assertEqual(len(step), 1)
