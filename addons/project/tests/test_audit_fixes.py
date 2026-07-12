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
