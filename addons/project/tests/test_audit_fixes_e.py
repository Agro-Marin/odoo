"""Regression tests for the 2026-08 project-module audit (Batch E).

Batch E is what survived being attacked. Every defect below was first found by
reading, then re-tested with a probe written to *falsify* it; several earlier
candidates died at that step and are not here. What is left is pinned with the
observation that proved it, so the same reasoning error cannot be re-made.

See research/2026-08-09-project-module-audit.md.
"""

import pathlib
from datetime import timedelta

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
class TestPredecessorBlockAtCreate(TestProjectCommon):
    """A dependency given at create time blocks the task, like one given later."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.project_pigs.allow_dependencies = True

    def _predecessor(self):
        return self.env["project.task"].create(
            {"name": "Predecessor", "project_id": self.project_pigs.id}
        )

    def test_blocked_when_predecessor_given_at_create(self) -> None:
        """``state`` carries a default, so the ORM writes ``todo`` straight to
        the row and ``_compute_state`` is never invoked — instrumented at zero
        calls. The record stored ``todo`` while ``is_blocked_by_predecessors()``
        answered True."""
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertTrue(task.is_blocked_by_predecessors())
        self.assertEqual(task.state, "blocked")

    def test_blocked_with_command_set(self) -> None:
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.set([predecessor.id])],
            }
        )
        self.assertEqual(task.state, "blocked")

    def test_blocked_through_the_import_path(self) -> None:
        """The spreadsheet import is the path that actually suffered: a batch of
        dependent tasks all landed unblocked."""
        predecessor = self._predecessor()
        self.env["ir.model.data"].create(
            [
                {
                    "module": "__test_batch_e__",
                    "name": "project",
                    "model": "project.project",
                    "res_id": self.project_pigs.id,
                },
                {
                    "module": "__test_batch_e__",
                    "name": "predecessor",
                    "model": "project.task",
                    "res_id": predecessor.id,
                },
            ]
        )
        result = self.env["project.task"].load(
            ["name", "project_id/id", "predecessor_ids/id"],
            [
                [
                    "Imported successor",
                    "__test_batch_e__.project",
                    "__test_batch_e__.predecessor",
                ]
            ],
        )
        self.assertFalse(
            [m for m in result["messages"] if m.get("type") == "error"],
            result["messages"],
        )
        imported = self.env["project.task"].browse(result["ids"])
        self.assertEqual(imported.state, "blocked")

    def test_closed_task_is_not_reopened_into_blocked(self) -> None:
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Already done",
                "project_id": self.project_pigs.id,
                "state": "done",
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertEqual(task.state, "done")

    def test_not_blocked_when_the_feature_is_off(self) -> None:
        self.project_pigs.allow_dependencies = False
        predecessor = self._predecessor()
        task = self.env["project.task"].create(
            {
                "name": "Successor",
                "project_id": self.project_pigs.id,
                "predecessor_ids": [Command.link(predecessor.id)],
            }
        )
        self.assertNotEqual(task.state, "blocked")


@tagged("post_install", "-at_install")
class TestDeliveredVersusClosed(TestProjectCommon):
    """ "Closed" and "delivered" are different questions, asked by different
    metrics, and they must not be answered with the same state list."""

    def test_cancelled_task_has_no_deadline_verdict(self) -> None:
        """A cancelled task did not miss its deadline — it was abandoned.
        ``deadline_met`` used to say 'missed', while the project-level
        ``deadline_compliance_pct`` ignored the task entirely."""
        now = fields.Datetime.now()
        task = self.env["project.task"].create(
            {
                "name": "Abandoned",
                "project_id": self.project_pigs.id,
                "date_end": now - timedelta(days=5),
            }
        )
        task.state = "canceled"
        self.assertFalse(task.deadline_met)

    def test_delivered_task_still_gets_a_verdict(self) -> None:
        now = fields.Datetime.now()
        late = self.env["project.task"].create(
            {
                "name": "Late",
                "project_id": self.project_pigs.id,
                "date_end": now - timedelta(days=5),
            }
        )
        late.state = "done"
        self.assertEqual(late.deadline_met, "missed")

    def test_task_and_project_agree_on_compliance(self) -> None:
        """The two used to return different answers about the same task."""
        now = fields.Datetime.now()
        project = self.env["project.project"].create({"name": "Compliance"})
        cancelled_late = self.env["project.task"].create(
            {
                "name": "Cancelled late",
                "project_id": project.id,
                "date_end": now - timedelta(days=5),
            }
        )
        cancelled_late.state = "canceled"
        on_time = self.env["project.task"].create(
            {
                "name": "On time",
                "project_id": project.id,
                "date_end": now + timedelta(days=5),
            }
        )
        on_time.state = "done"
        self.env.invalidate_all()

        self.assertFalse(cancelled_late.deadline_met)
        self.assertEqual(on_time.deadline_met, "met")
        self.assertEqual(project.deadline_compliance_pct, 100.0)

    def test_metric_sql_reads_the_declared_state_lists(self) -> None:
        """The SQL used to spell 'done', 'canceled' by hand in seventeen
        places, which is how the two definitions drifted apart."""
        from odoo.addons.project.models import project_project

        source = pathlib.Path(project_project.__file__).read_text(encoding="utf-8")
        self.assertNotIn("'done'", source)
        self.assertNotIn("'canceled'", source)


@tagged("post_install", "-at_install")
class TestPortalWritableFields(TestProjectCommon):
    """The portal allowlist must not grant writes the ORM will honour."""

    def test_status_timestamp_is_not_portal_writable(self) -> None:
        """``readonly=True`` is a client hint, not an ORM guard: listing this
        field let a portal collaborator stamp any value onto the timestamp that
        drives rotting, stage-duration tracking and the burndown chart."""
        Task = self.env["project.task"]
        self.assertNotIn("date_last_status_change", Task.TASK_PORTAL_WRITABLE_FIELDS)
        self.assertIn("date_last_status_change", Task.TASK_PORTAL_READABLE_FIELDS)

    def test_is_closed_is_not_portal_writable(self) -> None:
        """A non-stored compute with no inverse: the write was accepted and
        silently did nothing."""
        Task = self.env["project.task"]
        self.assertNotIn("is_closed", Task.TASK_PORTAL_WRITABLE_FIELDS)

    def test_every_portal_writable_field_can_actually_be_written(self) -> None:
        Task = self.env["project.task"]
        for fname in Task.TASK_PORTAL_WRITABLE_FIELDS:
            field = Task._fields[fname]
            with self.subTest(field=fname):
                self.assertFalse(
                    field.readonly and not field.inverse,
                    f"{fname} is readonly with no inverse",
                )
                self.assertFalse(
                    field.compute and not field.store and not field.inverse,
                    f"{fname} is a non-stored compute with no inverse",
                )


@tagged("post_install", "-at_install")
class TestTriageClear(TestProjectCommon):
    def test_clearing_the_personal_triage_takes_effect(self) -> None:
        """``write({"triage_id": False})`` used to delete the key and report
        success while the task stayed in its bucket."""
        task = self.env["project.task"].create(
            {
                "name": "Triaged",
                "project_id": self.project_pigs.id,
                "user_ids": [Command.link(self.env.user.id)],
            }
        )
        self.assertTrue(task.triage_id)
        task.write({"triage_id": False})
        self.env.invalidate_all()
        self.assertFalse(task.triage_id)


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
class TestProjectDatePair(TestProjectCommon):
    def test_create_rejects_a_half_set_pair(self) -> None:
        """``write`` refused it and ``create`` did not, so a one-sided project
        was creatable but then unrepairable field-by-field."""
        with self.assertRaises(UserError):
            self.env["project.project"].create(
                {"name": "Half", "date_start": fields.Date.today()}
            )

    def test_both_dates_together_is_accepted(self) -> None:
        today = fields.Date.today()
        project = self.env["project.project"].create(
            {"name": "Whole", "date_start": today, "date": today}
        )
        self.assertEqual(project.date_start, today)

    def test_neither_date_is_accepted(self) -> None:
        project = self.env["project.project"].create({"name": "Undated"})
        self.assertFalse(project.date_start)
        self.assertFalse(project.date)


@tagged("post_install", "-at_install")
class TestTagNameUniqueness(TestProjectCommon):
    def test_translated_tag_name_is_still_unique(self) -> None:
        """``name`` is translate=True, so it is jsonb and a plain UNIQUE(name)
        compared whole translation documents: once a second language existed,
        two tags could share an English name."""
        self.env["res.lang"]._activate_lang("fr_FR")
        tag = self.env["project.tags"].create({"name": "Uniqueness"})
        tag.with_context(lang="fr_FR").name = "Unicite"
        self.env.flush_all()

        with self.assertRaises(Exception):
            self.env["project.tags"].create({"name": "Uniqueness"})
            self.env.flush_all()


@tagged("post_install", "-at_install")
class TestElapsedBatching(TestProjectCommon):
    """The flow metrics must survive being computed in one calendar round-trip."""

    def test_elapsed_matches_the_calendar(self) -> None:
        calendar = self.env.company.resource_calendar_id
        project = self.env["project.project"].create({"name": "Elapsed"})
        project.company_id = self.env.company
        create_date = fields.Datetime.to_datetime("2026-08-03 06:00:00")
        assign = fields.Datetime.to_datetime("2026-08-04 06:00:00")
        closed = fields.Datetime.to_datetime("2026-08-06 15:00:00")

        task = self.env["project.task"].create(
            {"name": "Measured", "project_id": project.id}
        )
        self.env.cr.execute(
            "UPDATE project_task SET create_date = %s WHERE id = %s",
            (create_date, task.id),
        )
        task.invalidate_recordset(["create_date"])
        task.write({"date_assign": assign, "date_closed": closed})
        self.env.flush_all()

        leave_domain = [
            ("company_id", "in", project.company_id.ids),
            ("time_type", "=", "leave"),
        ]
        for label, start, stop, field in (
            ("queue", create_date, assign, "queue_time_hours"),
            ("lead", create_date, closed, "lead_time_hours"),
            ("cycle", assign, closed, "cycle_time_hours"),
        ):
            expected = calendar.get_work_duration_data(
                start, stop, compute_leaves=True, domain=leave_domain
            )["hours"]
            with self.subTest(span=label):
                self.assertAlmostEqual(task[field], expected, places=4)

    def test_elapsed_costs_one_calendar_call_per_batch(self) -> None:
        """Was exactly 3.00 ``get_work_duration_data`` calls per task — every
        bulk close and bulk assign paid ~3 queries per record."""
        project = self.env["project.project"].create({"name": "Batched"})
        project.company_id = self.env.company
        tasks = self.env["project.task"].create(
            [{"name": f"B{i}", "project_id": project.id} for i in range(10)]
        )
        self.env.flush_all()

        calls = []
        Calendar = type(self.env["resource.calendar"])
        original = Calendar._work_intervals_batch

        def counting(records, *args, **kwargs):
            calls.append(records.ids)
            return original(records, *args, **kwargs)

        self.patch(Calendar, "_work_intervals_batch", counting)
        tasks.write({"date_closed": fields.Datetime.now()})
        self.env.flush_all()

        self.assertLessEqual(
            len(calls),
            1,
            f"one interval fetch for the whole batch, got {len(calls)}",
        )


@tagged("post_install", "-at_install")
class TestResourceLevelling(TestProjectCommon):
    def test_a_shift_that_fits_the_float_is_taken(self) -> None:
        """The guard compared a wall-clock shift against working-hour float, so
        any move crossing a night or a weekend was refused — which is every
        move. Measured before the fix: 15h of float, a move needing ~8 working
        hours, rejected because those 8 hours spanned 50h of wall clock."""
        project = self.env["project.project"].create({"name": "Levelling"})
        project.company_id = self.env.company
        project.allow_dependencies = True
        user = self.env["res.users"].create(
            {"name": "Leveller", "login": "leveller_e", "email": "lev@example.com"}
        )
        Task = self.env["project.task"]
        first = Task.create(
            {
                "name": "First",
                "project_id": project.id,
                "planned_hours": 8.0,
                "allocated_hours": 8.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        Task.create(
            {
                "name": "Chained",
                "project_id": project.id,
                "planned_hours": 8.0,
                "predecessor_ids": [Command.link(first.id)],
            }
        )
        movable = Task.create(
            {
                "name": "Movable",
                "project_id": project.id,
                "planned_hours": 1.0,
                "allocated_hours": 1.0,
                "user_ids": [Command.link(user.id)],
            }
        )
        project.action_compute_critical_path()
        self.env.flush_all()
        start_before = movable.cpm_date_start
        self.assertFalse(movable.is_critical_path)
        self.assertGreater(movable.total_float, 0.0)

        project.action_level_resources()
        self.env.flush_all()

        self.assertGreater(
            movable.cpm_date_start,
            start_before,
            "a non-critical task overlapping its assignee must be shifted",
        )
