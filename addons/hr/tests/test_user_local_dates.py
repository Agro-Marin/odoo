from datetime import date, datetime

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import freeze_time

from odoo.addons.hr.tests.common import TestHrCommon

# 2026-01-15 03:00 UTC is 2026-01-14 21:00 in America/Mexico_City (UTC-6), so
# every date-only value below has two possible answers and they disagree. Every
# assertion here is about which of the two the code picks; none of them can pass
# by accident, because a wrong timezone gives the other date, never the same one.
FROZEN_UTC = "2026-01-15 03:00:00"
UTC_TODAY = date(2026, 1, 15)
LOCAL_TODAY = date(2026, 1, 14)
TZ = "America/Mexico_City"


@tagged("post_install", "-at_install")
class TestUserLocalDates(TestHrCommon):
    """Date-only flows must answer in the reader's day, not in UTC's.

    Our companies sit at UTC-6, so between 18:00 and midnight local the two
    disagree and every one of these paths was a day ahead.
    """

    def _employee(self, values=None):
        return (
            self.env["hr.employee"]
            .with_context(tz=TZ)
            .create({"name": "Local Day", "tz": TZ, **(values or {})})
        )

    def test_the_frozen_clock_straddles_midnight(self):
        """Guard the fixture, so the others cannot pass for the wrong reason."""
        with freeze_time(FROZEN_UTC):
            self.assertEqual(fields.Date.today(), UTC_TODAY)
            self.assertEqual(
                fields.Date.context_today(self.env["hr.version"].with_context(tz=TZ)),
                LOCAL_TODAY,
            )

    def test_date_version_defaults_to_the_readers_day(self):
        with freeze_time(FROZEN_UTC):
            defaults = (
                self.env["hr.version"].with_context(tz=TZ).default_get(["date_version"])
            )
        self.assertEqual(defaults["date_version"], LOCAL_TODAY)

    def test_a_contract_ending_today_is_still_in_contract(self):
        with freeze_time(FROZEN_UTC):
            employee = self._employee(
                {
                    "date_version": "2026-01-01",
                    "contract_date_start": "2026-01-01",
                    "contract_date_end": LOCAL_TODAY,
                }
            )
            version = employee.version_id.with_context(tz=TZ)

            self.assertTrue(version._is_in_contract())
            self.assertTrue(version.is_current)
            self.assertFalse(version.is_past)

    def test_a_version_starting_tomorrow_is_not_current_yet(self):
        with freeze_time(FROZEN_UTC):
            employee = self._employee({"date_version": "2026-01-01"})
            first_version = employee.version_id
            employee.create_version({"date_version": UTC_TODAY})

            employee = employee.with_context(tz=TZ)
            employee._compute_current_version_id()

            self.assertEqual(employee.current_version_id, first_version)
            self.assertEqual(employee._get_version(), first_version)

    def test_the_departure_wizard_defaults_to_the_readers_day(self):
        with freeze_time(FROZEN_UTC):
            employee = self._employee({"date_version": "2026-01-01"})
            defaults = (
                self.env["hr.departure.wizard"]
                .with_context(tz=TZ, active_ids=employee.ids)
                .default_get(["departure_date"])
            )
        self.assertEqual(defaults["departure_date"], LOCAL_TODAY)

    def test_a_presence_from_this_evening_still_shows_its_time(self):
        employee = self._employee({"user_id": self.res_users_hr_officer.id})
        self.env["mail.presence"].create(
            {
                "user_id": self.res_users_hr_officer.id,
                "last_presence": datetime(2026, 1, 15, 2, 0, 0),
            }
        )
        with freeze_time(FROZEN_UTC):
            employee = employee.with_context(tz=TZ)
            employee.invalidate_recordset(["last_activity", "last_activity_time"])

            self.assertEqual(employee.last_activity, LOCAL_TODAY)
            self.assertTrue(employee.last_activity_time)
