"""End-to-end tests for the project.task → resource.reservation sync flow.

Exercises the canonical assignment path (``employee_ids`` from this
module) wired through ``resource.scheduling.mixin``'s sync lifecycle
and the PMI hours model (planned/allocated/unallocated).  Lives in
core post-t20171: no enterprise dependency required.
"""

from datetime import datetime

from psycopg import IntegrityError

from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestReservationSync(TransactionCase):
    """Verify the CRUD hooks on ``resource.scheduling.mixin`` drive the
    reservation lifecycle end-to-end for ``project.task``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Two companies: the "home" company the employee belongs to and a
        # "foreign" company the editor might have active when editing.
        cls.company_home = cls.env["res.company"].create(
            {"name": "Home Co", "resource_calendar_id": False}
        )
        cls.company_foreign = cls.env["res.company"].create(
            {"name": "Foreign Co", "resource_calendar_id": False}
        )
        # Pin attendance explicitly: in environments where the admin company's
        # calendar carries a non-standard attendance pattern, default_get on
        # ``resource.calendar`` would inherit it and break hour-count tests.
        std_attendance = [
            (
                0,
                0,
                {
                    "name": "Morning",
                    "dayofweek": str(d),
                    "hour_from": 8,
                    "hour_to": 12,
                    "day_period": "morning",
                },
            )
            for d in range(5)
        ] + [
            (
                0,
                0,
                {
                    "name": "Afternoon",
                    "dayofweek": str(d),
                    "hour_from": 13,
                    "hour_to": 17,
                    "day_period": "afternoon",
                },
            )
            for d in range(5)
        ]
        home_cal = cls.env["resource.calendar"].create(
            {
                "name": "Home 40h",
                "tz": "UTC",
                "company_id": cls.company_home.id,
                "attendance_ids": std_attendance,
            }
        )
        foreign_cal = cls.env["resource.calendar"].create(
            {
                "name": "Foreign 40h",
                "tz": "UTC",
                "company_id": cls.company_foreign.id,
                "attendance_ids": std_attendance,
            }
        )
        cls.company_home.resource_calendar_id = home_cal
        cls.company_foreign.resource_calendar_id = foreign_cal

        # tz=UTC on user/employee aligns the resource's timezone with the
        # test calendars (also tz=UTC).  Otherwise the user inherits the
        # admin company's tz (e.g. America/Mexico_City) and
        # ``_get_valid_work_intervals`` interprets attendance hours in that
        # zone — turning a UTC Mon 8-17 input into MX 02-11, intersecting
        # only 3h of the 8-12 attendance.
        cls.user_with_resource = cls.env["res.users"].create(
            {
                "name": "Home Worker",
                "login": "home.worker@test",
                "tz": "UTC",
                "company_id": cls.company_home.id,
                "company_ids": [
                    Command.set([cls.company_home.id, cls.company_foreign.id])
                ],
                "group_ids": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.env.ref("project.group_project_user").id),
                ],
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Home Worker",
                "user_id": cls.user_with_resource.id,
                "company_id": cls.company_home.id,
                "tz": "UTC",
            }
        )

        cls.project = cls.env["project.project"].create(
            {"name": "Test Project", "company_id": cls.company_home.id}
        )
        cls.scheduled_vals = {
            "planned_date_begin": datetime(2026, 5, 4, 8, 0),
            "date_end": datetime(2026, 5, 4, 17, 0),
        }

    # ------------------------------------------------------------------
    # Create-time sync
    # ------------------------------------------------------------------

    def test_create_with_assignee_generates_reservation(self):
        """Creating a scheduled task with an employee must generate exactly
        one reservation for that employee's resource."""
        task = self.env["project.task"].create(
            {
                "name": "Create + assignee",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        self.assertEqual(len(task.reservation_ids), 1)
        self.assertEqual(task.reservation_ids.resource_id, self.employee.resource_id)

    def test_create_without_dates_does_not_generate_reservation(self):
        """No scheduling dates → no reservation even with assignees."""
        task = self.env["project.task"].create(
            {
                "name": "Unscheduled",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
            }
        )
        self.assertFalse(task.reservation_ids)

    # ------------------------------------------------------------------
    # Write-time sync — the scenario the user hit in the UI
    # ------------------------------------------------------------------

    def test_adding_employee_to_existing_task_creates_reservation(self):
        """Replicates the exact UI scenario that failed: a scheduled task
        already exists, then the user assigns someone via write().
        """
        task = self.env["project.task"].create(
            {
                "name": "Existing task",
                "project_id": self.project.id,
                **self.scheduled_vals,
            }
        )
        self.assertFalse(task.reservation_ids)

        task.write({"employee_ids": [Command.link(self.employee.id)]})

        self.assertEqual(
            len(task.reservation_ids),
            1,
            "Adding an assignee with a resource must auto-create its reservation",
        )
        self.assertEqual(task.reservation_ids.resource_id, self.employee.resource_id)

    def test_removing_employee_from_task_removes_its_reservation(self):
        task = self.env["project.task"].create(
            {
                "name": "To be unassigned",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        self.assertEqual(len(task.reservation_ids), 1)

        task.write({"employee_ids": [Command.unlink(self.employee.id)]})

        self.assertFalse(
            task.reservation_ids,
            "Unassigning the last employee must clear the reservation",
        )

    def test_changing_dates_updates_reservation_range(self):
        task = self.env["project.task"].create(
            {
                "name": "Reschedule me",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        reservation = task.reservation_ids
        self.assertEqual(len(reservation), 1)
        new_start = datetime(2026, 6, 1, 8, 0)
        new_end = datetime(2026, 6, 1, 17, 0)

        task.write({"planned_date_begin": new_start, "date_end": new_end})

        self.assertEqual(reservation.date_start, new_start)
        self.assertEqual(reservation.date_end, new_end)

    def test_renaming_task_updates_reservation_name(self):
        """The reservation label mirrors ``display_name`` — renames propagate.

        ``name`` is a sync trigger on project.task; without it, reservations
        kept the task's old title forever.
        """
        task = self.env["project.task"].create(
            {
                "name": "Old title",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        reservation = task.reservation_ids
        self.assertEqual(len(reservation), 1)

        task.name = "New title"

        self.assertEqual(
            reservation.name,
            task.display_name,
            "renaming the task must relabel its reservation",
        )
        self.assertIn("New title", reservation.name)

    def test_clearing_dates_removes_reservations(self):
        task = self.env["project.task"].create(
            {
                "name": "Unschedule me",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        self.assertEqual(len(task.reservation_ids), 1)

        task.write({"planned_date_begin": False, "date_end": False})

        self.assertFalse(task.reservation_ids)

    # ------------------------------------------------------------------
    # Multi-company scenario
    # ------------------------------------------------------------------

    def test_assigning_employee_from_foreign_company_resolves_resource(self):
        """Editing a task from a company different from the employee's home
        must still resolve the resource — the lookup walks
        ``employee.resource_id`` directly, which is already company-scoped.
        """
        task = self.env["project.task"].create(
            {
                "name": "Cross-company edit",
                "project_id": self.project.id,
                **self.scheduled_vals,
            }
        )
        self.assertFalse(task.reservation_ids)

        task.with_company(self.company_foreign).write(
            {"employee_ids": [Command.link(self.employee.id)]}
        )

        self.assertEqual(len(task.reservation_ids), 1)
        self.assertEqual(task.reservation_ids.resource_id, self.employee.resource_id)

    def test_foreign_company_edit_preserves_existing_reservations(self):
        """Touching a sync-trigger field from a foreign company context must
        not destroy existing reservations whose employees belong elsewhere.
        """
        task = self.env["project.task"].create(
            {
                "name": "Keep me",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        reservation = task.reservation_ids
        self.assertEqual(len(reservation), 1)

        task.with_company(self.company_foreign).write({"allocated_percentage": 75.0})

        self.assertTrue(
            reservation.exists(),
            "Existing reservations must survive foreign-company writes.",
        )

    # ------------------------------------------------------------------
    # Multi-employee reconciliation
    # ------------------------------------------------------------------

    def _create_second_assignee(self):
        """Helper: a second user/employee in the home company (tz=UTC)."""
        user = self.env["res.users"].create(
            {
                "name": "Second Worker",
                "login": "second.worker@test",
                "tz": "UTC",
                "company_id": self.company_home.id,
                "company_ids": [Command.set([self.company_home.id])],
                "group_ids": [
                    Command.link(self.env.ref("base.group_user").id),
                    Command.link(self.env.ref("project.group_project_user").id),
                ],
            }
        )
        employee = self.env["hr.employee"].create(
            {
                "name": "Second Worker",
                "user_id": user.id,
                "company_id": self.company_home.id,
                "tz": "UTC",
            }
        )
        return user, employee

    def test_multi_employee_creates_one_reservation_each(self):
        _, second_employee = self._create_second_assignee()
        task = self.env["project.task"].create(
            {
                "name": "Multi-assigned",
                "project_id": self.project.id,
                "employee_ids": [Command.set([self.employee.id, second_employee.id])],
                **self.scheduled_vals,
            }
        )
        self.assertEqual(len(task.reservation_ids), 2)
        self.assertEqual(
            task.reservation_ids.mapped("resource_id").sorted("id"),
            (self.employee.resource_id | second_employee.resource_id).sorted("id"),
        )

    def test_removing_one_of_several_employees_only_clears_its_reservation(self):
        _, second_employee = self._create_second_assignee()
        task = self.env["project.task"].create(
            {
                "name": "Multi then trim",
                "project_id": self.project.id,
                "employee_ids": [Command.set([self.employee.id, second_employee.id])],
                **self.scheduled_vals,
            }
        )
        self.assertEqual(len(task.reservation_ids), 2)

        task.write({"employee_ids": [Command.unlink(self.employee.id)]})

        self.assertEqual(len(task.reservation_ids), 1)
        self.assertEqual(task.reservation_ids.resource_id, second_employee.resource_id)

    # ------------------------------------------------------------------
    # Archive / unarchive mirror
    # ------------------------------------------------------------------

    def test_archiving_task_archives_its_reservations(self):
        task = self.env["project.task"].create(
            {
                "name": "Archive me",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        reservation_id = task.reservation_ids.id
        reservation_no_filter = (
            self.env["resource.reservation"]
            .with_context(active_test=False)
            .browse(reservation_id)
        )

        task.action_archive()

        self.assertFalse(reservation_no_filter.active)
        self.assertFalse(
            task.reservation_ids,
            "Archived reservations must drop out of the default O2M.",
        )

    def test_unarchiving_task_restores_its_reservations(self):
        task = self.env["project.task"].create(
            {
                "name": "Roundtrip",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        task.action_archive()
        task.action_unarchive()

        self.assertEqual(
            len(task.reservation_ids),
            1,
            "Restoring the task must surface its reservation again.",
        )
        self.assertTrue(task.reservation_ids.active)

    # ------------------------------------------------------------------
    # ``user_ids`` is read-only in this fork — guarantee the silent no-op
    # ------------------------------------------------------------------

    def test_writing_user_ids_is_silently_ignored(self):
        """``user_ids`` is a stored compute mirror of ``employee_ids``.

        ``readonly=True`` on the field makes the ORM drop direct writes
        on the floor — this test pins that behavior so a future change
        (e.g. someone adding ``inverse=`` again) is caught immediately.
        Callers that intend to assign someone must write ``employee_ids``.
        """
        task = self.env["project.task"].create(
            {
                "name": "user_ids no-op",
                "project_id": self.project.id,
                **self.scheduled_vals,
            }
        )
        self.assertFalse(task.employee_ids)
        self.assertFalse(task.user_ids)

        task.write({"user_ids": [Command.link(self.user_with_resource.id)]})

        self.assertFalse(
            task.employee_ids,
            "user_ids is read-only — writes must not propagate to employee_ids.",
        )
        self.assertFalse(task.reservation_ids)

    # ------------------------------------------------------------------
    # ``hr.employee.resource_id`` change propagates to reservations
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # PMI hours model: planned / allocated / unallocated
    # ------------------------------------------------------------------

    def test_planned_hours_default_from_range(self):
        """``planned_hours`` auto-computes from the task's date range using
        the company calendar (Mon-Fri 8h/day).
        """
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Planned default",
                    "project_id": self.project.id,
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertEqual(task.planned_hours, 8.0)

    def test_planned_hours_user_override_persists(self):
        """User-set ``planned_hours`` overrides the auto-compute."""
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Planned override",
                    "project_id": self.project.id,
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                    "planned_hours": 20.0,
                }
            )
        )
        self.assertEqual(task.planned_hours, 20.0)

    def test_allocated_hours_single_user_sums_one_reservation(self):
        """1 user with custom calendar → 1 reservation → allocated = its hours."""
        half_calendar = self.env["resource.calendar"].create(
            {
                "name": "Half Day",
                "tz": "UTC",
                "company_id": self.company_home.id,
                "attendance_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Mon AM",
                            "dayofweek": "0",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    )
                ],
            }
        )
        self.employee.resource_calendar_id = half_calendar
        task = self.env["project.task"].create(
            {
                "name": "Half day single user",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                "date_end": datetime(2026, 5, 4, 17, 0),
            }
        )
        # 1 reservation with the user's half calendar → 4h
        self.assertEqual(len(task.reservation_ids), 1)
        self.assertEqual(task.allocated_hours, 4.0)

    def test_allocated_hours_multi_user_sums_reservations(self):
        """≥2 users → N reservations (one per employee) → allocated_hours
        is the SUM (PMI Work semantic: person-hours across resources).
        """
        _, second_employee = self._create_second_assignee()
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Multi user",
                    "project_id": self.project.id,
                    "employee_ids": [
                        Command.set([self.employee.id, second_employee.id])
                    ],
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertEqual(len(task.reservation_ids), 2)
        # Each reservation: Mon 8-17 = 8h. Sum = 16h.
        self.assertEqual(task.allocated_hours, 16.0)

    def test_allocated_hours_zero_user_returns_zero(self):
        """0 users → 0 reservations → allocated_hours = 0.

        Honest signal: no resource is committed.  ``planned_hours``
        keeps the estimate so dashboards retain planning information.
        """
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "No assignee",
                    "project_id": self.project.id,
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertFalse(task.employee_ids)
        self.assertEqual(task.allocated_hours, 0.0)
        self.assertEqual(task.planned_hours, 8.0)
        self.assertEqual(task.allocation_state, "unallocated")

    def test_allocated_hours_scales_by_allocated_percentage(self):
        """``allocated_percentage=50`` over 8 effective hours → 4h reservation
        → 4h allocated.  Pin: percentage flows through the reservation.
        """
        task = self.env["project.task"].create(
            {
                "name": "50%",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                "date_end": datetime(2026, 5, 4, 17, 0),
                "allocated_percentage": 50.0,
            }
        )
        self.assertEqual(task.allocated_hours, 4.0)

    def test_planned_hours_honors_allocated_percentage(self):
        """PMBOK Effort = Duration x Resources x Units.

        ``allocated_percentage=50`` halves planned_hours so allocation_state
        reflects intent honestly: planning at half-time and committing at
        half-time should land on ``allocated``, not ``under_allocated``.
        """
        task = self.env["project.task"].create(
            {
                "name": "Half-time plan",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                "date_end": datetime(2026, 5, 4, 17, 0),
                "allocated_percentage": 50.0,
            }
        )
        self.assertEqual(task.scheduled_hours, 8.0)
        self.assertEqual(task.planned_resources, 1)
        self.assertEqual(task.planned_hours, 4.0)
        self.assertEqual(task.allocated_hours, 4.0)
        self.assertEqual(task.allocation_state, "allocated")

    def test_planned_resources_default_one(self):
        """Default ``planned_resources`` = 1; planned_hours = scheduled_hours."""
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Default resources",
                    "project_id": self.project.id,
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertEqual(task.planned_resources, 1)
        self.assertEqual(task.scheduled_hours, 8.0)
        self.assertEqual(task.planned_hours, 8.0)

    def test_planned_resources_doubles_planned_hours(self):
        """Setting ``planned_resources=2`` doubles planned_hours."""
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Two resources",
                    "project_id": self.project.id,
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                    "planned_resources": 2,
                }
            )
        )
        self.assertEqual(task.scheduled_hours, 8.0)
        self.assertEqual(task.planned_hours, 16.0)

    def test_planned_resources_must_be_positive(self):
        """DB-level CHECK rejects planned_resources <= 0."""
        with (
            self.assertRaises(IntegrityError),
            self.cr.savepoint(),
            mute_logger("odoo.db"),
        ):
            self.env["project.task"].create(
                {
                    "name": "Zero resources",
                    "project_id": self.project.id,
                    "planned_resources": 0,
                }
            )

        with (
            self.assertRaises(IntegrityError),
            self.cr.savepoint(),
            mute_logger("odoo.db"),
        ):
            self.env["project.task"].create(
                {
                    "name": "Negative resources",
                    "project_id": self.project.id,
                    "planned_resources": -1,
                }
            )

    def test_planned_hours_inverse_posts_on_manual_override(self):
        """Direct user write of planned_hours posts a chatter message.

        Stored compute recomputes (triggered by scheduled_hours or
        planned_resources changes) MUST NOT post; only direct writes do.
        """
        task = self.env["project.task"].create(
            {
                "name": "Override case",
                "project_id": self.project.id,
                "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                "date_end": datetime(2026, 5, 4, 17, 0),
            }
        )
        baseline = self.env["mail.message"].search_count(
            [("res_id", "=", task.id), ("model", "=", "project.task")]
        )

        # Dependency-driven recompute: must NOT post.
        task.write({"planned_resources": 2})
        self.assertEqual(task.planned_hours, 16.0)
        after_recompute = self.env["mail.message"].search_count(
            [("res_id", "=", task.id), ("model", "=", "project.task")]
        )
        # planned_resources is tracked → at most one tracking message, and it
        # must not also include a planned_hours override entry.
        self.assertLessEqual(after_recompute - baseline, 1)
        override_msgs = self.env["mail.message"].search(
            [
                ("res_id", "=", task.id),
                ("model", "=", "project.task"),
                ("body", "ilike", "manually overridden"),
            ]
        )
        self.assertFalse(
            override_msgs,
            "Recompute should not trigger override message.",
        )

        # Direct user write: must post override message.
        task.write({"planned_hours": 99.0})
        override_msgs = self.env["mail.message"].search(
            [
                ("res_id", "=", task.id),
                ("model", "=", "project.task"),
                ("body", "ilike", "manually overridden"),
            ]
        )
        self.assertEqual(len(override_msgs), 1)

    def test_allocation_state_unestimated(self):
        """No dates, no resources → unestimated."""
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create({"name": "No dates", "project_id": self.project.id})
        )
        self.assertEqual(task.allocation_state, "unestimated")

    def test_allocation_state_unallocated(self):
        """Dates but no employees → unallocated (intent without commit)."""
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Not assigned",
                    "project_id": self.project.id,
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertEqual(task.planned_hours, 8.0)
        self.assertEqual(task.allocated_hours, 0.0)
        self.assertEqual(task.allocation_state, "unallocated")

    def test_allocation_state_allocated(self):
        """planned_resources=1 + 1 employee → allocated (matches intent)."""
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Allocated",
                    "project_id": self.project.id,
                    "employee_ids": [Command.link(self.employee.id)],
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertEqual(task.planned_hours, 8.0)
        self.assertEqual(task.allocated_hours, 8.0)
        self.assertEqual(task.allocation_state, "allocated")

    def test_allocation_state_under_allocated(self):
        """planned_resources=2, 1 employee → under_allocated."""
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Partial",
                    "project_id": self.project.id,
                    "planned_resources": 2,
                    "employee_ids": [Command.link(self.employee.id)],
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertEqual(task.planned_hours, 16.0)
        self.assertEqual(task.allocated_hours, 8.0)
        self.assertEqual(task.allocation_state, "under_allocated")

    def test_allocation_state_over_allocated(self):
        """planned_resources=1 (default), 2 employees → over_allocated (PM over-allocated)."""
        _, second_employee = self._create_second_assignee()
        task = (
            self.env["project.task"]
            .with_company(self.company_home)
            .create(
                {
                    "name": "Overplanned",
                    "project_id": self.project.id,
                    "employee_ids": [
                        Command.set([self.employee.id, second_employee.id])
                    ],
                    "planned_date_begin": datetime(2026, 5, 4, 8, 0),
                    "date_end": datetime(2026, 5, 4, 17, 0),
                }
            )
        )
        self.assertEqual(task.planned_hours, 8.0)
        self.assertEqual(task.allocated_hours, 16.0)
        self.assertEqual(task.allocation_state, "over_allocated")

    def test_changing_employee_resource_updates_existing_reservations(self):
        task = self.env["project.task"].create(
            {
                "name": "Resource swap",
                "project_id": self.project.id,
                "employee_ids": [Command.link(self.employee.id)],
                **self.scheduled_vals,
            }
        )
        original_resource = self.employee.resource_id
        self.assertEqual(task.reservation_ids.resource_id, original_resource)

        replacement = self.env["resource.resource"].create(
            {
                "name": "Replacement Resource",
                "calendar_id": self.company_home.resource_calendar_id.id,
                "company_id": self.company_home.id,
            }
        )
        self.employee.resource_id = replacement

        self.assertEqual(
            len(task.reservation_ids),
            1,
            "Swapping the employee's resource must not duplicate reservations.",
        )
        self.assertEqual(
            task.reservation_ids.resource_id,
            replacement,
            "The reservation must follow the employee's current resource.",
        )
