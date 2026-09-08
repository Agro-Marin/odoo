from datetime import datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceAssignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Assignment = cls.env["resource.assignment"]
        cls.Reservation = cls.env["resource.reservation"]
        cls.truck = cls.env["resource.resource"].create(
            {"name": "Truck 12", "resource_type": "material", "tz": "UTC"}
        )
        cls.driver = cls.env["resource.resource"].create(
            {"name": "Ana", "resource_type": "user", "tz": "UTC"}
        )
        cls.other_driver = cls.env["resource.resource"].create(
            {"name": "Bo", "resource_type": "user", "tz": "UTC"}
        )
        cls.now = datetime.now().replace(microsecond=0)

    def _assign(self, assignee=None, **vals):
        return self.Assignment.create(
            {
                "resource_id": self.truck.id,
                "assignee_id": (assignee or self.driver).id,
                "role": "driver",
                "date_start": self.now - timedelta(days=1),
                **vals,
            }
        )

    def test_name_and_state(self):
        assignment = self._assign()
        self.assertEqual(assignment.name, "Ana, Driver of Truck 12")
        self.assertEqual(assignment.state, "active")
        assignment.date_end = self.now - timedelta(hours=1)
        self.assertEqual(assignment.state, "ended")
        assignment.write(
            {"date_start": self.now + timedelta(days=1), "date_end": False}
        )
        self.assertEqual(assignment.state, "planned")

    def test_state_is_searchable(self):
        active = self._assign()
        ended = self._assign(
            assignee=self.other_driver, date_end=self.now - timedelta(hours=1)
        )
        planned = self._assign(
            assignee=self.other_driver, date_start=self.now + timedelta(days=2)
        )
        found = self.Assignment.search([("resource_id", "=", self.truck.id)])
        self.assertEqual(found.filtered(lambda a: a.state == "active"), active)
        self.assertEqual(
            self.Assignment.search(
                [("resource_id", "=", self.truck.id), ("state", "=", "active")]
            ),
            active,
        )
        self.assertEqual(
            self.Assignment.search(
                [
                    ("resource_id", "=", self.truck.id),
                    ("state", "in", ["ended", "planned"]),
                ]
            ),
            ended | planned,
        )
        self.assertEqual(
            self.Assignment.search(
                [("resource_id", "=", self.truck.id), ("state", "!=", "active")]
            ),
            ended | planned,
        )

    def test_holder_is_the_current_assignee(self):
        self.assertFalse(self.truck.holder_id)
        self._assign(assignee=self.other_driver, date_end=self.now - timedelta(hours=1))
        self.assertFalse(self.truck.holder_id)
        self._assign()
        self.truck.invalidate_recordset(["holder_id"])
        self.assertEqual(self.truck.holder_id, self.driver)
        self.assertIn(
            self.truck,
            self.env["resource.resource"].search([("holder_id", "=", self.driver.id)]),
        )
        self.assertNotIn(
            self.truck,
            self.env["resource.resource"].search(
                [("holder_id", "=", self.other_driver.id)]
            ),
        )

    def test_holder_by_role_and_moment(self):
        self._assign(role="manager", assignee=self.other_driver)
        self._assign(role="driver")
        self.assertEqual(
            self.Assignment._get_holder(self.truck, role="manager"), self.other_driver
        )
        self.assertEqual(
            self.Assignment._get_holder(self.truck, role="driver"), self.driver
        )
        self.assertFalse(
            self.Assignment._get_holder(self.truck, at=self.now - timedelta(days=5))
        )

    def test_open_ended_custody_books_nothing(self):
        assignment = self._assign()
        self.assertFalse(assignment.reservation_ids)

    def test_bounded_custody_books_the_resource(self):
        assignment = self._assign(date_end=self.now + timedelta(days=3))
        self.assertRecordValues(
            assignment.reservation_ids,
            [
                {
                    "resource_id": self.truck.id,
                    "date_start": self.now - timedelta(days=1),
                    "date_end": self.now + timedelta(days=3),
                    "allocated_percentage": 100.0,
                    "enforcement_mode": "soft",
                    "res_model": "resource.assignment",
                }
            ],
        )
        assignment.date_end = False
        self.assertFalse(assignment.reservation_ids)

    def test_two_bounded_custodies_overlap_as_a_warning(self):
        first = self._assign(date_end=self.now + timedelta(days=3))
        second = self._assign(
            assignee=self.other_driver, date_end=self.now + timedelta(days=2)
        )
        (first | second).invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(first.schedule_overlap_count, 1)
        self.assertEqual(second.schedule_overlap_count, 1)

    def test_capacity_above_one_divides_the_booked_share(self):
        room = self.env["resource.resource"].create(
            {"name": "Room 4", "resource_type": "material", "tz": "UTC", "capacity": 4}
        )
        assignments = self.Assignment.create(
            [
                {
                    "resource_id": room.id,
                    "assignee_id": assignee.id,
                    "role": "custodian",
                    "date_start": self.now - timedelta(days=1),
                    "date_end": self.now + timedelta(days=3),
                }
                for assignee in (self.driver, self.other_driver)
            ]
        )
        self.assertEqual(
            assignments.reservation_ids.mapped("allocated_percentage"), [25.0, 25.0]
        )
        assignments.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(assignments.mapped("schedule_overlap_count"), [0, 0])

    def test_a_loan_conflicts_with_a_planned_shift_on_the_ledger(self):
        loan = self._assign(date_end=self.now + timedelta(days=3))
        self.Reservation.create(
            {
                "name": "Shift",
                "resource_id": self.truck.id,
                "date_start": self.now,
                "date_end": self.now + timedelta(hours=8),
                "res_model": "res.partner",
                "res_id": 1,
            }
        )
        loan.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(loan.schedule_overlap_count, 1)

    def test_only_a_human_can_hold(self):
        machine = self.env["resource.resource"].create(
            {"name": "Press", "resource_type": "material", "tz": "UTC"}
        )
        with self.assertRaises(ValidationError):
            self._assign(assignee=machine)
        with self.assertRaises(ValidationError):
            self.Assignment.create(
                {
                    "resource_id": self.driver.id,
                    "assignee_id": self.driver.id,
                    "date_start": self.now,
                }
            )

    def test_end_before_start_is_rejected(self):
        from odoo.tools import mute_logger

        with self.assertRaises(Exception), mute_logger("odoo.sql_db", "odoo.db.cursor"):
            with self.env.cr.savepoint():
                self._assign(date_end=self.now - timedelta(days=2))

    def test_archiving_releases_the_booking(self):
        assignment = self._assign(date_end=self.now + timedelta(days=3))
        assignment.action_archive()
        self.assertFalse(self.Reservation.search([("resource_id", "=", self.truck.id)]))
        assignment.action_unarchive()
        self.assertEqual(
            self.Reservation.search_count([("resource_id", "=", self.truck.id)]), 1
        )

    def test_a_held_resource_cannot_be_deleted(self):
        from odoo.tools import mute_logger

        self._assign(date_end=self.now + timedelta(days=3))
        with (
            self.assertRaises(Exception),
            mute_logger("odoo.sql_db", "odoo.db.cursor"),
            self.env.cr.savepoint(),
        ):
            self.truck.unlink()

    def test_deleting_the_assignment_releases_the_booking(self):
        assignment = self._assign(date_end=self.now + timedelta(days=3))
        assignment.unlink()
        self.assertFalse(
            self.Reservation.search([("res_model", "=", "resource.assignment")])
        )
