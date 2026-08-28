from datetime import timedelta

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.event.tests.common import EventCase


@tagged("event_internals", "post_install", "-at_install")
class TestSeatsAvailabilityContract(EventCase):
    """`_get_seats_availability` distinguishes "no limit" from "sold out".

    It returns None for the first and 0 for the second, and every caller has to
    keep them apart -- `_get_current_limit_per_order` collapsed both with a
    falsiness test and handed a sold-out ticket the full per-order allowance.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.now = fields.Datetime.now()
        cls.event = cls.env["event.event"].create({
            "date_begin": cls.now + timedelta(days=2),
            "date_end": cls.now + timedelta(days=3),
            "event_mail_ids": [],
            "event_ticket_ids": [
                Command.create({"name": "Unlimited"}),
                Command.create({"name": "Limited", "seats_max": 2}),
            ],
            "name": "Availability contract",
            "question_ids": [],
            "seats_limited": False,
        })
        cls.ticket_unlimited, cls.ticket_limited = cls.event.event_ticket_ids

    def test_availability_is_none_when_unlimited_and_zero_when_sold_out(self):
        no_slot = self.env["event.slot"]
        self.assertEqual(
            self.event._get_seats_availability([(no_slot, self.ticket_unlimited)]),
            [None],
            "an unconstrained ticket has no limit, which is not the same as no seats",
        )
        self.assertEqual(
            self.event._get_seats_availability([(no_slot, self.ticket_limited)]), [2]
        )
        self._create_registrations_for_slot_and_ticket(
            self.event, no_slot, self.ticket_limited, 2
        )
        self.event.invalidate_recordset()
        self.assertEqual(
            self.event._get_seats_availability([(no_slot, self.ticket_limited)]),
            [0],
            "a sold-out ticket has zero seats, which is not the same as no limit",
        )

    def test_a_sold_out_ticket_is_not_orderable(self):
        self._create_registrations_for_slot_and_ticket(
            self.event, self.env["event.slot"], self.ticket_limited, 2
        )
        self.event.invalidate_recordset()
        limits = self.ticket_limited._get_current_limit_per_order(event=self.event)
        self.assertEqual(
            limits[self.ticket_limited.id], 0,
            "a sold-out ticket may not be ordered; treating None and 0 alike "
            "offered it at the full per-order allowance",
        )
        limits = self.ticket_unlimited._get_current_limit_per_order(event=self.event)
        self.assertEqual(
            limits[self.ticket_unlimited.id],
            self.event.EVENT_MAX_TICKETS,
            "an unlimited ticket is capped only by the per-order maximum",
        )

    def test_availability_is_scoped_to_the_pairs_asked_about(self):
        """Asking about one slot/ticket pair must not count another's seats."""
        event = self.env["event.event"].create({
            "date_begin": (self.now + timedelta(days=1)).replace(hour=0, minute=0, second=0),
            "date_end": self.now + timedelta(days=2),
            "date_tz": "UTC",
            "event_mail_ids": [],
            "event_ticket_ids": [Command.create({"name": "T", "seats_max": 10})],
            "is_multi_slots": True,
            "name": "Scoped",
            "question_ids": [],
        })
        slots = self.env["event.slot"].create([
            {
                "date": (self.now + timedelta(days=1)).date(),
                "end_hour": 9.0 + index,
                "event_id": event.id,
                "start_hour": 8.0 + index,
            }
            for index in range(2)
        ])
        ticket = event.event_ticket_ids
        self._create_registrations_for_slot_and_ticket(event, slots[0], ticket, 4)
        event.invalidate_recordset()
        self.assertEqual(
            event._get_seats_availability([(slots[1], ticket)]), [10],
            "the other slot's registrations must not count against this one",
        )
        self.assertEqual(event._get_seats_availability([(slots[0], ticket)]), [6])
