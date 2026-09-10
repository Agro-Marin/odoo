from datetime import UTC, datetime

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceAssetMaintenance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.machinery = cls.env.ref("resource_asset.kind_machinery")
        cls.press = cls.env["resource.asset"].create(
            {"name": "Press 1", "kind_id": cls.machinery.id}
        )
        cls.team = cls.env["maintenance.team"].create({"name": "Mechanics"})
        cls.stage_done = cls.env["maintenance.stage"].search(
            [("done", "=", True)], limit=1
        )
        cls.start = datetime(2026, 3, 2, 8, 0)
        cls.end = datetime(2026, 3, 2, 12, 0)

    def _request(self, **vals):
        return self.env["maintenance.request"].create(
            {
                "name": "Oil change",
                "asset_id": self.press.id,
                "maintenance_team_id": self.team.id,
                "schedule_date": self.start,
                "schedule_end": self.end,
                **vals,
            }
        )

    def _bookings(self):
        return self.env["resource.reservation"].search(
            [("resource_id", "=", self.press.resource_id.id)]
        )

    def test_a_scheduled_request_blocks_the_asset(self):
        request = self._request()
        self.assertRecordValues(
            self._bookings(),
            [
                {
                    "res_model": "maintenance.request",
                    "res_id": request.id,
                    "date_start": self.start,
                    "date_end": self.end,
                    "enforcement_mode": "hard",
                }
            ],
        )
        unavailable = self.press.resource_id._get_unavailable_intervals(
            datetime(2026, 3, 2, tzinfo=UTC), datetime(2026, 3, 3, tzinfo=UTC)
        )[self.press.resource_id.id]
        self.assertTrue(
            any(
                s <= self.start.replace(tzinfo=UTC)
                and e >= self.end.replace(tzinfo=UTC)
                for s, e in unavailable
            )
        )

    def test_the_block_follows_the_schedule_and_the_flag(self):
        request = self._request()
        request.write(
            {
                "schedule_date": datetime(2026, 3, 3, 8, 0),
                "schedule_end": datetime(2026, 3, 3, 9, 0),
            }
        )
        self.assertEqual(self._bookings().date_start, datetime(2026, 3, 3, 8, 0))
        request.block_asset = False
        self.assertFalse(self._bookings())
        request.block_asset = True
        self.assertEqual(len(self._bookings()), 1)

    def test_a_done_or_archived_request_releases_the_asset(self):
        request = self._request()
        request.stage_id = self.stage_done
        self.assertFalse(self._bookings())
        other = self._request(name="Belt")
        self.assertEqual(len(self._bookings()), 1)
        other.archive_equipment_request()
        self.assertFalse(self._bookings())

    def test_two_requests_cannot_block_the_same_window(self):
        from odoo.exceptions import ValidationError

        self._request()
        with self.assertRaises(ValidationError):
            self._request(
                name="Second",
                schedule_date=datetime(2026, 3, 2, 10, 0),
                schedule_end=datetime(2026, 3, 2, 14, 0),
            )

    def test_the_asset_counts_its_requests_and_lends_its_team(self):
        self.press.write({"maintenance_team_id": self.team.id})
        request = self.env["maintenance.request"].create({"name": "Check"})
        request.asset_id = self.press
        self.assertEqual(request.maintenance_team_id, self.team)
        self.press.invalidate_recordset()
        self.assertEqual(self.press.maintenance_count, 1)
        self.assertEqual(self.press.maintenance_open_count, 1)
        self.assertFalse(self._bookings(), "an unscheduled request blocks nothing")

    def test_the_asset_outranks_the_equipment_for_team_and_technician(self):
        """The bridge used to set the asset's team, then let the base compute
        overwrite it with the equipment's."""
        other_team = self.env["maintenance.team"].create({"name": "Electricians"})
        technician = self.env["res.users"].create(
            {"name": "Asset tech", "login": "asset_tech"}
        )
        equipment = self.env["maintenance.equipment"].create(
            {"name": "Old press", "maintenance_team_id": other_team.id}
        )
        self.press.write(
            {"maintenance_team_id": self.team.id, "technician_user_id": technician.id}
        )
        request = self.env["maintenance.request"].create({"name": "Check"})
        request.write({"equipment_id": equipment.id, "asset_id": self.press.id})
        self.assertEqual(request.maintenance_team_id, self.team)
        self.assertEqual(request.user_id, technician)
        request.asset_id = False
        self.assertEqual(request.maintenance_team_id, other_team)

    def test_an_asset_only_request_plans_an_activity_on_the_asset(self):
        request = self._request()
        activity = request.activity_ids.filtered(
            lambda a: (
                a.activity_type_id
                == self.env.ref("maintenance.mail_act_maintenance_request")
            )
        )
        self.assertEqual(len(activity), 1)
        self.assertIn(self.press.name, activity.note)
