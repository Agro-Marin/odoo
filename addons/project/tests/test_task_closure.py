"""What closes a task, what delivers one, and what each metric counts."""

import pathlib
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestClosureSignal(TestProjectCommon):
    """date_closed must track state, the signal every metric already reads."""

    def setUp(self) -> None:
        super().setUp()
        self.project = self.env["project.project"].create({"name": "Closure"})
        self.open_step, self.next_step, self.folded_step = self.env[
            "project.workflow.step"
        ].create(
            [
                {
                    "name": name,
                    "sequence": seq,
                    "fold": fold,
                    "project_ids": [Command.link(self.project.id)],
                }
                for name, seq, fold in (
                    ("Open", 1, False),
                    ("Next", 2, False),
                    ("Done", 9, True),
                )
            ]
        )

    def _task(self, **vals):
        return self.env["project.task"].create(
            {
                "name": "t",
                "project_id": self.project.id,
                "step_id": self.open_step.id,
                **vals,
            }
        )

    def test_closing_via_state_stamps_date_closed(self) -> None:
        """date_closed used to be written ONLY by entering a folded step, so a
        task closed from the state widget looked never-delivered to every
        metric, and a deadline months away reported as missed."""
        task = self._task(date_end="2026-12-31 17:00:00")
        task.state = "done"
        self.assertTrue(task.date_closed)
        self.assertEqual(task.deadline_met, "met")

    def test_step_move_preserves_the_closure_timestamp(self) -> None:
        """Dragging a done card to another column must not rewrite history."""
        task = self._task(date_end="2026-12-31 17:00:00")
        task.state = "done"
        stamped = task.date_closed

        task.step_id = self.next_step

        self.assertEqual(task.state, "done")
        self.assertEqual(task.date_closed, stamped)
        self.assertEqual(task.deadline_met, "met")

    def test_folded_step_does_not_close_an_open_task(self) -> None:
        """The mirror case: a closure date on a task that is still in progress."""
        task = self._task()
        task.step_id = self.folded_step
        self.assertNotIn(task.state, ("done", "canceled"))
        self.assertFalse(task.date_closed)

    def test_reopening_clears_the_closure_timestamp(self) -> None:
        task = self._task()
        task.state = "done"
        self.assertTrue(task.date_closed)
        task.state = "in_progress"
        self.assertFalse(task.date_closed)


@tagged("post_install", "-at_install")
class TestStateIsNotDrivenByStep(TestProjectCommon):
    """Where a task sits and what condition it is in are orthogonal."""

    def setUp(self) -> None:
        super().setUp()
        self.project = self.env["project.project"].create({"name": "State"})
        self.step_a, self.step_b = self.env["project.workflow.step"].create(
            [
                {
                    "name": name,
                    "sequence": seq,
                    "project_ids": [Command.link(self.project.id)],
                }
                for name, seq in (("A", 1), ("B", 2))
            ]
        )

    def _task_in_state(self, state):
        task = self.env["project.task"].create(
            {
                "name": state,
                "project_id": self.project.id,
                "step_id": self.step_a.id,
            }
        )
        task.state = state
        return task

    def test_step_move_keeps_the_default_state(self) -> None:
        """A column move used to force in_progress on every open task, so the
        fork's own 'todo' default could not survive one drag."""
        task = self._task_in_state("todo")
        task.step_id = self.step_b
        self.assertEqual(task.state, "todo")

    def test_step_move_clears_a_stale_review_verdict(self) -> None:
        """Verdicts describe the task where it stood, so they do reset — see
        test_change_stage_or_project. Only they do."""
        for state in ("approved", "changes_requested"):
            with self.subTest(state=state):
                task = self._task_in_state(state)
                task.step_id = self.step_b
                self.assertEqual(task.state, "in_progress")

    def test_dependency_blocking_still_works(self) -> None:
        """The transition the compute genuinely owns must be intact."""
        self.project.allow_dependencies = True
        a, b = self.env["project.task"].create(
            [
                {"name": n, "project_id": self.project.id, "step_id": self.step_a.id}
                for n in ("A", "B")
            ]
        )
        b.predecessor_ids = a
        self.assertEqual(b.state, "blocked")
        a.state = "done"
        self.assertEqual(b.state, "in_progress")


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
        # The project-level metrics are a stored snapshot, dated by the cron or
        # by this call; the task-level field is reactive.
        project.action_refresh_metrics()

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
class TestReportStateSelection(TestProjectCommon):
    """The analysis report's state list tracks the task's own."""

    def test_report_state_selections_match_the_task(self) -> None:
        """An incomplete rename left a 'waiting' value that no task can hold,
        and no entry for 'todo' or 'blocked'."""
        expected = {
            v for v, _label in self.env["project.task"]._fields["state"].selection
        }
        for model in (
            "report.project.task.user",
            "project.task.burndown.chart.report",
            "project.cfd.report",
        ):
            with self.subTest(model=model):
                got = {v for v, _label in self.env[model]._fields["state"].selection}
                self.assertEqual(got, expected)

    def test_state_blocked_transition_still_works(self) -> None:
        """The dependency-driven blocked/unblock transition must be intact."""
        project = self.env["project.project"].create(
            {"name": "BlockProj", "allow_dependencies": True}
        )
        a = self.env["project.task"].create({"name": "A", "project_id": project.id})
        b = self.env["project.task"].create({"name": "B", "project_id": project.id})
        b.write({"predecessor_ids": [(4, a.id)]})
        self.assertEqual(b.state, "blocked", "open predecessor must block")
        a.state = "done"
        self.assertEqual(b.state, "in_progress", "clearing blockers must unblock")

    def test_canceled_task_not_counted_as_throughput(self) -> None:
        """F1: canceled tasks are not delivered work — excluded from throughput."""
        task = self.env["project.task"].create(
            {"name": "X", "project_id": self.project_pigs.id}
        )
        task.state = "canceled"
        task.date_closed = fields.Datetime.now()
        self.project_pigs.action_refresh_metrics()
        self.assertEqual(
            self.project_pigs.throughput_week,
            0.0,
            "a canceled task must not count as delivered throughput",
        )

    def test_deadline_met_tristate(self) -> None:
        """DM: deadline_met distinguishes 'no deadline / not closed' (empty) from
        'missed' — a Boolean collapsed both to False."""
        no_deadline = self.env["project.task"].create(
            {"name": "no dl", "project_id": self.project_pigs.id}
        )
        now = fields.Datetime.now()
        missed = self.env["project.task"].create(
            {
                "name": "missed",
                "project_id": self.project_pigs.id,
                "date_end": now - timedelta(days=1),
                "state": "done",
                "date_closed": now,
            }
        )
        (no_deadline + missed).invalidate_recordset(["deadline_met"])
        self.assertFalse(no_deadline.deadline_met, "no deadline → empty")
        self.assertEqual(missed.deadline_met, "missed", "closed late → 'missed'")

    def test_project_change_reopens_only_open_tasks(self) -> None:
        """Re-homing drops a task onto the target project's default non-folded
        step, so an *open* task reopens to in_progress. A closed one does not:
        closed is sticky, the same contract `_compute_state` enforces, because a
        bulk project reorganization must not destroy the closure history that
        lead/cycle/throughput and deadline_met read.
        """
        source = self.env["project.project"].create({"name": "Src"})
        target = self.env["project.project"].create({"name": "Dst"})
        closed, open_task = self.env["project.task"].create(
            [
                {
                    "name": "was done",
                    "project_id": source.id,
                    "state": "done",
                    "date_closed": fields.Datetime.now(),
                },
                {
                    "name": "still open",
                    "project_id": source.id,
                    "state": "changes_requested",
                },
            ]
        )
        closed_at = closed.date_closed
        self.assertTrue(closed_at)

        (closed + open_task).write({"project_id": target.id})

        self.assertEqual(
            closed.state, "done", "a re-homed closed task must keep its state"
        )
        self.assertEqual(
            closed.date_closed, closed_at, "re-homing must not clear the closure date"
        )
        self.assertEqual(
            open_task.state,
            "in_progress",
            "a re-homed open task must reopen onto the target's default step",
        )
        self.assertNotIn(
            open_task.step_id.fold, (True,), "must land on a non-folded step"
        )
