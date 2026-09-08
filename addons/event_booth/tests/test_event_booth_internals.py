from datetime import datetime, timedelta

from odoo import Command
from odoo.fields import Datetime as FieldsDatetime
from odoo.tests.common import tagged, users

from odoo.addons.event_booth.tests.common import TestEventBoothCommon


@tagged("post_install", "-at_install", "event_booth")
class TestEventData(TestEventBoothCommon):
    @users("user_eventmanager")
    def test_event_booth_contact(self):
        """Test contact details computation"""
        customer = self.env["res.partner"].browse(self.event_customer.ids)
        category = self.env["event.booth.category"].browse(
            self.event_booth_category_1.ids
        )
        self.assertTrue(
            all(
                bool(customer[fname])
                for fname in ["name", "email", "country_id", "phone_ids"]
            )
        )
        customer_email = customer.email

        event = self.env["event.event"].create(
            {
                "name": "Event",
                "date_begin": FieldsDatetime.to_string(
                    datetime.today() + timedelta(days=1)
                ),
                "date_end": FieldsDatetime.to_string(
                    datetime.today() + timedelta(days=15)
                ),
                "event_type_id": False,
            }
        )
        self.assertEqual(event.event_booth_ids, self.env["event.booth"])

        booth = self.env["event.booth"].create(
            {
                "name": "Test Booth",
                "booth_category_id": category.id,
                "event_id": event.id,
                "partner_id": customer.id,
            }
        )
        self.assertEqual(booth.contact_name, customer.name)
        self.assertEqual(booth.contact_email, customer_email)
        self.assertEqual(booth.phone_ids, customer._phone_get_number())

        booth.write(
            {
                "contact_email": '"New Emails" <new.email@test.example.com',
                "phone_ids": [Command.clear()],
            }
        )
        self.assertEqual(
            booth.contact_email, '"New Emails" <new.email@test.example.com'
        )
        self.assertFalse(booth.phone_ids)
        self.assertEqual(
            customer.email, customer_email, "No sync from booth to partner"
        )

        # partial update of contact fields: we may end up with mixed contact information, is it a good idea ?
        booth.write({"partner_id": self.event_customer2.id})
        self.assertEqual(booth.contact_name, customer.name)
        self.assertEqual(
            booth.contact_email, '"New Emails" <new.email@test.example.com'
        )
        self.assertEqual(booth.phone_ids, self.event_customer2._phone_get_number())
