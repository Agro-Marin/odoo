"""Workflow steps: defaults, private tasks, and the periodic rating cron."""

from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
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

    def test_workflow_step_clear_command_creates_an_unattached_step(self) -> None:
        """A clear/empty project command yields a step with no project.

        This used to assert that such a step became a *personal stage*
        (``user_id`` set). That field is gone — personal buckets are
        ``project.triage`` — so what matters now is only that the commands are
        resolved rather than treated as truthy: [(5,)] and [(6,0,[])] must not
        be mistaken for a project assignment."""
        Step = self.env["project.workflow.step"]
        for command in ([(5,)], [(6, 0, [])]):
            step = Step.create({"name": "Unattached", "project_ids": command})
            self.assertFalse(step.project_ids, f"{command}: must have no project")
        proj_step = Step.create(
            {"name": "Proj", "project_ids": [(4, self.project_pigs.id)]}
        )
        self.assertEqual(proj_step.project_ids, self.project_pigs)

    def test_step_delete_wizard_count_depends_on_steps(self) -> None:
        """The delete wizard's tasks_count must recompute when step_ids changes
        (the field it actually reads), not only when project_ids changes."""
        step = self.env["project.workflow.step"].create(
            {"name": "Zap", "project_ids": [(4, self.project_pigs.id)]}
        )
        self.env["project.task"].create(
            {"name": "in step", "project_id": self.project_pigs.id, "step_id": step.id}
        )
        wizard = self.env["project.workflow.step.delete.wizard"].create(
            {"step_ids": [(6, 0, step.ids)]}
        )
        self.assertEqual(wizard.tasks_count, 1)
        # Clearing step_ids must recompute the count to 0 (the bug left it stale
        # because the compute depended on project_ids instead).
        wizard.step_ids = [(5,)]
        self.assertEqual(
            wizard.tasks_count, 0, "tasks_count must react to step_ids changes"
        )

    def test_rating_deadline_is_seeded_and_stable(self) -> None:
        """rating_request_deadline is a plain field: seeded on enabling periodic
        rating and NOT reset to now()+period by an unrelated recompute."""
        step = self.env["project.workflow.step"].create(
            {
                "name": "Periodic",
                "rating_active": True,
                "rating_status": "periodic",
                "rating_status_period": "weekly",
            }
        )
        seeded = step.rating_request_deadline
        self.assertTrue(seeded, "deadline must be seeded when periodic rating on")
        step.invalidate_recordset(["rating_request_deadline"])
        self.assertEqual(
            step.rating_request_deadline,
            seeded,
            "deadline must survive recompute (no now()-based reset)",
        )

    def test_send_rating_all_advances_deadline(self) -> None:
        """The rating cron must process an overdue periodic step and push its
        rating_request_deadline into the future (idempotent per day)."""
        step = self.env["project.workflow.step"].create(
            {
                "name": "Periodic",
                "project_ids": [(4, self.project_pigs.id)],
                "rating_active": True,
                "rating_status": "periodic",
                "rating_status_period": "weekly",
            }
        )
        # Force the step overdue.
        step.rating_request_deadline = fields.Datetime.now() - timedelta(days=1)
        # The cron commits per step for idempotency; neutralise commit inside the
        # test transaction (commits are forbidden in tests).
        with patch.object(self.env.cr, "commit", lambda: None):
            self.env["project.workflow.step"]._send_rating_all()
        self.assertGreater(
            step.rating_request_deadline,
            fields.Datetime.now(),
            "cron must advance the deadline of an overdue periodic step",
        )
