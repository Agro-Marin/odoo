from datetime import datetime

from freezegun import freeze_time

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEventConfigurator(TransactionCase):
    @freeze_time("2026-09-15 01:00:00")
    def test_an_event_ending_later_today_still_offers_its_tickets_west_of_utc(self):
        product = self.env["product.product"].create(
            {"name": "Evening Seat", "type": "service", "service_tracking": "event"}
        )
        self.env["event.event"].create(
            {
                "name": "Evening Talk",
                "date_begin": datetime(2026, 9, 15, 0, 0),
                "date_end": datetime(2026, 9, 15, 2, 0),
                "date_tz": "America/Mexico_City",
                "event_ticket_ids": [
                    Command.create({"name": "Seat", "product_id": product.id})
                ],
            }
        )
        configurator = (
            self.env["event.event.configurator"]
            .with_context(tz="America/Mexico_City")
            .new({"product_id": product.id})
        )
        self.assertTrue(configurator.has_available_tickets)
