from datetime import datetime

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCalendarBaseSignatureCalls(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.event = cls.env["calendar.event"].create(
            {
                "name": "Signature standup",
                "start": datetime(2026, 3, 2, 9, 0),
                "stop": datetime(2026, 3, 2, 9, 30),
            }
        )

    def test_read_group_takes_the_base_having_default(self):
        rows = self.env["calendar.event"]._read_group(
            [("id", "=", self.event.id)], [], ["__count"], having=None
        )
        self.assertEqual(rows, [(1,)])

    def test_write_takes_the_base_keyword(self):
        self.event.write(vals={"name": "Signature retro"})
        self.assertEqual(self.event.name, "Signature retro")
