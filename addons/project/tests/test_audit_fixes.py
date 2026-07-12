"""Regression tests for the 2026-07 project-module audit fixes (Batch A).

Each test pins a specific correctness bug found during the audit so it cannot
silently regress. See doc/pm_excellence_investigation.md for the audit context.
"""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.project.tests.test_project_base import TestProjectCommon


@tagged("-at_install", "post_install")
class TestAuditFixes(TestProjectCommon):
    def test_deadline_compliance_uses_date_closed(self) -> None:
        """deadline_compliance_pct must compare actual closure (date_closed) to
        the deadline (date_end), not a column against itself.

        Bug: the SQL read ``date_end <= date_end`` (always true) → every project
        reported 100% compliance.
        """
        project = self.project_pigs
        now = fields.Datetime.now()
        # Task closed on time: closed before its deadline.
        self.env["project.task"].create({
            "name": "On time",
            "project_id": project.id,
            "state": "done",
            "date_closed": now - timedelta(days=2),
            "date_end": now - timedelta(days=1),
        })
        # Task closed late: closed after its deadline.
        self.env["project.task"].create({
            "name": "Late",
            "project_id": project.id,
            "state": "done",
            "date_closed": now,
            "date_end": now - timedelta(days=1),
        })
        project.invalidate_recordset(["deadline_compliance_pct"])
        self.assertEqual(
            project.deadline_compliance_pct,
            50.0,
            "One of two deadline-bearing closed tasks met its deadline → 50%",
        )

    def test_flow_window_keys_off_date_closed(self) -> None:
        """Rolling flow windows (throughput) must select tasks by closure date,
        not by deadline (date_end, which in this fork is the *deadline*)."""
        project = self.project_pigs
        now = fields.Datetime.now()
        # 4 tasks recently closed but with ancient deadlines: MUST all be counted
        # (throughput keys off closure date, not deadline). 4 / 4.0 weeks = 1.0,
        # an exact value that avoids the field's 1-decimal rounding.
        for i in range(4):
            self.env["project.task"].create({
                "name": f"Closed recently, old deadline {i}",
                "project_id": project.id,
                "state": "done",
                "date_closed": now - timedelta(days=1),
                "date_end": now - timedelta(days=365),
            })
        # Not closed, deadline in the recent window: MUST NOT be counted.
        self.env["project.task"].create({
            "name": "Open, recent deadline",
            "project_id": project.id,
            "state": "in_progress",
            "date_end": now - timedelta(days=1),
        })
        project.invalidate_recordset(["throughput_week"])
        # Under the old (buggy) code these keyed off date_end (365d ago) → 0.0.
        self.assertEqual(project.throughput_week, 1.0)

    def test_benefit_review_cron_creates_activity_with_deadline(self) -> None:
        """The benefit-review cron must write ``date_deadline`` on mail.activity
        (the fork's date_deadline→date_end rename is task-only).

        Bug: it wrote ``date_end`` — a field mail.activity does not have — so the
        cron raised ValueError on every run and no reminder was ever created.
        """
        review = fields.Date.context_today(self.env["project.benefit"]) - timedelta(days=1)
        benefit = self.env["project.benefit"].create({
            "name": "Cut fuel cost",
            "project_id": self.project_pigs.id,
            "accountable_id": self.user_projectmanager.id,
            "review_date": review,
            "state": "tracking",
        })
        self.env["project.benefit"]._cron_check_review_dates()
        activity = self.env["mail.activity"].search([
            ("res_model", "=", "project.benefit"),
            ("res_id", "=", benefit.id),
        ])
        self.assertEqual(len(activity), 1, "Cron must schedule exactly one activity")
        self.assertEqual(activity.date_deadline, review)
        # Idempotent: a second run must not duplicate the activity.
        self.env["project.benefit"]._cron_check_review_dates()
        self.assertEqual(
            self.env["mail.activity"].search_count([
                ("res_model", "=", "project.benefit"),
                ("res_id", "=", benefit.id),
            ]),
            1,
            "Cron must be idempotent",
        )

    def test_recurrence_until_requires_valid_future_date(self) -> None:
        """repeat_type='until' with an empty date must raise a clean
        ValidationError, not a TypeError (False < date)."""
        Recurrence = self.env["project.task.recurrence"]
        with self.assertRaises(ValidationError):
            Recurrence.create({"repeat_type": "until"})  # no repeat_until
        today = fields.Date.today()
        with self.assertRaises(ValidationError):
            Recurrence.create({
                "repeat_type": "until",
                "repeat_until": today - timedelta(days=1),
            })
        # A valid future date must succeed.
        rec = Recurrence.create({
            "repeat_type": "until",
            "repeat_until": today + timedelta(days=30),
        })
        self.assertTrue(rec)

    def test_copy_data_preserves_defaults_across_batch(self) -> None:
        """Batch-copying tasks where an earlier task has children must not narrow
        the caller's ``default`` dict for later tasks.

        Bug: the child-copy branch rebound the loop-shared ``default`` to a
        whitelist-narrowed dict, so every task after the first parent-with-child
        silently lost the passed defaults (e.g. name).
        """
        project = self.project_pigs
        parent = self.env["project.task"].create({
            "name": "Parent with child",
            "project_id": project.id,
        })
        self.env["project.task"].create({
            "name": "Child",
            "project_id": project.id,
            "parent_id": parent.id,
        })
        sibling = self.env["project.task"].create({
            "name": "Sibling",
            "project_id": project.id,
        })
        self.assertGreater(sibling.id, parent.id, "parent must be processed first")
        copies = (parent + sibling).copy({"name": "RenamedCopy"})
        self.assertEqual(
            copies[1].name,
            "RenamedCopy",
            "The sibling copy must honour the passed default name, not fall back "
            "to '<name> (copy)' because default was narrowed by the parent's "
            "child-copy branch",
        )

    def test_multi_project_copy_isolates_milestones(self) -> None:
        """Copying several projects at once must give each copy only its own
        milestones, not the union of every source project's milestones."""
        project_a = self.env["project.project"].create({
            "name": "Alpha", "allow_milestones": True,
        })
        project_b = self.env["project.project"].create({
            "name": "Beta", "allow_milestones": True,
        })
        self.env["project.milestone"].create({
            "name": "A-M1", "project_id": project_a.id,
        })
        self.env["project.milestone"].create({
            "name": "B-M1", "project_id": project_b.id,
        })
        copies = (project_a + project_b).copy()
        self.assertEqual(len(copies[0].milestone_ids), 1)
        self.assertEqual(len(copies[1].milestone_ids), 1)
        self.assertEqual(copies[0].milestone_ids.name, "A-M1")
        self.assertEqual(copies[1].milestone_ids.name, "B-M1")

    def test_critical_path_cycle_guard(self) -> None:
        """A dependency cycle reaching the CPM must raise a clean UserError, not
        recurse infinitely (RecursionError → HTTP 500).

        Cycles are normally blocked by @api.constrains, so we inject the reverse
        edge with raw SQL to simulate a constraint-bypassed / drifted graph.
        """
        project = self.env["project.project"].create({
            "name": "CycleProj", "allow_dependencies": True,
        })
        task_a = self.env["project.task"].create({"name": "A", "project_id": project.id})
        task_b = self.env["project.task"].create({"name": "B", "project_id": project.id})
        # A -> B via the ORM (valid, no cycle yet).
        self.env["project.task.dependency"].create({
            "task_id": task_b.id, "depends_on_id": task_a.id,
        })
        # B -> A injected directly, bypassing the cycle constraint.
        self.env.cr.execute(
            """INSERT INTO project_task_dependency
               (task_id, depends_on_id, dependency_type, lag_hours, project_id)
               VALUES (%s, %s, 'fs', 0.0, %s)""",
            (task_a.id, task_b.id, project.id),
        )
        self.env.invalidate_all()
        with self.assertRaises(UserError):
            project.action_compute_critical_path()

    def test_closed_predecessor_count_reacts_to_state_change(self) -> None:
        """closed_predecessor_count must refresh when a predecessor's state
        changes, even though the relation itself is unchanged."""
        self.project_goats.allow_dependencies = True
        (self.task_1 + self.task_2).write({"project_id": self.project_goats.id})
        self.task_1.predecessor_ids = self.task_2
        self.assertEqual(self.task_1.closed_predecessor_count, 0)
        self.task_2.state = "done"
        self.assertEqual(
            self.task_1.closed_predecessor_count,
            1,
            "closing a predecessor must update closed_predecessor_count",
        )


@tagged("-at_install", "post_install")
class TestAuditFixesBatchB(TestProjectCommon):
    """Batch B: correctness/crash fixes from the 2026-07 follow-up audit."""

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

    def test_mass_rename_projects_with_analytic_account(self) -> None:
        """Renaming several projects at once must not raise 'Expected singleton'.

        Bug: write() used self.name (a multi-record set) to update the linked
        analytic accounts.
        """
        p1 = self.env["project.project"].create({"name": "P1"})
        p2 = self.env["project.project"].create({"name": "P2"})
        # Give each its own analytic account (one project per account → the
        # single-project branch that updates the account name).
        p1._create_analytic_account()
        p2._create_analytic_account()
        self.assertTrue(p1.account_id and p2.account_id)
        (p1 + p2).write({"name": "Renamed"})  # must not raise
        self.assertEqual(p1.name, "Renamed")
        self.assertEqual(p2.name, "Renamed")
        self.assertEqual(p1.account_id.name, "Renamed")

    def test_report_successor_ids_is_queryable(self) -> None:
        """report.project.task.user.successor_ids must map to an existing column.

        Bug: column1='predecessor_id' doesn't exist on the rel table → any read
        of the 'Block' field raised a Fault 500.
        """
        project = self.env["project.project"].create(
            {"name": "RepProj", "allow_dependencies": True}
        )
        a = self.env["project.task"].create({"name": "A", "project_id": project.id})
        b = self.env["project.task"].create({"name": "B", "project_id": project.id})
        b.write({"predecessor_ids": [(4, a.id)]})
        self.env.flush_all()
        report = self.env["report.project.task.user"]
        rows = report.search([("task_id", "=", a.id)])
        # Reading the field must not raise; A blocks B, so A is a successor edge.
        self.assertIn(b, rows.successor_ids)

    def test_forecast_wizard_throughput_by_closure(self) -> None:
        """The forecast wizard's throughput query must run (no INTERVAL syntax
        error), count non-template tasks, and bucket by date_closed."""
        project = self.project_pigs
        now = fields.Datetime.now()
        for i in range(3):
            self.env["project.task"].create(
                {
                    "name": f"done {i}",
                    "project_id": project.id,
                    "state": "done",
                    "date_closed": now - timedelta(days=3),
                }
            )
        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": project.id, "weeks_of_history": 8}
        )
        throughput = wizard._get_weekly_throughput()  # must not raise
        self.assertEqual(sum(throughput), 3)

    def test_health_schedule_respects_utc(self) -> None:
        """An open task whose deadline is a couple of hours in the past (naive
        UTC) must count as overdue.

        Bug: the SQL compared date_end (naive UTC) to a bare NOW() (session tz,
        here UTC-6), so a task up to 6h overdue was still counted on-time.
        """
        project = self.env["project.project"].create({"name": "TZProj"})
        now = fields.Datetime.now()  # naive UTC
        self.env["project.task"].create(
            {
                "name": "just overdue",
                "project_id": project.id,
                "state": "in_progress",
                "date_end": now - timedelta(hours=2),
            }
        )
        project.invalidate_recordset(["health_score", "health_status"])
        project._compute_health_indicators()
        # The only deadline-bearing open task is overdue → schedule component 0.
        # (Composite of schedule/staleness/milestone/risk; schedule dragged down.)
        self.assertLess(
            project.health_score,
            100,
            "a task 2h past its UTC deadline must lower the schedule score",
        )

    def test_flow_metrics_exclude_archived(self) -> None:
        """WIP and other flow metrics must not count archived tasks."""
        project = self.env["project.project"].create({"name": "ArchProj"})
        live = self.env["project.task"].create(
            {"name": "live", "project_id": project.id, "state": "in_progress"}
        )
        archived = self.env["project.task"].create(
            {"name": "arch", "project_id": project.id, "state": "in_progress"}
        )
        project.invalidate_recordset(["wip_count"])
        project._compute_flow_metrics()
        self.assertEqual(project.wip_count, 2)
        archived.active = False
        project.invalidate_recordset(["wip_count"])
        project._compute_flow_metrics()
        self.assertEqual(
            project.wip_count, 1, "archived tasks must be excluded from WIP"
        )
        self.assertTrue(live.active)

    def test_personal_triage_search_accepts_scalar(self) -> None:
        """Searching personal_triage_id with a scalar value must not raise
        TypeError ('int' object is not iterable)."""
        # A non-falsy scalar exercises the scalar-iteration path in the search
        # method (a falsy value would be short-circuited before it is reached).
        result = self.env["project.task"].search(
            [("personal_triage_id", "=", 999999999)]
        )
        self.assertEqual(len(result), 0)

    def test_baseline_snapshot_uses_planned_start(self) -> None:
        """Baseline snapshots must capture planned_date_begin (scheduled start),
        not date_assign (actual assignment)."""
        project = self.env["project.project"].create({"name": "BaseProj"})
        begin = fields.Datetime.now() - timedelta(days=5)
        task = self.env["project.task"].create(
            {
                "name": "planned",
                "project_id": project.id,
                "planned_date_begin": begin,
                "date_end": begin + timedelta(days=1),
            }
        )
        baseline = self.env["project.baseline"].create(
            {"name": "B1", "project_id": project.id}
        )
        baseline.action_capture_snapshot()
        line = baseline.line_ids.filtered(lambda line: line.task_id == task)
        self.assertEqual(line.planned_start, begin)

    def test_project_change_reopens_closed_task(self) -> None:
        """Moving a task to another project must reopen it and drop its closure
        date: it lands on the target project's default non-folded step, and in
        this model state follows step, so a closed state there is invalid.

        Pins the fix for the pre-existing TestTaskState.test_change_stage_or_project
        failure (a canceled task stayed canceled after a project change).
        """
        source = self.env["project.project"].create({"name": "Src"})
        target = self.env["project.project"].create({"name": "Dst"})
        task = self.env["project.task"].create(
            {
                "name": "was done",
                "project_id": source.id,
                "state": "done",
                "date_closed": fields.Datetime.now(),
            }
        )
        self.assertTrue(task.date_closed)
        task.write({"project_id": target.id})
        self.assertEqual(
            task.state, "in_progress", "a re-homed task must reopen to an open state"
        )
        self.assertFalse(
            task.date_closed, "reopening must clear the stale closure date"
        )
        self.assertNotIn(task.step_id.fold, (True,), "must land on a non-folded step")

    def test_project_copy_remaps_subtask_dependencies(self) -> None:
        """Copying a project must remap subtask dependencies onto the COPIED
        tasks, not leave them pointing at the originals.

        Pins the fix to _create_task_mapping: child_ids is read back in _order
        (newest-first), not creation order, so the positional zip mis-paired
        originals with copies — mis-wiring dependencies (and crashing with
        `zip strict` when a grandchild zipped against the wrong copy).
        """
        project = self.env["project.project"].create(
            {"name": "DepCopy", "allow_dependencies": True}
        )
        parent = self.env["project.task"].create(
            {"name": "P", "project_id": project.id}
        )
        a = self.env["project.task"].create(
            {"name": "A", "project_id": project.id, "parent_id": parent.id}
        )
        b = self.env["project.task"].create(
            {"name": "B", "project_id": project.id, "parent_id": parent.id}
        )
        a.write({"predecessor_ids": [(4, b.id)]})
        copy = project.copy()
        copied_a = copy.task_ids.filtered(lambda t: t.name == "A")
        copied_b = copy.task_ids.filtered(lambda t: t.name == "B")
        self.assertTrue(copied_a and copied_b, "both subtasks must be copied")
        self.assertEqual(
            copied_a.predecessor_ids,
            copied_b,
            "copied A must depend on the COPIED B, not the original",
        )
        self.assertNotIn(
            b, copied_a.predecessor_ids, "must not reference the original task"
        )

    def test_retrospective_carry_forward_idempotent(self) -> None:
        """action_carry_forward run twice must not duplicate carried actions."""
        project = self.env["project.project"].create({"name": "RetroProj"})
        prev = self.env["project.retrospective"].create(
            {"name": "Sprint 1", "project_id": project.id}
        )
        self.env["project.retrospective.action"].create(
            {
                "name": "Fix CI",
                "retrospective_id": prev.id,
                "state": "open",
                "owner_id": self.user_projectuser.id,
            }
        )
        current = self.env["project.retrospective"].create(
            {"name": "Sprint 2", "project_id": project.id, "previous_id": prev.id}
        )
        current.action_carry_forward()
        current.action_carry_forward()
        self.assertEqual(
            len(current.action_ids), 1, "carry-forward must be idempotent"
        )
