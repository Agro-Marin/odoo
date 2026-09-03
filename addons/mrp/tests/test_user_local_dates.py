from datetime import date, datetime

from odoo.tests import tagged
from odoo.tests.common import freeze_time
from odoo.tools import format_date

from .common import TestMrpCommon

# 02:00 UTC is 20:00 of the *previous* day in a UTC-6 installation, so this is
# the window in which `fields.Date.today()` and the user's calendar date differ.
EVENING_UTC = "2026-10-12 02:00:00"
LOCAL_DAY = date(2026, 10, 11)
UTC_DAY = date(2026, 10, 12)


@tagged("post_install", "-at_install")
class TestMrpUserLocalDates(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = "America/Mexico_City"

    @freeze_time(EVENING_UTC)
    def test_bom_structure_display_date_is_user_local(self):
        """The BoM structure quotes the reader's calendar date, not UTC's."""
        report = self.env["report.mrp.report_bom_structure"]
        self.assertNotEqual(LOCAL_DAY, UTC_DAY, "the fixture must straddle midnight")

        displayed = report._format_date_display("estimated", 0)

        self.assertIn(format_date(self.env, LOCAL_DAY), displayed)
        self.assertNotIn(format_date(self.env, UTC_DAY), displayed)

    @freeze_time(EVENING_UTC)
    def test_operation_type_late_count_ignores_today(self):
        """An order scheduled for this afternoon is not late this evening."""
        mo, _bom, _product, _p1, _p2 = self.generate_mo(qty_final=1)
        # 22:00 UTC on the 11th is 16:00 local the same day: in the past, but
        # still today, so it must not show up under "Late".
        mo.date_start = datetime(2026, 10, 11, 22, 0, 0)
        self.assertEqual(mo.state, "confirmed")

        picking_type = mo.picking_type_id
        picking_type.invalidate_recordset(["count_mo_late"])

        self.assertEqual(picking_type.count_mo_late, 0)
