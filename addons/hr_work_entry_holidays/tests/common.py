# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.addons.hr_holidays.tests.common import TestHolidayContract
from odoo.addons.hr_work_entry.tests.common import TestWorkEntryBase


class TestWorkEntryHolidaysBase(TestWorkEntryBase, TestHolidayContract):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leave_type.work_entry_type_id = cls.work_entry_type_leave.id
