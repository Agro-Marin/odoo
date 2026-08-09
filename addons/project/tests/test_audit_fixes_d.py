"""Regression tests for the 2026-07 project-module audit (Batch D).

Batch D covers the scheduling/metric layer: the fields the critical path
writes, the single closure signal every metric reads, and the throughput
sample the forecast draws from. Each test pins a behaviour that was wrong in
a way nothing errored on — the numbers were simply false.
"""

from datetime import datetime, timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestCpmFieldOwnership(TestProjectCommon):
    """The CPM output fields must be the module's own, not enterprise's."""

    def test_cpm_fields_are_stored_and_distinct(self) -> None:
        """cpm_date_start/end must be real stored columns.

        They used to be called planned_date_start/planned_date_end.
        project_enterprise (auto_install) declares planned_date_start as a
        NON-stored compute whose inverse writes planned_date_begin — so its
        definition won the field merge, CPM's start was never stored, and
        writing it edited the user's schedule instead.
        """
        Task = self.env["project.task"]
        for fname in ("cpm_date_start", "cpm_date_end"):
            field = Task._fields[fname]
            self.assertTrue(field.store, f"{fname} must be stored")
            self.assertFalse(field.compute, f"{fname} must not be computed")
            self.assertFalse(
                getattr(field, "inverse", None), f"{fname} must have no inverse"
            )

    def test_cpm_does_not_touch_user_entered_dates(self) -> None:
        """Computing the critical path must not edit planned_date_begin/date_end."""
        project = self.env["project.project"].create(
            {"name": "CPM ownership", "allow_dependencies": True}
        )
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        task = self.env["project.task"].create(
            {
                "name": "scheduled",
                "project_id": project.id,
                "step_id": step.id,
                "planned_date_begin": "2026-08-03 08:00:00",
                "date_end": "2026-08-07 17:00:00",
            }
        )
        successor = self.env["project.task"].create(
            {"name": "succ", "project_id": project.id, "step_id": step.id}
        )
        successor.predecessor_ids = task
        before = (task.planned_date_begin, task.date_end, task.scheduled_hours)

        project.action_compute_critical_path()
        task.invalidate_recordset()

        self.assertEqual(
            (task.planned_date_begin, task.date_end, task.scheduled_hours),
            before,
            "CPM must write only its own fields",
        )

    def test_cpm_preserves_the_deadline_of_unscheduled_tasks(self) -> None:
        """The common CPM input is a task with a deadline and no start date.

        The enterprise inverse's else-branch wrote date_end (the deadline) when
        planned_date_begin was unset, so one click replaced every such deadline
        with "now".
        """
        project = self.env["project.project"].create(
            {"name": "CPM deadlines", "allow_dependencies": True}
        )
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        deadline = fields.Datetime.to_datetime("2026-12-31 17:00:00")
        tasks = self.env["project.task"].create(
            [
                {
                    "name": name,
                    "project_id": project.id,
                    "step_id": step.id,
                    "date_end": deadline,
                    "planned_hours": 8.0,
                }
                for name in ("A", "B")
            ]
        )
        tasks[1].predecessor_ids = tasks[0]

        project.action_compute_critical_path()
        tasks.invalidate_recordset()

        for task in tasks:
            self.assertEqual(task.date_end, deadline, "deadline must survive CPM")

    def test_cpm_schedule_shape_is_stable_across_runs(self) -> None:
        """Re-running CPM on unchanged data must not move the schedule.

        CPM used allocated_hours as duration while its own writes inflated
        allocated_hours, so run N's output became run N+1's input and the
        project end drifted two weeks per run.
        """
        project = self.env["project.project"].create(
            {"name": "CPM stability", "allow_dependencies": True}
        )
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        a, b = self.env["project.task"].create(
            [
                {
                    "name": name,
                    "project_id": project.id,
                    "step_id": step.id,
                    "planned_hours": 8.0,
                }
                for name in ("A", "B")
            ]
        )
        b.predecessor_ids = a

        def shape():
            (a + b).invalidate_recordset()
            return [
                (
                    t.cpm_date_end - t.cpm_date_start,
                    round(t.total_float, 4),
                    t.is_critical_path,
                )
                for t in (a + b)
            ]

        # Freeze the clock: CPM anchors its schedule at "now" by design, so
        # only a frozen anchor makes an exact comparison meaningful. What used
        # to drift here was the duration, by two weeks per run.
        with freeze_time("2026-08-03 08:00:00"):
            project.action_compute_critical_path()
            first = shape()
            project.action_compute_critical_path()
            project.action_compute_critical_path()
            self.assertEqual(shape(), first, "the schedule shape must not drift")

    def test_cpm_duration_is_duration_not_effort(self) -> None:
        """Staffing an activity with more people must not make it longer."""
        project = self.env["project.project"].create({"name": "CPM duration"})
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        task = self.env["project.task"].create(
            {
                "name": "one working week",
                "project_id": project.id,
                "step_id": step.id,
                "planned_date_begin": "2026-08-03 08:00:00",
                "date_end": "2026-08-07 17:00:00",
            }
        )
        self.assertEqual(
            task._get_cpm_duration_hours(),
            task.scheduled_hours,
            "a scheduled activity's duration is its working span",
        )

    def test_cpm_survives_a_company_without_a_calendar(self) -> None:
        """plan_hours on an empty calendar recordset used to be a 500."""
        project = self.env["project.project"].create(
            {"name": "CPM no calendar", "allow_dependencies": True}
        )
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        a, b = self.env["project.task"].create(
            [
                {
                    "name": name,
                    "project_id": project.id,
                    "step_id": step.id,
                    "planned_hours": 8.0,
                }
                for name in ("A", "B")
            ]
        )
        b.predecessor_ids = a
        project.company_id.resource_calendar_id = False
        project.invalidate_recordset(["resource_calendar_id"])

        project.action_compute_critical_path()  # must not raise
        project.action_level_resources()  # must not raise

    def test_cpm_honours_plain_m2m_dependencies(self) -> None:
        """A typed dependency anywhere used to hide every plain one."""
        project = self.env["project.project"].create(
            {"name": "CPM edges", "allow_dependencies": True}
        )
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        x, y, z = self.env["project.task"].create(
            [
                {
                    "name": name,
                    "project_id": project.id,
                    "step_id": step.id,
                    "planned_hours": 8.0,
                }
                for name in ("X", "Y", "Z")
            ]
        )
        # X -> Y through the typed model, Y -> Z through the M2M only.
        self.env["project.task.dependency"].create(
            {"task_id": y.id, "depends_on_id": x.id}
        )
        z.predecessor_ids = y

        project.action_compute_critical_path()
        (x + y + z).invalidate_recordset()

        self.assertGreaterEqual(
            z.cpm_date_start,
            y.cpm_date_end,
            "the M2M-only successor must still be scheduled after its predecessor",
        )


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
class TestForecastSampling(TestProjectCommon):
    """A week with no delivery is evidence, not an absent row."""

    def test_zero_delivery_weeks_are_sampled(self) -> None:
        project = self.env["project.project"].create({"name": "Forecast"})
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        now = self.env.cr.now()
        done = self.env["project.task"].create(
            [
                {"name": f"d{i}", "project_id": project.id, "step_id": step.id}
                for i in range(4)
            ]
        )
        done.state = "done"
        self.env["project.task"].create(
            [
                {"name": f"o{i}", "project_id": project.id, "step_id": step.id}
                for i in range(20)
            ]
        )
        self.env.flush_all()
        # Delivery in exactly 2 of the last 12 weeks.
        self.env.cr.execute(
            "UPDATE project_task SET date_closed = %s WHERE id = ANY(%s)",
            (now - timedelta(weeks=1), done[:2].ids),
        )
        self.env.cr.execute(
            "UPDATE project_task SET date_closed = %s WHERE id = ANY(%s)",
            (now - timedelta(weeks=6), done[2:].ids),
        )
        self.env.cr.execute(
            "UPDATE project_project SET create_date = %s WHERE id = %s",
            (now - timedelta(weeks=20), project.id),
        )
        self.env.invalidate_all()

        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": project.id, "weeks_of_history": 12, "simulation_count": 2000}
        )
        sample = wizard._get_weekly_throughput()

        self.assertIn(0, sample, "weeks with no delivery must be sampled")
        self.assertGreaterEqual(len(sample), 12, "every week in the window is a sample")

        wizard.action_run_forecast()
        self.assertGreater(
            len({wizard.p50_weeks, wizard.p85_weeks, wizard.p95_weeks}),
            1,
            "a sample with variance must produce distinct percentiles",
        )
        naive = wizard.remaining_items / (sum(sample) / len(sample))
        self.assertLessEqual(
            wizard.p50_weeks, 2 * naive, "the forecast must not be wildly optimistic"
        )

    def test_backdated_closures_are_not_dropped(self) -> None:
        """The window floor is the earlier of project creation and first
        closure, so imported history still counts."""
        project = self.env["project.project"].create({"name": "Backdated"})
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        now = fields.Datetime.now()
        task = self.env["project.task"].create(
            {"name": "old", "project_id": project.id, "step_id": step.id}
        )
        task.state = "done"
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_task SET date_closed = %s WHERE id = %s",
            (now - timedelta(days=10), task.id),
        )
        self.env.invalidate_all()

        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": project.id, "weeks_of_history": 8}
        )
        self.assertEqual(sum(wizard._get_weekly_throughput()), 1)


@tagged("post_install", "-at_install")
class TestBurnupClosureHistory(TestProjectCommon):
    def test_burnup_flips_at_the_closure_not_at_the_last_step_move(self) -> None:
        """is_closed was derived from the step field's tracking label compared
        against state literals, so it could never be true for a historical
        bucket: the chart only flipped at the last step change."""
        year = datetime.now().year - 1
        project = self.env["project.project"].create({"name": "Burnup"})
        alpha, beta = self.env["project.workflow.step"].create(
            [
                {"name": n, "project_ids": [Command.link(project.id)]}
                for n in ("Alpha", "Beta")
            ]
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_workflow_step SET create_date = %s WHERE id = ANY(%s)",
            (datetime(year, 1, 1), (alpha + beta).ids),
        )
        with freeze_time(f"{year}-01-10"):
            task = self.env["project.task"].create(
                {"name": "hist", "project_id": project.id, "step_id": alpha.id}
            )
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.cr.execute(
            "UPDATE project_task SET create_date = %s WHERE id = %s",
            (datetime(year, 1, 10), task.id),
        )
        with freeze_time(f"{year}-02-10"):
            task.state = "done"
            self.env.flush_all()
            self.env.cr.precommit.run()
        with freeze_time(f"{year}-03-10"):
            task.step_id = beta
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.invalidate_all()

        rows = self.env["project.task.burndown.chart.report"]._read_group(
            [("project_id", "=", project.id)], ["date:month", "is_closed"], ["__count"]
        )
        open_months = sorted(
            str(date)[:7] for date, closed, _count in rows if closed == "open"
        )
        self.assertEqual(
            open_months,
            [f"{year}-01"],
            "only the month before the closure may read as open",
        )


@tagged("post_install", "-at_install")
class TestAuditFixesDMisc(TestProjectCommon):
    def test_planned_hours_estimate_is_not_a_formula_override(self) -> None:
        """Creating a task with an estimate posted a bogus 'manually
        overridden (formula override)' note — on a task with no dates, where
        the formula has no opinion at all."""
        task = self.env["project.task"].create(
            {
                "name": "estimate",
                "project_id": self.project_pigs.id,
                "planned_hours": 5.0,
            }
        )
        self.assertFalse(
            any("manually overridden" in str(m.body) for m in task.message_ids)
        )

    def test_planned_hours_override_is_logged_once_per_batch(self) -> None:
        """A genuine override is still reported, without a message_post per
        record (a 200-task write cost 810 queries and 200 chatter entries)."""
        tasks = self.env["project.task"].create(
            [
                {
                    "name": f"t{i}",
                    "project_id": self.project_pigs.id,
                    "planned_date_begin": "2026-08-03 08:00:00",
                    "date_end": "2026-08-04 17:00:00",
                }
                for i in range(3)
            ]
        )
        self.env.flush_all()
        tasks.write({"planned_hours": 999.0})
        self.env.flush_all()
        for task in tasks:
            self.assertTrue(
                any("manually overridden" in str(m.body) for m in task.message_ids)
            )

    def test_context_default_repeat_until_wins(self) -> None:
        """default_get clobbered a context-supplied default_repeat_until."""
        vals = (
            self.env["project.task"]
            .with_context(default_repeat_until="2030-01-01")
            .default_get(["repeat_until"])
        )
        self.assertEqual(str(vals["repeat_until"]), "2030-01-01")

    def test_empty_assignee_payload_does_not_stamp_date_assign(self) -> None:
        """The web client sends [(6, 0, [])] for "no assignee"; it is truthy."""
        task = self.env["project.task"].create(
            {
                "name": "unassigned",
                "project_id": self.project_pigs.id,
                "user_ids": [Command.set([])],
            }
        )
        self.assertFalse(task.user_ids)
        self.assertFalse(task.date_assign)

    def test_get_unusual_days_accepts_one_date(self) -> None:
        """The signature advertised date_to as optional but crashed without it."""
        self.env["project.task"].get_unusual_days("2026-07-01")  # must not raise

    def test_name_create_seeds_a_default_step(self) -> None:
        """A project created on the fly still gets its first board column.

        The seeding moved from ``name_create`` to ``create`` (so the form,
        imports and scripts get one too); this pins that the dropdown
        quick-create did not lose it in the move."""
        project_id, _name = self.env["project.project"].name_create("On the fly")
        step = self.env["project.project"].browse(project_id).workflow_step_ids
        self.assertEqual(len(step), 1)

    def test_retrospective_actions_list_open_items_first(self) -> None:
        """_order sorted on the raw selection keys, putting Done above Open."""
        retro = self.env["project.retrospective"].create(
            {"name": "R", "project_id": self.project_pigs.id}
        )
        Action = self.env["project.retrospective.action"]
        for name, state in (
            ("z-open", "open"),
            ("a-done", "done"),
            ("m-inprog", "in_progress"),
        ):
            Action.create(
                {
                    "name": name,
                    "retrospective_id": retro.id,
                    "owner_id": self.env.uid,
                    "state": state,
                }
            )
        ordered = Action.search([("retrospective_id", "=", retro.id)]).mapped("state")
        self.assertEqual(ordered, ["open", "in_progress", "done"])

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


@tagged("post_install", "-at_install")
class TestDependencyStoresAgree(TestProjectCommon):
    """predecessor_ids and project.task.dependency are one fact, two tables."""

    def setUp(self) -> None:
        super().setUp()
        self.project = self.env["project.project"].create(
            {"name": "Deps", "allow_dependencies": True}
        )
        self.step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(self.project.id)]}
        )
        self.a, self.b = self.env["project.task"].create(
            [
                {"name": n, "project_id": self.project.id, "step_id": self.step.id}
                for n in ("A", "B")
            ]
        )

    def _rows(self, task):
        return self.env["project.task.dependency"].search([("task_id", "=", task.id)])

    def test_m2m_link_materialises_a_typed_row(self) -> None:
        """An edge drawn on the task form used to exist only in the M2M:
        untyped, lag-less, invisible to everything reading the typed model."""
        self.b.predecessor_ids = self.a
        rows = self._rows(self.b)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.depends_on_id, self.a)
        self.assertEqual(rows.dependency_type, "fs")
        self.assertEqual(rows.lag_hours, 0.0)

    def test_m2m_link_on_create_materialises_a_typed_row(self) -> None:
        task = self.env["project.task"].create(
            {
                "name": "C",
                "project_id": self.project.id,
                "step_id": self.step.id,
                "predecessor_ids": [Command.link(self.a.id)],
            }
        )
        self.assertEqual(self._rows(task).depends_on_id, self.a)

    def test_m2m_unlink_removes_the_typed_row(self) -> None:
        self.b.predecessor_ids = self.a
        self.assertTrue(self._rows(self.b))
        self.b.predecessor_ids = [Command.clear()]
        self.assertFalse(self._rows(self.b))

    def test_typed_row_edit_is_not_undone_by_the_reverse_sync(self) -> None:
        """The typed side carries the richer type/lag; syncing back from the
        M2M must not overwrite it or bounce between the two stores."""
        dependency = self.env["project.task.dependency"].create(
            {
                "task_id": self.b.id,
                "depends_on_id": self.a.id,
                "dependency_type": "ss",
                "lag_hours": 4.0,
            }
        )
        self.assertEqual(self.b.predecessor_ids, self.a)
        self.assertEqual(dependency.dependency_type, "ss")
        self.assertEqual(dependency.lag_hours, 4.0)
        self.assertEqual(len(self._rows(self.b)), 1)

    def test_typed_row_unlink_removes_the_m2m_link(self) -> None:
        dependency = self.env["project.task.dependency"].create(
            {"task_id": self.b.id, "depends_on_id": self.a.id}
        )
        dependency.unlink()
        self.assertFalse(self.b.predecessor_ids)
        self.assertFalse(self._rows(self.b))

    def test_cycle_detection_spans_projects(self) -> None:
        """A dependency may cross projects, so a cycle can leave one and come
        back. Scoping the graph read by project would miss exactly that."""
        other = self.env["project.project"].create(
            {"name": "Other", "allow_dependencies": True}
        )
        other_step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(other.id)]}
        )
        bridge = self.env["project.task"].create(
            {"name": "bridge", "project_id": other.id, "step_id": other_step.id}
        )
        Dependency = self.env["project.task.dependency"]
        Dependency.create({"task_id": bridge.id, "depends_on_id": self.a.id})
        Dependency.create({"task_id": self.b.id, "depends_on_id": bridge.id})
        # a -> bridge -> b ; closing b -> a is a cycle through `other`.
        with self.assertRaises(ValidationError):
            Dependency.create({"task_id": self.a.id, "depends_on_id": self.b.id})

    def test_self_dependency_is_a_cycle(self) -> None:
        with self.assertRaises(Exception):
            self.env["project.task.dependency"].create(
                {"task_id": self.a.id, "depends_on_id": self.a.id}
            )


@tagged("post_install", "-at_install")
class TestElapsedWithoutCalendar(TestProjectCommon):
    def test_elapsed_falls_back_to_wall_clock(self) -> None:
        """With no working calendar the metrics used to report 0.0, which does
        not read as "unknown" — it reads as delivered instantly."""
        project = self.env["project.project"].create({"name": "No calendar"})
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        # resource_calendar_id falls back to the active company, so both the
        # project's company and env.company must be cleared for the project to
        # genuinely resolve no calendar.
        (project.company_id | self.env.company).resource_calendar_id = False
        project.invalidate_recordset(["resource_calendar_id"])
        self.assertFalse(project.resource_calendar_id)

        task = self.env["project.task"].create(
            {"name": "t", "project_id": project.id, "step_id": step.id}
        )
        task.state = "done"
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_task SET create_date = %s, date_assign = %s, "
            "date_closed = %s WHERE id = %s",
            (
                "2026-08-03 08:00:00",
                "2026-08-03 12:00:00",
                "2026-08-04 08:00:00",
                task.id,
            ),
        )
        self.env.invalidate_all()
        task.modified(["create_date", "date_assign", "date_closed"])
        self.env.flush_all()

        self.assertEqual(task.lead_time_hours, 24.0)
        self.assertEqual(task.queue_time_hours, 4.0)
        self.assertEqual(task.cycle_time_hours, 20.0)


@tagged("post_install", "-at_install")
class TestCfdReport(TestProjectCommon):
    """The CFD is reachable from a menu and two buttons but had no test at all,
    so nothing exercised its hand-injected SQL."""

    def test_cfd_reconstructs_step_history(self) -> None:
        year = datetime.now().year - 1
        project = self.env["project.project"].create({"name": "CFD"})
        alpha, beta = self.env["project.workflow.step"].create(
            [
                {"name": n, "sequence": i, "project_ids": [Command.link(project.id)]}
                for i, n in enumerate(("Alpha", "Beta"), start=1)
            ]
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_workflow_step SET create_date = %s WHERE id = ANY(%s)",
            (datetime(year, 1, 1), (alpha + beta).ids),
        )
        with freeze_time(f"{year}-01-10"):
            task = self.env["project.task"].create(
                {"name": "flow", "project_id": project.id, "step_id": alpha.id}
            )
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.cr.execute(
            "UPDATE project_task SET create_date = %s WHERE id = %s",
            (datetime(year, 1, 10), task.id),
        )
        with freeze_time(f"{year}-03-10"):
            task.step_id = beta
            self.env.flush_all()
            self.env.cr.precommit.run()
        self.env.invalidate_all()

        rows = self.env["project.cfd.report"]._read_group(
            [("project_id", "=", project.id)],
            ["date:month", "step_id"],
            ["task_count:sum"],
        )
        per_month = {(str(date)[:7], step.name): count for date, step, count in rows}
        self.assertEqual(
            per_month.get((f"{year}-01", "Alpha")),
            1,
            "the task sat in Alpha in January",
        )
        self.assertEqual(
            per_month.get((f"{year}-03", "Beta")),
            1,
            "and moved to Beta in March",
        )
        self.assertNotIn(
            (f"{year}-03", "Alpha"), per_month, "it is no longer counted in Alpha"
        )

    def test_cfd_requires_date_and_step_groupby(self) -> None:
        with self.assertRaises(UserError):
            self.env["project.cfd.report"]._read_group([], ["step_id"], ["__count"])


@tagged("post_install", "-at_install")
class TestSprintCommitmentHistory(TestProjectCommon):
    def test_closed_sprint_does_not_report_full_completion(self) -> None:
        """Closing a sprint detaches unfinished work, so completion was
        computed against the delivered tasks alone — 100%, always."""
        project = self.env["project.project"].create(
            {"name": "Sprints", "use_sprints": True}
        )
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [Command.link(project.id)]}
        )
        sprint = self.env["project.sprint"].create(
            {
                "name": "S1",
                "project_id": project.id,
                "date_start": "2026-08-03",
                "date_end": "2026-08-14",
            }
        )
        done, todo = self.env["project.task"].create(
            [
                {
                    "name": name,
                    "project_id": project.id,
                    "step_id": step.id,
                    "sprint_id": sprint.id,
                    "story_points": 3.0,
                }
                for name in ("delivered", "carried")
            ]
        )
        done.state = "done"
        sprint.invalidate_recordset()
        self.assertEqual(sprint.task_count, 2)
        self.assertEqual(sprint.completion_pct, 50.0)

        sprint.action_close()
        sprint.invalidate_recordset()

        self.assertFalse(todo.sprint_id, "unfinished work returns to the backlog")
        self.assertEqual(sprint.carried_over_count, 1)
        self.assertEqual(sprint.carried_over_story_points, 3.0)
        self.assertEqual(
            sprint.task_count, 2, "the sprint still knows what it committed to"
        )
        self.assertEqual(sprint.completed_count, 1)
        self.assertEqual(sprint.completion_pct, 50.0, "not 100%")
        self.assertEqual(sprint.story_points_committed, 6.0)
        self.assertEqual(sprint.story_points_completed, 3.0)
