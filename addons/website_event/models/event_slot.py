from datetime import datetime

from odoo import models


class EventSlot(models.Model):
    _inherit = "event.slot"

    def _filter_open_slots(self):
        upcoming_slots = self.filtered(
            lambda slot: slot.start_datetime > datetime.now()
        )

        availabilities_by_slot_id = {}
        for event in upcoming_slots.event_id:
            event_slots = upcoming_slots.filtered(
                lambda slot: slot.event_id == event  # noqa: B023  (consumed by filtered() in the same iteration)
            )
            slot_tickets = [
                (slot, ticket)
                for slot in event_slots
                for ticket in event.event_ticket_ids or [False]
            ]
            for (slot, _ticket), availability in zip(
                slot_tickets, event._get_seats_availability(slot_tickets), strict=True
            ):
                availabilities_by_slot_id.setdefault(slot.id, []).append(availability)

        return upcoming_slots.filtered(
            lambda slot: any(
                availability is None or availability > 0
                for availability in availabilities_by_slot_id[slot.id]
            )
        )
