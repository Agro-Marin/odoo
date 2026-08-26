from datetime import datetime, timedelta

from odoo import Command, fields
from odoo.fields import Domain
from odoo.tests import tagged

from .test_project_base import TestProjectCommon


@tagged("post_install", "-at_install")
class TestProjectMetricsAreQueryable(TestProjectCommon):
    def test_health_is_searchable(self) -> None:
        self.assertIn(
            self.project_pigs,
            self.env["project.project"].search(
                [
                    (
                        "health_status",
                        "in",
                        ["healthy", "attention", "warning", "critical"],
                    )
                ]
            ),
        )

    def test_health_is_groupable(self) -> None:
        groups = self.env["project.project"]._read_group(
            [("id", "=", self.project_pigs.id)], ["health_status"], ["__count"]
        )
        self.assertEqual(len(groups), 1)

    def test_flow_metrics_are_searchable(self) -> None:
        Project = self.env["project.project"]
        domain = Domain.OR(
            Domain(fname, ">=", 0)
            for fname in (
                "wip_count",
                "avg_lead_time",
                "avg_cycle_time",
                "throughput_week",
                "deadline_compliance_pct",
            )
        )
        self.assertIsInstance(Project.search_count(domain), int)

    def test_the_snapshot_is_dated_not_reactive(self) -> None:
        project = self.env["project.project"].create({"name": "Snapshot"})
        self.env["project.task"].create(
            [{"name": f"open {i}", "project_id": project.id} for i in range(3)]
        )
        self.env.flush_all()
        stale = project.wip_count

        project.action_refresh_metrics()
        self.assertEqual(project.wip_count, 3)
        self.assertNotEqual(
            stale, None, "the snapshot exists before the refresh, it is just older"
        )

    def test_the_cron_refreshes_every_project(self) -> None:
        project = self.env["project.project"].create({"name": "Cron"})
        self.env["project.task"].create({"name": "one", "project_id": project.id})
        self.env.flush_all()
        self.env["project.project"]._cron_refresh_metrics()
        self.assertEqual(project.wip_count, 1)

    def test_wip_excludes_closed_and_blocked(self) -> None:
        project = self.env["project.project"].create(
            {"name": "WIP", "allow_dependencies": True}
        )
        Task = self.env["project.task"]
        Task.create({"name": "open", "project_id": project.id})
        Task.create({"name": "done", "project_id": project.id, "state": "done"})
        blocker = Task.create({"name": "blocker", "project_id": project.id})
        Task.create(
            {
                "name": "blocked",
                "project_id": project.id,
                "predecessor_ids": [Command.link(blocker.id)],
            }
        )
        self.env.flush_all()
        project.action_refresh_metrics()
        self.assertEqual(project.wip_count, 2)


@tagged("post_install", "-at_install")
class TestTaskLevelMetrics(TestProjectCommon):
    def _task(self, **vals):
        return self.env["project.task"].create(
            {"name": "Metric", "project_id": self.project_pigs.id, **vals}
        )

    def test_cd3_is_cost_of_delay_over_duration(self) -> None:
        task = self._task(planned_hours=4.0, cost_of_delay=100.0)
        self.assertEqual(task.cd3_score, 25.0)

    def test_cd3_needs_both_terms(self) -> None:
        self.assertEqual(self._task(cost_of_delay=100.0).cd3_score, 0.0)
        self.assertEqual(self._task(planned_hours=4.0).cd3_score, 0.0)

    def test_cd3_follows_the_estimate(self) -> None:
        task = self._task(planned_hours=4.0, cost_of_delay=100.0)
        task.planned_hours = 10.0
        self.assertEqual(task.cd3_score, 10.0)

    def test_allocation_state_unestimated(self) -> None:
        self.assertEqual(self._task().allocation_state, "unestimated")

    def test_allocation_state_unallocated(self) -> None:
        self.assertEqual(self._task(planned_hours=8.0).allocation_state, "unallocated")

    def test_allocation_state_under_over_and_exact(self) -> None:
        self.assertEqual(
            self._task(planned_hours=8.0, allocated_hours=4.0).allocation_state,
            "under_allocated",
        )
        self.assertEqual(
            self._task(planned_hours=8.0, allocated_hours=8.0).allocation_state,
            "allocated",
        )
        self.assertEqual(
            self._task(planned_hours=8.0, allocated_hours=12.0).allocation_state,
            "over_allocated",
        )

    def test_planned_resources_must_be_positive(self) -> None:
        from psycopg.errors import CheckViolation

        from odoo.tools import mute_logger

        with mute_logger("odoo.db.cursor"), self.assertRaises(CheckViolation):
            with self.cr.savepoint():
                self._task(planned_resources=0)

    def test_is_overallocated_is_false_without_reservations(self) -> None:
        task = self._task(
            planned_date_begin=datetime(2026, 9, 1, 8, 0),
            date_end=datetime(2026, 9, 1, 12, 0),
        )
        self.assertFalse(task.reservation_ids)
        self.assertFalse(task.is_overallocated)


@tagged("post_install", "-at_install")
class TestResourceReport(TestProjectCommon):
    def test_the_view_answers(self) -> None:
        report = self.env["project.resource.report"]
        rows = report.search([])
        self.assertEqual(
            set(rows.mapped("is_overallocated")) - {True, False},
            set(),
            "is_overallocated must be a boolean for every row",
        )

    def test_the_view_excludes_closed_tasks(self) -> None:
        self.env["project.task"].create(
            {
                "name": "closed",
                "project_id": self.project_pigs.id,
                "state": "done",
                "planned_date_begin": fields.Datetime.now(),
                "date_end": fields.Datetime.now() + timedelta(hours=2),
            }
        )
        self.env.flush_all()
        self.assertNotIn(
            self.project_pigs,
            self.env["project.resource.report"].search([]).mapped("project_id"),
        )

    def test_deadline_compliance_uses_date_closed(self) -> None:
        project = self.project_pigs
        now = fields.Datetime.now()
        self.env["project.task"].create(
            {
                "name": "On time",
                "project_id": project.id,
                "state": "done",
                "date_closed": now - timedelta(days=2),
                "date_end": now - timedelta(days=1),
            }
        )
        self.env["project.task"].create(
            {
                "name": "Late",
                "project_id": project.id,
                "state": "done",
                "date_closed": now,
                "date_end": now - timedelta(days=1),
            }
        )
        project.action_refresh_metrics()
        self.assertEqual(
            project.deadline_compliance_pct,
            50.0,
            "One of two deadline-bearing closed tasks met its deadline → 50%",
        )

    def test_flow_window_keys_off_date_closed(self) -> None:
        project = self.project_pigs
        now = fields.Datetime.now()
        for i in range(4):
            self.env["project.task"].create(
                {
                    "name": f"Closed recently, old deadline {i}",
                    "project_id": project.id,
                    "state": "done",
                    "date_closed": now - timedelta(days=1),
                    "date_end": now - timedelta(days=365),
                }
            )
        self.env["project.task"].create(
            {
                "name": "Open, recent deadline",
                "project_id": project.id,
                "state": "in_progress",
                "date_end": now - timedelta(days=1),
            }
        )
        project.action_refresh_metrics()
        self.assertEqual(project.throughput_week, 1.0)

    def test_health_schedule_respects_utc(self) -> None:
        project = self.env["project.project"].create({"name": "TZProj"})
        now = fields.Datetime.now()
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
        self.assertLess(
            project.health_score,
            100,
            "a task 2h past its UTC deadline must lower the schedule score",
        )

    def test_flow_metrics_exclude_archived(self) -> None:
        project = self.env["project.project"].create({"name": "ArchProj"})
        live = self.env["project.task"].create(
            {"name": "live", "project_id": project.id, "state": "in_progress"}
        )
        archived = self.env["project.task"].create(
            {"name": "arch", "project_id": project.id, "state": "in_progress"}
        )
        project.action_refresh_metrics()
        project._compute_flow_metrics()
        self.assertEqual(project.wip_count, 2)
        archived.active = False
        project.action_refresh_metrics()
        project._compute_flow_metrics()
        self.assertEqual(
            project.wip_count, 1, "archived tasks must be excluded from WIP"
        )
        self.assertTrue(live.active)
