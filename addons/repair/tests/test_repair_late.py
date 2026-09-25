from datetime import datetime

from freezegun import freeze_time

from odoo.tests import tagged

from .test_repair import TestRepairCommon


@tagged("post_install", "-at_install")
class TestRepairLate(TestRepairCommon):
    @freeze_time("2026-09-26 02:00:00")
    def test_a_repair_due_later_today_is_not_late_west_of_utc(self):
        repair = self._create_simple_repair_order()
        repair.schedule_date = datetime(2026, 9, 26, 3, 0)
        repair.action_validate()
        self.assertEqual(repair.state, "confirmed")
        picking_type = repair.picking_type_id.with_context(tz="America/Mexico_City")
        picking_type.invalidate_recordset(["count_repair_late"])
        self.assertEqual(picking_type.count_repair_late, 0)
