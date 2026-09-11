"""Remove incidental customer attendance from equipment reservation projections."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    events = (
        env["calendar.event"]
        .with_context(active_test=False)
        .search([("appointment_type_id.schedule_based_on", "=", "resources")])
    )
    for offset in range(0, len(events), 500):
        events[offset : offset + 500]._sync_reservations()
