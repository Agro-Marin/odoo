"""Regression tests for the 2026-07 project-module audit fixes (Batch A).

Each test pins a specific correctness bug found during the audit so it cannot
silently regress. See doc/pm_excellence_investigation.md for the audit context.
"""

from datetime import datetime, time, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
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


@tagged("-at_install", "post_install")
class TestAuditFixesBatchC(TestProjectCommon):
    """Batch C: correctness/security fixes from the 2026-07 deep audit.

    Each test pins a bug that was reproduced on a disposable DB before the fix
    (see doc/pm_excellence_investigation.md / audit probe harness).
    """

    def test_duplicate_current_baseline(self) -> None:
        """C2: copying the current baseline must not hit the partial unique index."""
        baseline = self.env["project.baseline"].create(
            {"project_id": self.project_pigs.id, "name": "B1"})
        baseline.action_set_current()
        baseline.flush_recordset()
        copy = baseline.copy()  # must not raise IntegrityError
        copy.flush_recordset()
        self.assertFalse(copy.is_current, "the copy must not also be current")

    def test_confidential_child_models_not_leaked(self) -> None:
        """S1: a plain project user who is not a follower of a follower-only
        project must not see that project's risks (mirrors the task rule),
        but must still see risks of an employees-visible project."""
        Risk = self.env["project.risk"]
        secret = Risk.create({
            "project_id": self.project_goats.id,  # privacy_visibility='followers'
            "name": "SECRET", "probability": "5", "impact": "5",
        })
        visible = Risk.create({
            "project_id": self.project_pigs.id,  # privacy_visibility='employees'
            "name": "OPEN", "probability": "1", "impact": "1",
        })
        as_user = Risk.with_user(self.user_projectuser)
        self.assertNotIn(
            secret, as_user.search([("project_id", "=", self.project_goats.id)]),
            "follower-only project's risk must be hidden from non-follower user",
        )
        self.assertIn(
            visible, as_user.search([("project_id", "=", self.project_pigs.id)]),
            "employees-visible project's risk must remain readable",
        )

    def test_typed_dependency_write_resyncs_m2m(self) -> None:
        """D1: editing a typed dependency's predecessor must re-sync the backing
        predecessor_ids M2M."""
        self.project_pigs.allow_dependencies = True
        a, b, c = self.env["project.task"].create([
            {"name": n, "project_id": self.project_pigs.id} for n in ("A", "B", "C")
        ])
        dep = self.env["project.task.dependency"].create(
            {"task_id": b.id, "depends_on_id": a.id, "dependency_type": "fs"})
        b.invalidate_recordset(["predecessor_ids"])
        self.assertEqual(b.predecessor_ids, a)
        dep.depends_on_id = c.id
        b.invalidate_recordset(["predecessor_ids"])
        self.assertEqual(
            b.predecessor_ids, c,
            "editing the dependency must move the M2M link from A to C",
        )

    def test_empty_milestone_mark_done_consistent(self) -> None:
        """M1: an empty milestone must be non-markable in both the saved and
        the onchange (NewId) computation."""
        self.project_pigs.allow_milestones = True
        saved = self.env["project.milestone"].create(
            {"project_id": self.project_pigs.id, "name": "M"})
        saved.invalidate_recordset(["can_be_marked_as_done"])
        new_rec = self.env["project.milestone"].new(
            {"project_id": self.project_pigs.id, "name": "Mnew"})
        self.assertFalse(saved.can_be_marked_as_done)
        self.assertEqual(
            saved.can_be_marked_as_done, new_rec.can_be_marked_as_done,
            "saved and onchange computation must agree for an empty milestone",
        )

    def test_resolved_risk_excluded_from_counts(self) -> None:
        """H1: a resolved risk no longer counts toward risk_count / health."""
        risk = self.env["project.risk"].create({
            "project_id": self.project_pigs.id, "name": "R",
            "probability": "5", "impact": "5",
        })
        self.project_pigs.invalidate_recordset(["risk_count"])
        self.assertEqual(self.project_pigs.risk_count, 1)
        risk.state = "resolved"
        self.project_pigs.invalidate_recordset(["risk_count"])
        self.assertEqual(
            self.project_pigs.risk_count, 0,
            "resolved risks must be excluded from the open-risk count",
        )

    def test_canceled_task_not_counted_as_throughput(self) -> None:
        """F1: canceled tasks are not delivered work — excluded from throughput."""
        task = self.env["project.task"].create(
            {"name": "X", "project_id": self.project_pigs.id})
        task.state = "canceled"
        task.date_closed = fields.Datetime.now()
        self.project_pigs.invalidate_recordset(["throughput_week"])
        self.assertEqual(
            self.project_pigs.throughput_week, 0.0,
            "a canceled task must not count as delivered throughput",
        )

    def test_deadline_met_tristate(self) -> None:
        """DM: deadline_met distinguishes 'no deadline / not closed' (empty) from
        'missed' — a Boolean collapsed both to False."""
        no_deadline = self.env["project.task"].create(
            {"name": "no dl", "project_id": self.project_pigs.id})
        now = fields.Datetime.now()
        missed = self.env["project.task"].create({
            "name": "missed", "project_id": self.project_pigs.id,
            "date_end": now - timedelta(days=1), "state": "done",
            "date_closed": now,
        })
        (no_deadline + missed).invalidate_recordset(["deadline_met"])
        self.assertFalse(no_deadline.deadline_met, "no deadline → empty")
        self.assertEqual(missed.deadline_met, "missed", "closed late → 'missed'")

    def test_triage_bucket_must_belong_to_user(self) -> None:
        """A personal triage bucket cannot be assigned to a different user's
        task-triage entry (only the UI domain guarded this before)."""
        bucket = self.env["project.triage"].create(
            {"name": "Inbox", "user_id": self.user_projectuser.id})
        with self.assertRaises(ValidationError):
            self.env["project.task.triage"].create({
                "task_id": self.task_1.id,
                "user_id": self.user_projectmanager.id,  # different user
                "triage_id": bucket.id,
            })

    def test_forecast_wizard_rejects_non_positive_sims(self) -> None:
        """The Monte Carlo wizard must not IndexError on simulation_count <= 0."""
        wizard = self.env["project.forecast.wizard"].create({
            "project_id": self.project_pigs.id,
            "simulation_count": 0,
        })
        with self.assertRaises(UserError):
            wizard.action_run_forecast()

    def test_rating_deadline_is_seeded_and_stable(self) -> None:
        """rating_request_deadline is a plain field: seeded on enabling periodic
        rating and NOT reset to now()+period by an unrelated recompute."""
        step = self.env["project.workflow.step"].create({
            "name": "Periodic",
            "rating_active": True,
            "rating_status": "periodic",
            "rating_status_period": "weekly",
        })
        seeded = step.rating_request_deadline
        self.assertTrue(seeded, "deadline must be seeded when periodic rating on")
        step.invalidate_recordset(["rating_request_deadline"])
        self.assertEqual(
            step.rating_request_deadline, seeded,
            "deadline must survive recompute (no now()-based reset)",
        )

    def test_history_duration_uses_completion_not_today(self) -> None:
        """project.history actual duration must key off real completion (last
        task closure), not the snapshot date."""
        start = fields.Date.today() - timedelta(days=100)
        project = self.env["project.project"].create(
            {"name": "HistProj", "date_start": start})
        task = self.env["project.task"].create(
            {"name": "T", "project_id": project.id})
        # Completed 90 days after start (10 days before "today").
        task.write({"state": "done"})
        task.date_closed = fields.Datetime.to_datetime(start) + timedelta(days=90)
        hist = self.env["project.history"].create_from_project(project)
        self.assertEqual(
            hist.actual_duration_days, 90,
            "duration must be start→last-closure (90d), not start→today (100d)",
        )
        self.assertEqual(hist.date_completed, (start + timedelta(days=90)))

    def test_cpm_float_and_critical_path(self) -> None:
        """CPM must compute correct float / critical-path on a diamond graph.

        A(8)->B(4)->D(2) and A(8)->C(2)->D(2): path ABD=14 is critical, C has
        2h of float. Pins the values so the iterative rewrite can't drift.
        """
        project = self.env["project.project"].create(
            {"name": "CPM", "allow_dependencies": True})

        def mk(name, hours):
            return self.env["project.task"].create({
                "name": name, "project_id": project.id, "allocated_hours": hours,
            })

        a, b, c, d = mk("A", 8), mk("B", 4), mk("C", 2), mk("D", 2)
        b.predecessor_ids = a
        c.predecessor_ids = a
        d.predecessor_ids = b + c
        project.action_compute_critical_path()
        (a + b + c + d).invalidate_recordset(["total_float", "is_critical_path"])
        self.assertTrue(a.is_critical_path and b.is_critical_path and d.is_critical_path)
        self.assertFalse(c.is_critical_path)
        self.assertAlmostEqual(c.total_float, 2.0, places=2)
        for t in (a, b, d):
            self.assertAlmostEqual(t.total_float, 0.0, places=2)

    def test_cpm_long_chain_no_recursion_error(self) -> None:
        """A dependency chain deeper than the Python recursion limit must not
        raise RecursionError (the passes are iterative)."""
        project = self.env["project.project"].create(
            {"name": "DeepCPM", "allow_dependencies": True})
        depth = 1200  # > default recursionlimit (1000)
        tasks = self.env["project.task"].create([
            {"name": f"T{i}", "project_id": project.id, "allocated_hours": 1.0}
            for i in range(depth)
        ]).sorted("id")
        for i in range(1, depth):
            tasks[i].predecessor_ids = tasks[i - 1]
        project.action_compute_critical_path()  # must not raise
        tasks[-1].invalidate_recordset(["is_critical_path"])
        self.assertTrue(tasks[-1].is_critical_path, "the whole chain is critical")

    def test_recurrence_until_respects_user_timezone(self) -> None:
        """repeat_until (a naive calendar Date) must be compared in the user's
        timezone, not UTC — otherwise a boundary occurrence is dropped a day
        early in a negative-offset tz."""
        self.env.user.tz = "Etc/GMT+6"  # UTC-6, no DST
        step = self.env["project.workflow.step"].create(
            {"name": "S", "project_ids": [(4, self.project_pigs.id)]})
        until = fields.Date.today() + timedelta(days=30)
        rec = self.env["project.task.recurrence"].create({
            "repeat_type": "until",
            "repeat_unit": "day",
            "repeat_interval": 1,
            "repeat_until": until,
        })
        # date_end + 1 day = until+1 @ 03:00 UTC = until @ 21:00 local (UTC-6).
        # UTC .date() would be until+1 → skipped; local date is until → created.
        task = self.env["project.task"].create({
            "name": "Recur",
            "project_id": self.project_pigs.id,
            "step_id": step.id,
            "recurrence_id": rec.id,
            "date_end": datetime.combine(until, time(3, 0)),
        })
        created = self.env["project.task.recurrence"]._create_next_occurrences(task)
        self.assertTrue(
            created,
            "boundary occurrence must be created (compared in user tz, not UTC)",
        )

    def test_forecast_throughput_excludes_canceled(self) -> None:
        """Throughput forecasting must count delivered (done) work only — a
        canceled task is not delivery."""
        now = fields.Datetime.now()
        self.env["project.task"].create({
            "name": "done", "project_id": self.project_pigs.id,
            "state": "done", "date_closed": now - timedelta(days=3)})
        self.env["project.task"].create({
            "name": "canceled", "project_id": self.project_pigs.id,
            "state": "canceled", "date_closed": now - timedelta(days=3)})
        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": self.project_pigs.id, "weeks_of_history": 8})
        self.assertEqual(
            sum(wizard._get_weekly_throughput()), 1,
            "only the done task counts toward throughput",
        )

    def test_forecast_throughput_enforces_read_access(self) -> None:
        """The raw-SQL throughput query must not leak a project the user cannot
        read (record rules don't apply to raw SQL — an explicit check does)."""
        wizard = self.env["project.forecast.wizard"].create(
            {"project_id": self.project_goats.id, "weeks_of_history": 8})
        # project_goats is follower-only; user_projectuser is not a follower.
        with self.assertRaises(AccessError):
            wizard.with_user(self.user_projectuser)._get_weekly_throughput()


@tagged("-at_install", "post_install")
class TestAuditFixesBatchD(TestProjectCommon):
    """Batch D: correctness/security/perf fixes from the 2026-07 full-module audit.

    Each test pins a bug reproduced on a disposable DB before the fix.
    """

    def test_milestone_markable_reacts_to_task_state(self) -> None:
        """can_be_marked_as_done must recompute when a task's state changes.

        Bug: the compute had no @api.depends, so the cached value went stale.
        """
        project = self.env["project.project"].create(
            {"name": "MSReact", "allow_milestones": True}
        )
        milestone = self.env["project.milestone"].create(
            {"name": "M", "project_id": project.id}
        )
        task = self.env["project.task"].create(
            {"name": "mt", "project_id": project.id, "milestone_id": milestone.id}
        )
        self.assertFalse(milestone.can_be_marked_as_done, "open task → not markable")
        task.state = "done"
        # No manual invalidate: @api.depends must trigger the recompute.
        self.assertTrue(
            milestone.can_be_marked_as_done,
            "closing the only task must make the milestone markable (depends)",
        )

    def test_successor_count_on_new_record(self) -> None:
        """_compute_successor_count must not feed NewId values to _read_group in
        an onchange (new, unsaved record)."""
        project = self.env["project.project"].create(
            {"name": "NewSucc", "allow_dependencies": True}
        )
        existing = self.env["project.task"].create(
            {"name": "existing", "project_id": project.id}
        )
        new_task = self.env["project.task"].new(
            {"name": "new", "project_id": project.id, "successor_ids": [(4, existing.id)]}
        )
        # Reading the count on an unsaved record must not raise.
        self.assertEqual(new_task.successor_count, 1)

    def test_workflow_step_clear_command_keeps_owner(self) -> None:
        """Creating a step with a clear/empty project command must keep it a
        personal stage (user_id set), not orphan it.

        Bug: `if vals.get("project_ids")` treated [(5,)] / [(6,0,[])] as truthy
        and wiped user_id."""
        Step = self.env["project.workflow.step"]
        for command in ([(5,)], [(6, 0, [])]):
            step = Step.create({"name": "Personal", "project_ids": command})
            self.assertTrue(step.user_id, f"{command}: must remain a personal stage")
            self.assertFalse(step.project_ids, f"{command}: must have no project")
        # A real project assignment still clears the owner.
        proj_step = Step.create(
            {"name": "Proj", "project_ids": [(4, self.project_pigs.id)]}
        )
        self.assertFalse(proj_step.user_id, "a project stage must not have an owner")

    def test_task_count_archived_project_in_mixed_recordset(self) -> None:
        """task_count of an archived project must not read 0 just because the
        batch also contains an active project.

        Bug: __compute_task_count applied a single batch-wide active_test."""
        active = self.env["project.project"].create({"name": "ActiveP"})
        archived = self.env["project.project"].create({"name": "ArchP"})
        self.env["project.task"].create({"name": "a", "project_id": active.id})
        self.env["project.task"].create(
            [
                {"name": "b1", "project_id": archived.id},
                {"name": "b2", "project_id": archived.id},
            ]
        )
        archived.active = False
        batch = active | archived
        batch.invalidate_recordset(["task_count"])
        self.assertEqual(active.task_count, 1)
        self.assertEqual(
            archived.task_count, 2, "archived project must still count its tasks"
        )

    def test_unlink_keeps_shared_analytic_account(self) -> None:
        """Deleting one project must not delete an analytic account another
        project still references (ondelete=set null would orphan the sibling)."""
        plan = self.env["account.analytic.plan"].search([], limit=1)
        account = self.env["account.analytic.account"].create(
            {"name": "Shared", "plan_id": plan.id}
        )
        p1 = self.env["project.project"].create(
            {"name": "S1", "account_id": account.id}
        )
        p2 = self.env["project.project"].create(
            {"name": "S2", "account_id": account.id}
        )
        p1.unlink()
        self.assertTrue(
            account.exists(), "shared account must survive while a sibling uses it"
        )
        self.assertEqual(p2.account_id, account, "sibling must keep its account")
        p2.unlink()
        self.assertFalse(
            account.exists(), "account must be removed once no project uses it"
        )

    def test_message_subscribe_none_safe_and_no_mutation(self) -> None:
        """message_subscribe must tolerate partner_ids=None and never mutate the
        caller's list."""
        task = self.env["project.task"].create(
            {"name": "sub", "project_id": self.project_pigs.id}
        )
        # No crash with a None partner list.
        task.message_subscribe(subtype_ids=None)
        # Caller's list is not mutated.
        partners = [self.user_projectmanager.partner_id.id]
        original = list(partners)
        task.message_subscribe(partner_ids=partners)
        self.assertEqual(partners, original, "caller's list must not be mutated")

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

    def test_triage_user_cannot_edit_another_users_bucket(self) -> None:
        """Personal triage buckets are per-user: any internal user manages their
        own, but the own-bucket record rule blocks editing someone else's.

        (project.triage keeps base.group_user CRUD — it is a personal model like
        vanilla personal stages — and the global rule scopes access to
        user_id in (False, self).)"""
        Triage = self.env["project.triage"]
        own = Triage.with_user(self.user_projectuser).create(
            {"name": "Mine", "user_id": self.user_projectuser.id}
        )
        own.write({"name": "Renamed"})
        self.assertEqual(own.name, "Renamed")
        other = Triage.sudo().create(
            {"name": "Other", "user_id": self.user_projectmanager.id}
        )
        with self.assertRaises(AccessError):
            other.with_user(self.user_projectuser).write({"name": "Hijacked"})


@tagged("-at_install", "post_install")
class TestAuditFixesBatchE(TestProjectCommon):
    """Batch E: behaviour/perf fixes from the 2026-07 full-module audit
    (follower propagation, benefit re-nag, batched syncs)."""

    def test_benefit_cron_does_not_renag_after_completion(self) -> None:
        """Once a reminder is scheduled for a review_date, the cron must not
        re-create it on later runs (even after the user completes it). It
        re-arms only when review_date moves forward."""
        Benefit = self.env["project.benefit"]
        today = fields.Date.context_today(Benefit)
        benefit = Benefit.create({
            "name": "Reduce cost",
            "project_id": self.project_pigs.id,
            "accountable_id": self.user_projectmanager.id,
            "review_date": today - timedelta(days=5),
            "state": "tracking",
        })
        Benefit._cron_check_review_dates()
        acts = self.env["mail.activity"].search(
            [("res_model", "=", "project.benefit"), ("res_id", "=", benefit.id)]
        )
        self.assertEqual(len(acts), 1, "first run schedules one reminder")
        self.assertEqual(benefit.review_reminder_date, benefit.review_date)
        # User completes (deletes) the activity, then the cron runs again.
        acts.unlink()
        Benefit._cron_check_review_dates()
        self.assertEqual(
            self.env["mail.activity"].search_count(
                [("res_model", "=", "project.benefit"), ("res_id", "=", benefit.id)]
            ),
            0,
            "cron must NOT re-nag for the same review_date after completion",
        )
        # Moving review_date forward re-arms the reminder.
        benefit.review_date = today - timedelta(days=1)
        Benefit._cron_check_review_dates()
        self.assertEqual(
            self.env["mail.activity"].search_count(
                [("res_model", "=", "project.benefit"), ("res_id", "=", benefit.id)]
            ),
            1,
            "a new review_date must schedule a fresh reminder",
        )

    def test_unsubscribe_removes_follower_from_closed_task(self) -> None:
        """Removing a project follower must drop them from CLOSED tasks too,
        not just open ones (portal access hinges on task followers)."""
        project = self.env["project.project"].create({"name": "FollowP"})
        closed = self.env["project.task"].create(
            {"name": "closed", "project_id": project.id, "state": "done"}
        )
        self.assertTrue(closed.is_closed)
        closed.message_subscribe(partner_ids=self.partner_2.ids)
        self.assertIn(self.partner_2, closed.message_partner_ids)
        project.message_unsubscribe(partner_ids=self.partner_2.ids)
        self.assertNotIn(
            self.partner_2,
            closed.message_partner_ids,
            "follower must be removed from the closed task as well",
        )

    def test_add_followers_covers_closed_tasks(self) -> None:
        """A partner added to the project must follow their CLOSED tasks too."""
        project = self.env["project.project"].create(
            {"name": "AddF", "partner_id": self.partner_1.id}
        )
        closed = self.env["project.task"].create({
            "name": "closed",
            "project_id": project.id,
            "partner_id": self.partner_1.id,
            "state": "done",
        })
        self.assertTrue(closed.is_closed)
        project._add_followers(self.partner_1)
        self.assertIn(
            self.partner_1,
            closed.message_partner_ids,
            "partner must follow their closed task after being added",
        )

    def test_batch_typed_dependencies_sync_all(self) -> None:
        """Creating several typed dependencies at once must sync every
        predecessor_ids link (batched _sync_to_m2m), with no cycle false-positive."""
        project = self.env["project.project"].create(
            {"name": "BatchDep", "allow_dependencies": True}
        )
        a, b, c, d = self.env["project.task"].create(
            [{"name": n, "project_id": project.id} for n in ("A", "B", "C", "D")]
        )
        self.env["project.task.dependency"].create([
            {"task_id": b.id, "depends_on_id": a.id},
            {"task_id": c.id, "depends_on_id": a.id},
            {"task_id": d.id, "depends_on_id": b.id},
        ])
        (b + c + d).invalidate_recordset(["predecessor_ids"])
        self.assertEqual(b.predecessor_ids, a)
        self.assertEqual(c.predecessor_ids, a)
        self.assertEqual(d.predecessor_ids, b)

    def test_batch_create_populates_triage_for_all_assignees(self) -> None:
        """Batch-creating tasks with different assignees must give each
        (task, user) a triage bucket (batched _populate_missing_triages)."""
        project = self.env["project.project"].create({"name": "TriageBatch"})
        tasks = self.env["project.task"].create([
            {
                "name": "t1",
                "project_id": project.id,
                "user_ids": [(6, 0, self.user_projectuser.ids)],
            },
            {
                "name": "t2",
                "project_id": project.id,
                "user_ids": [(6, 0, self.user_projectmanager.ids)],
            },
        ])
        rows = self.env["project.task.triage"].sudo().search(
            [("task_id", "in", tasks.ids)]
        )
        self.assertEqual(len(rows), 2, "each assignee gets a triage row")
        self.assertTrue(
            all(row.triage_id for row in rows),
            "every triage row must get a default bucket",
        )


@tagged("-at_install", "post_install")
class TestAuditFixesBatchF(TestProjectCommon):
    """Batch F: coverage for previously-untested fork models/paths
    (project.phase.write, project.role, project.gate.criterion, rating cron)."""

    def test_phase_write_company_switch_guard(self) -> None:
        """Switching a phase's company must raise while a project of a different
        company is still assigned to it."""
        company_a = self.env["res.company"].create({"name": "Co A"})
        company_b = self.env["res.company"].create({"name": "Co B"})
        phase = self.env["project.phase"].create(
            {"name": "Planning", "company_id": company_a.id}
        )
        self.env["project.project"].create({
            "name": "In phase",
            "phase_id": phase.id,
            "company_id": company_a.id,
        })
        with self.assertRaises(UserError):
            phase.company_id = company_b.id
        # No conflicting project → the switch is allowed.
        empty_phase = self.env["project.phase"].create(
            {"name": "Empty", "company_id": company_a.id}
        )
        empty_phase.company_id = company_b.id
        self.assertEqual(empty_phase.company_id, company_b)

    def test_phase_archive_cascades_to_projects(self) -> None:
        """Archiving a phase archives every project assigned to it."""
        phase = self.env["project.phase"].create({"name": "Closing"})
        project = self.env["project.project"].create(
            {"name": "Cascade", "phase_id": phase.id}
        )
        self.assertTrue(project.active)
        phase.active = False
        self.assertFalse(
            project.active, "archiving the phase must archive its projects"
        )

    def test_role_defaults_and_task_assignment(self) -> None:
        """project.role gets a color in range and can be assigned to a task."""
        role = self.env["project.role"].create({"name": "Reviewer"})
        self.assertTrue(1 <= role.color <= 11, "default color must be in [1, 11]")
        self.task_1.role_ids = [(4, role.id)]
        self.assertIn(role, self.task_1.role_ids)
        # copy suffix from the shared mixin.
        self.assertEqual(role.copy().name, "Reviewer (copy)")

    def test_gate_criterion_counts(self) -> None:
        """criteria_met_count / criteria_total_count must reflect the criteria
        and react to a criterion being marked met."""
        gate = self.env["project.gate"].create(
            {"name": "G1", "project_id": self.project_pigs.id}
        )
        c1 = self.env["project.gate.criterion"].create(
            {"gate_id": gate.id, "name": "Budget ok"}
        )
        self.env["project.gate.criterion"].create(
            {"gate_id": gate.id, "name": "Scope ok"}
        )
        self.assertEqual(gate.criteria_total_count, 2)
        self.assertEqual(gate.criteria_met_count, 0)
        c1.met = True
        self.assertEqual(
            gate.criteria_met_count, 1, "met count must react to criterion.met"
        )

    def test_gate_criterion_milestone_cross_project_guard(self) -> None:
        """A gate's trigger milestone must belong to the gate's project."""
        self.project_goats.allow_milestones = True
        other_ms = self.env["project.milestone"].create(
            {"name": "Other", "project_id": self.project_goats.id}
        )
        with self.assertRaises(ValidationError):
            self.env["project.gate"].create({
                "name": "BadGate",
                "project_id": self.project_pigs.id,
                "milestone_id": other_ms.id,
            })

    def test_send_rating_all_advances_deadline(self) -> None:
        """The rating cron must process an overdue periodic step and push its
        rating_request_deadline into the future (idempotent per day)."""
        step = self.env["project.workflow.step"].create({
            "name": "Periodic",
            "project_ids": [(4, self.project_pigs.id)],
            "rating_active": True,
            "rating_status": "periodic",
            "rating_status_period": "weekly",
        })
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
