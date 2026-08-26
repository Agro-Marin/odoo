from datetime import datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestTaskReservation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["resource.reservation"]
        cls.project = cls.env["project.project"].create({"name": "Test Project"})
        cls.calendar = cls.env.company.resource_calendar_id
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Test Resource",
                "calendar_id": cls.calendar.id,
            }
        )

    def test_allocated_percentage_default(self):
        task = self.env["project.task"].create(
            {"name": "Test Task", "project_id": self.project.id}
        )
        self.assertEqual(task.allocated_percentage, 100.0)

    def test_reservation_ids_empty(self):
        task = self.env["project.task"].create(
            {"name": "No Reservations", "project_id": self.project.id}
        )
        self.assertEqual(len(task.reservation_ids), 0)

    def test_reservation_ids_populated(self):
        task = self.env["project.task"].create(
            {"name": "Has Reservation", "project_id": self.project.id}
        )
        self.Reservation.create(
            {
                "name": "Manual reservation",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "res_model": "project.task",
                "res_id": task.id,
            }
        )
        task.invalidate_recordset(["reservation_ids"])
        self.assertEqual(len(task.reservation_ids), 1)

    def test_schedule_overlap_count(self):
        task = self.env["project.task"].create(
            {"name": "Conflicted", "project_id": self.project.id}
        )
        self.Reservation.create(
            {
                "name": "Res 1",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "res_model": "project.task",
                "res_id": task.id,
            }
        )
        self.Reservation.create(
            {
                "name": "Res 2 (other task, same resource)",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 10, 0),
                "date_end": datetime(2025, 1, 6, 14, 0),
                "res_model": "project.task",
                "res_id": task.id,
            }
        )
        task.invalidate_recordset(["schedule_overlap_count"])
        self.assertGreater(task.schedule_overlap_count, 0)

    def test_unlink_cleans_reservations(self):
        task = self.env["project.task"].create(
            {"name": "To Delete", "project_id": self.project.id}
        )
        task_id = task.id
        self.Reservation.create(
            {
                "name": "Will be cleaned",
                "resource_id": self.resource.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "res_model": "project.task",
                "res_id": task_id,
            }
        )
        task.unlink()
        remaining = self.Reservation.search(
            [("res_model", "=", "project.task"), ("res_id", "=", task_id)]
        )
        self.assertEqual(
            len(remaining), 0, "Reservations should be cleaned up on unlink"
        )

    def test_get_reservation_date_fields_returns_tuple(self):
        task = self.env["project.task"].create(
            {"name": "Core task", "project_id": self.project.id}
        )
        result = task._get_fields_reservation_date()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_sync_reservations_no_error(self):
        task = self.env["project.task"].create(
            {"name": "Core sync", "project_id": self.project.id}
        )
        task._sync_reservations()
