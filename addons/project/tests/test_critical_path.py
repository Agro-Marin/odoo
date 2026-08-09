"""Critical-path computation: which fields it owns, and which edges it sees."""

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import freeze_time, tagged

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
