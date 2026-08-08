"""Second-pass regressions that need a real ``resource.mixin`` /
``resource.scheduling.mixin`` consumer, which is why they live here rather than
in ``resource`` itself: that module's tests run before this one is in the
registry.
"""

from datetime import datetime

from pytz import utc

from odoo.tests.common import TransactionCase


class TestResourceSecondPassConsumers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Second Pass Co"})
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "SP calendar", "company_id": cls.company.id, "tz": "UTC"}
        )

    def _resource(self, **vals):
        return self.env["resource.resource"].create(
            {
                "name": vals.pop("name", "SP resource"),
                "company_id": vals.pop("company_id", self.company.id),
                "calendar_id": vals.pop("calendar_id", self.calendar.id),
                "tz": vals.pop("tz", "UTC"),
                **vals,
            }
        )

    def test_consumer_can_filter_its_conflicted_records(self):
        resource = self._resource(name="Consumer conflict")
        model = self.env["resource.scheduling.test"]
        vals = {
            "company_id": self.company.id,
            "resource_id": resource.id,
            "date_start": datetime(2026, 3, 4, 8, 0),
            "date_end": datetime(2026, 3, 4, 12, 0),
        }
        first = model.create({"name": "one", **vals})
        second = model.create({"name": "two", **vals})
        conflicted = model.search([("schedule_overlap_count", "!=", 0)])
        self.assertLessEqual({first.id, second.id}, set(conflicted.ids))

    def test_shared_resource_returns_every_record(self):
        shared = self._resource(name="Shared")
        first = self.env["resource.test"].create(
            {"name": "first", "resource_id": shared.id, "company_id": self.company.id}
        )
        second = self.env["resource.test"].create(
            {"name": "second", "resource_id": shared.id, "company_id": self.company.id}
        )
        window = (
            utc.localize(datetime(2026, 3, 2)),
            utc.localize(datetime(2026, 3, 7)),
        )
        work = (first | second)._get_work_days_data_batch(*window)
        leave = (first | second)._get_leave_days_data_batch(*window)
        for result in (work, leave):
            self.assertEqual(set(result), {first.id, second.id})
            self.assertEqual(result[first.id], result[second.id])

    def test_orphan_reservations_are_garbage_collected(self):
        resource = self._resource(name="Orphan maker")
        record = self.env["resource.scheduling.test"].create(
            {
                "name": "will be deleted behind the ORM's back",
                "company_id": self.company.id,
                "resource_id": resource.id,
                "date_start": datetime(2026, 3, 2, 8, 0),
                "date_end": datetime(2026, 3, 2, 17, 0),
            }
        )
        self.env.flush_all()
        record_id = record.id
        self.env.cr.execute(
            "DELETE FROM resource_scheduling_test WHERE id = %s", (record_id,)
        )
        self.env.invalidate_all()

        reservations = self.env["resource.reservation"].search(
            [("res_model", "=", "resource.scheduling.test"), ("res_id", "=", record_id)]
        )
        self.assertTrue(reservations, "precondition: the orphan survives the delete")

        self.env["resource.reservation"]._gc_orphan_reservations()
        self.assertFalse(reservations.exists())

    def test_gc_keeps_live_and_standalone_reservations(self):
        resource = self._resource(name="Keep me")
        live = self.env["resource.scheduling.test"].create(
            {
                "name": "alive",
                "company_id": self.company.id,
                "resource_id": resource.id,
                "date_start": datetime(2026, 3, 2, 8, 0),
                "date_end": datetime(2026, 3, 2, 17, 0),
            }
        )
        standalone = self.env["resource.reservation"].create(
            {
                "name": "no origin",
                "resource_id": resource.id,
                "date_start": datetime(2026, 3, 9, 8, 0),
                "date_end": datetime(2026, 3, 9, 17, 0),
            }
        )
        self.env.flush_all()
        mirrored = live.reservation_ids
        self.assertTrue(mirrored)

        self.env["resource.reservation"]._gc_orphan_reservations()
        self.assertTrue(mirrored.exists(), "a live consumer keeps its reservations")
        self.assertTrue(
            standalone.exists(), "a booking with no origin is not an orphan"
        )
